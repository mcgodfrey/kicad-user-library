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


def generate_bom(net, f):

    # subset the components to those wanted in the BOM, controlled
    # by <configure> block in kicad_netlist_reader.py
    components = net.getInterestingComponents()
    # Group them, based on the myEqu comparison function (which matches LCSC Part #)
    grouped = net.groupComponents(components)

    columns = ['Item', 'LCSC Part #', 'Qty', 'Reference(s)', 'Value', 'LibPart', 'Footprint']

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

    # Print a line for each group
    for index, group in enumerate(grouped):
        row = []
        # generate a list of all the references for this component
        refs = ', '.join([component.getRef() for component in group])
        first_component = group[0]  # used to get comonent info (should be the same for all the components in the group

        # Fill in the component groups common data
        # columns = ['Item', 'LCSC Part #', 'Qty', 'Reference(s)', 'Value', 'LibPart', 'Footprint']
        row.append(index)
        row.append(first_component.getField('LCSC Part #'))
        row.append(len(group))
        row.append(refs)
        row.append(first_component.getValue())
        row.append(first_component.getLibName() + ":" + first_component.getPartName())
        row.append(net.getGroupFootprint(group))

        writerow(out, row)


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


def run():
    check_args()
    
    # Override the component equivalence operator - it is important to do this
    # before loading the netlist, otherwise all components will have the original
    # equivalency operator.
    kicad_netlist_reader.comp.__eq__ = myEqu

    # Generate an instance of a generic netlist, and load the netlist tree from
    # the command line option. If the file doesn't exist, execution will stop
    net = kicad_netlist_reader.netlist(sys.argv[1])

    outfile = get_output_file()
    generate_bom(net, outfile)
    outfile.close()
    

if __name__ == '__main__':
    run()