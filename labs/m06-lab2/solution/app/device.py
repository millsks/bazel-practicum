"""Print which accelerator this binary was built for (decided by Bazel at build time)."""

import os

from python.runfiles import runfiles

r = runfiles.Create()
for name in ("cpu", "gpu"):
    path = r.Rlocation(f"_main/app/{name}.txt")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            print(f.read().strip())
