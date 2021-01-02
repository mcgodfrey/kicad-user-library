import os
import re
from typing import Optional
import requests
import time
import shutil
import datetime

filename_root = 'D:/programs/kicad/user-library/user-symbols/LCSC parts'
lib_file = filename_root + '.lib'
dcm_file = filename_root + '.dcm'


def obtainCsrfTokenAndCookies():
    search_page = requests.get("https://lcsc.com/products/Pre-ordered-Products_11171.html")
    return extractCsrfToken(search_page.text), search_page.cookies


def extractCsrfToken(page_text):
    m = re.search(r"'X-CSRF-TOKEN':\s*'(.*)'", page_text)
    if not m:
        return None
    return m.group(1)


def check_files():
    if not os.path.exists(lib_file):
        raise FileNotFoundError(f"Couldn't find lib file {lib_file}")
    if not os.path.exists(dcm_file):
        raise FileNotFoundError(f"Couldn't find dcm file {dcm_file}")


def usd2aud(usd):
    if usd2aud.exchange_rate is None:
        res = requests.get('https://api.exchangeratesapi.io/latest?base=AUD&symbols=USD')
        usd2aud.exchange_rate = res.json()['rates']['USD']

    return usd/usd2aud.exchange_rate
usd2aud.exchange_rate = None


def split_string_with_quotes(s):
    return re.findall(r"(?:\".*?\"|\S)+", s)

def process_F_fields(f_fields, headers, cookies):
    price_field = None
    part_no = None
    for field in f_fields:
        cols = split_string_with_quotes(field)
        if len(cols) == 10:
            field_name = cols[9]
            if field_name == '"LCSC Part #"':
                part_no = cols[1][1:-1]  #strip quote marks
            elif field_name == '"Price"':
                price_field = field
    if part_no:
        new_price = lookup_price(part_no, headers, cookies)
        if price_field:
            split_price_field = split_string_with_quotes(price_field)
            split_price_field[1] = f'"{new_price:.4f}"'
            price_field = ' '.join(split_price_field)
        else:
            f_fields.append(f'F{len(f_fields)} "{new_price:.4f}" 0 0 50 H I C CNN "Price"')
    else:
        print(f' --Warning: No "LCSC Part #" field for part <{split_string_with_quotes(f_fields[1])[1]}>')
    return f_fields


def lookup_price(part_no, headers, cookies) -> Optional[float]:
    price = None
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
            price = lookup_price(part_no, headers, cookies)
        else:
            results = res.json()["result"]["data"]
            if len(results) != 1:
                print(f" --Warning, {part_no} doesn't have a single result/data section - len(results) = {len(results)}")
                print(res.text)
            else:
                component = res.json()["result"]["data"][0]
                if component["number"] != part_no:
                    print(f" --Warning, {part_no} result/data/number ({component['number']}) doesn't match part no")
                else:
                    price_info = component['price']
                    if len(price_info) > 0:
                        # assume that the price info list is sorted by number of parts
                        num_parts = price_info[0][0]
                        price = usd2aud(price_info[0][1])
                        if num_parts != 1:
                            print(f" --Info: {part_no} only available in min quantity {num_parts}")
                            price = price / num_parts
                    else:
                        print(f" --Warning, no price info for {part_no}")
    except Exception as e:
        print(f"  Cannot parse response for component {part_no}")
        print(f"{type(e)}")
        print(f"  Error: {e}")
        print(f"  Response: {res.text}")
        if "Bad Gateway" in res.text:
            print("Bad gateway, try again in a second")
            time.sleep(5)
    return price


def init_lcsc_connection():
    token, cookies = obtainCsrfTokenAndCookies()
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


def read_lib_file():
    headers, cookies = init_lcsc_connection()

    components = []
    current_component = None
    F_fields = None
    outfile = []
    with open(lib_file, 'r') as f:
        for line in f:
            if current_component is None:
                if line.startswith('DEF'):
                    current_component = line.split()[1]
                    print(f'{current_component}')
                    outfile.append(line)
                else:
                    outfile.append(line)
            else:
                if F_fields is None:
                    if line.startswith('F0'):
                        F_fields = [line]
                    elif line.startswith('ENDDEF'):
                        components.append(current_component)
                        current_component = None
                        outfile.append(line)
                    else:
                        outfile.append(line)
                else:
                    if line.startswith("F"):
                        F_fields.append(line)
                    else:
                        F_fields = process_F_fields(F_fields, headers, cookies)
                        outfile += F_fields
                        F_fields = None
                        outfile.append(line)

    backup_lib_file = f'{lib_file}.bak_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copyfile(lib_file, backup_lib_file)
    with open(lib_file, 'w') as f:
        f.write('\n'.join([x.rstrip() for x in outfile]))


def run():
    check_files()
    read_lib_file()


if __name__ == '__main__':
    run()
