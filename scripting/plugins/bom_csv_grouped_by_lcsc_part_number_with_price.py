#
# Example python script to generate a BOM from a KiCad generic netlist
#
# Example: Sorted and Grouped CSV BOM
#
"""
    @package
    Generate a csv BOM list.
    Components are sorted by ref and grouped by value
    Fields are (if exist)
    Item, Qty, Reference(s), Value, LibPart, Footprint, Datasheet

    Command line:
    python "pathToFile/bom_csv_grouped_by_value.py" "%I" "%O.csv"
"""

from __future__ import print_function

# Import the KiCad python helper module and the csv formatter
import kicad_netlist_reader
import csv
import sys
import requests
import re
import time
import datetime
import shelve
import tempfile
import os

cache_filename = os.path.join(tempfile.gettempdir(), 'lcsc_part_cache')
exchange_rate = None


def generate_bom(net, f, headers, cookies):

    part_cache = PartCache(cache_filename, ttl=None)

    # subset the components to those wanted in the BOM, controlled
    # by <configure> block in kicad_netlist_reader.py
    components = net.getInterestingComponents()
    # Group them, based on the myEqu comparison function (which matches LCSC Part #)
    grouped = net.groupComponents(components)

    columns = ['Item', 'LCSC Part #', 'Qty', 'Reference(s)', 'Value', 'LibPart', 'Footprint',
               'LCSC Footprint', 'Price per unit', 'Price total', 'in stock']

    # Create a new csv writer object to use as the output formatter
    out = csv.writer(f, lineterminator='\n', delimiter=',', quotechar='\"', quoting=csv.QUOTE_ALL)

    # override csv.writer's writerow() to support encoding conversion (initial encoding is utf8):
    def writerow(acsvwriter, cols):
        utf8row = []
        for col in cols:
            utf8row.append(str(col))  # currently, no change
        acsvwriter.writerow(utf8row)

    # Output a set of rows as a header providing general information
    writerow(out, ['Source:', net.getSource()])
    writerow(out, ['Date:', net.getDate()])
    writerow(out, ['Tool:', net.getTool()])
    writerow(out, ['Generator:', sys.argv[0]])
    writerow(out, ['Component Count:', len(components)])
    writerow(out, ['Unique component Count:', len(grouped)])
    writerow(out, [])                        # blank line
    writerow(out, columns)

    cumulative_total_price = 0
    items_without_price = []
    # Print a line for each group
    for index, group in enumerate(grouped):
        row = []
        # generate a list of all the references for this component
        refs = ', '.join([component.getRef() for component in group])
        first_component = group[0]  # used to get comonent info (should be the same for all the components in the group
        lcsc_part_no = first_component.getField('LCSC Part #')
        
        if lcsc_part_no != '':
            price, in_stock, footprint = lookup_part_info(lcsc_part_no, part_cache, headers, cookies)
            if isinstance(price, float):
                total_price = price * len(group)
                cumulative_total_price += total_price
            else:
                total_price = 'Error'
                items_without_price.append(first_component.getPartName())
        else:
            price = ''
            total_price = ''
            in_stock = ''
            footprint = ''
            items_without_price.append(first_component.getPartName())

        # Fill in the component groups common data
        # columns = ['Item', 'LCSC Part #', 'Qty', 'Reference(s)', 'Value', 'LibPart', 'Footprint']
        row.append(index)
        row.append(lcsc_part_no)
        row.append(len(group))
        row.append(refs)
        row.append(first_component.getValue())
        row.append(first_component.getLibName() + ":" + first_component.getPartName())
        row.append(net.getGroupFootprint(group))
        row.append(footprint)
        row.append(price)
        row.append(total_price)
        row.append(in_stock)

        writerow(out, row)

    print('Total price: {}'.format(cumulative_total_price))
    print('Num items without price: {}'.format(len(items_without_price)))
    for item in items_without_price:
        print('   {}'.format(item))


def myEqu(self, other):
    """myEqu is a more advanced equivalence function for components which is
    used by component grouping. Normal operation is to group components based
    on their value and footprint.

    In this case, group by LCSC Part #, and then also check that the footpring, value and library match, and print a warning if they don't
    """
    result = False
    fields_to_check = ['getFootprint', 'getValue', 'getLibPart']
    if self.getField('LCSC Part #') == other.getField('LCSC Part #'):
        if self.getField('LCSC Part #') != '':
            result = True  # set result to true. Then if any of the fields below don't match, it will be set back to false.
            for field in fields_to_check:
                val1 = getattr(self, field)()
                val2 = getattr(other, field)()
                if val1 != val2:
                    result = False
                    print('Warning components {} and {} have matching LCSC Part # ({}) but {}() mismatch: <{}> - <{}>'.format(self.getRef(), other.getRef(), self.getField('LCSC Part #'), field, val1, val2))

    return result
    
    
def check_args():
    if len(sys.argv) != 3:
        print("Usage ", __file__, "<generic_netlist.xml> <output.csv>", file=sys.stderr)
        sys.exit(1)
        

def get_output_file():
    """
    append .csv if necessary to the output file, and then open it for writing
    """
    outfile_name = sys.argv[2]
    if not outfile_name.endswith('.csv'):
        outfile_name += '.csv'
    f = open(outfile_name, 'w')
    return f


# LCSC lookup functions
def obtain_csrf_token_and_cookies():
    search_page = requests.get("https://lcsc.com/products/Pre-ordered-Products_11171.html")
    return extract_csrf_token(search_page.text), search_page.cookies


def extract_csrf_token(page_text):
    m = re.search(r"'X-CSRF-TOKEN':\s*'(.*)'", page_text)
    if not m:
        return None
    return m.group(1)
    

def usd2aud(usd):
    return usd/get_exchange_rate()


def get_exchange_rate():
    global exchange_rate
    if exchange_rate is None:
        res = requests.get('https://api.exchangeratesapi.io/latest?base=AUD&symbols=USD')
        exchange_rate = res.json()['rates']['USD']
    return exchange_rate


def lookup_part_info(part_no, part_cache, headers, cookies):
    part = part_cache[part_no]
    if part is None:
        part = lcsc_lookup(part_no, headers, cookies)
        part_cache[part_no] = part

    return part


def lcsc_lookup(part_no, headers, cookies):
    price = None
    in_stock = None
    footprint = None
    res = requests.post("https://lcsc.com/api/products/search",
                        headers=headers, cookies=cookies,
                        data={
                            "current_page": "1",
                            "in_stock": "false",
                            "is_RoHS": "false",
                            "show_icon": "false",
                            "search_content": part_no,
                        })
    try:
        if "exceeded the maximum number of attempts" in res.text or res.json()["code"] == 429:
            print("Too many requests! Waiting")
            time.sleep(10)
            price = lcsc_lookup(part_no, headers, cookies)
        else:
            results = res.json()["result"]["data"]
            if len(results) != 1:
                print(" --Warning, {} doesn't have a single result/data section - len(results) = {}".format(part_no, len(results)))
                print(res.text)
            else:
                component = res.json()["result"]["data"][0]
                if component["number"] != part_no:
                    print(" --Warning, {} result/data/number ({}) doesn't match part no".format(part_no, component['number']))
                else:
                    in_stock = component['stock']
                    footprint = component['package']
                    price_info = component['price']
                    if len(price_info) > 0:
                        # assume that the price info list is sorted by number of parts
                        price = usd2aud(price_info[0][1])
                    else:
                        print(" --Warning, no price info for {}".format(part_no))
    except Exception as e:
        print("  Cannot parse response for component {}".format(part_no))
        print("{}".format(type(e)))
        print("  Error: {}".format(e))
        print("  Response: {}".format(res.text))
        if "Bad Gateway" in res.text:
            print("Bad gateway, try again in a second")
            time.sleep(5)
    time.sleep(0.5)
    return price, in_stock, footprint


def init_lcsc_connection():
    token, cookies = obtain_csrf_token_and_cookies()
    headers = {
        'pragma': 'no-cache',
        'cache-control': 'no-cache',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'x-csrf-token': token,
        'x-requested-with': 'XMLHttpRequest',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36',
        'isajax': 'true',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'origin': 'https://lcsc.com',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'referer': 'https://lcsc.com',
        'accept-language': 'cs,en;q=0.9,sk;q=0.8,en-GB;q=0.7',
    }
    return headers, cookies


class PartCache:
    def __init__(self, filename, ttl=None):
        self.filename = filename
        self.ttl = ttl
        shelf = shelve.open(filename)
        shelf['last_opened'] = datetime.datetime.now()
        if 'data' not in shelf:
            shelf['data'] = dict()
        shelf.close()

    def __getitem__(self, item, default=None):
        shelf = shelve.open(self.filename)
        try:
            data = shelf['data'][item]
            if self.ttl is not None:
                update_timestamp = data['update_timestamp']
                if (datetime.datetime.now() - update_timestamp).total_seconds() > self.ttl:
                    result = default
                else:
                    result = data['data']
            else:
                result = data['data']
            # print('read item {} from cache, data=<{}>'.format(item, data))
        except KeyError:
            result = default
            # print('item {} not in cache.'.format(item))

        shelf.close()

        return result

    def __setitem__(self, key, value):
        shelf = shelve.open(self.filename)
        new_data = {
            'update_timestamp': datetime.datetime.now(),
            'data': value
        }
        existing_data = shelf['data']
        existing_data[key] = new_data
        shelf['data'] = existing_data
        # print('added item {} to cache, data=<{}>'.format(key, new_data))
        shelf.close()


def run():
    check_args()
    
    # Override the component equivalence operator - it is important to do this
    # before loading the netlist, otherwise all components will have the original
    # equivalency operator.
    kicad_netlist_reader.comp.__eq__ = myEqu

    # Generate an instance of a generic netlist, and load the netlist tree from
    # the command line option. If the file doesn't exist, execution will stop
    net = kicad_netlist_reader.netlist(sys.argv[1])
    
    headers, cookies = init_lcsc_connection()

    outfile = get_output_file()
    generate_bom(net, outfile, headers, cookies)
    outfile.close()
    

if __name__ == '__main__':
    run()
