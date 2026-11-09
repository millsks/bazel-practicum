"""Prints a one-line summary of catalog/prices.json.

TODO(lab): this works in your editor's terminal from the workspace root, and
nowhere else. Make the JSON file a runfile and look it up with the rules_python
runfiles library.
"""

import json

from report.inventory import summary_line

with open("catalog/prices.json", encoding="utf-8") as f:
    catalog = json.load(f)

print(summary_line(catalog))
