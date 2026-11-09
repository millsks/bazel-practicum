"""Print the banner for whichever environment this binary was built for.

The program does not read any environment variable or flag at run time. Bazel decides at build time which banner
file goes into the binary's runfiles; this script prints the one it finds.
"""

import os

from python.runfiles import runfiles

r = runfiles.Create()
for env in ("dev", "staging", "prod"):
    path = r.Rlocation(f"_main/app/banners/{env}.txt")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            print(f.read().strip())
