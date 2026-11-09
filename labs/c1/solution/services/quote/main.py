"""Command line: quote WIDGET=2 GADGET ..."""

import sys

from services.quote import quote

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: quote SKU[=QTY] ...", file=sys.stderr)
        sys.exit(2)
    print(quote.render(sys.argv[1:]))
