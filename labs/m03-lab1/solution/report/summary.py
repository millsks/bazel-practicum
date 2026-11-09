"""Prints a one-line summary of catalog/prices.json.

The JSON file reaches this program as a runfile; the runfiles library finds it
no matter which directory the program is started from.
"""

import json

from python.runfiles import runfiles

from report.inventory import summary_line

r = runfiles.Create()
path = r.Rlocation("_main/catalog/prices.json")
with open(path, encoding="utf-8") as f:
    catalog = json.load(f)

print(summary_line(catalog))
