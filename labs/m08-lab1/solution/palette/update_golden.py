"""Copy the freshly generated constants.py over the checked-in golden file.

Run it with `bazel run //palette:update_golden`. Bazel starts it in its runfiles
tree; BUILD_WORKSPACE_DIRECTORY is the root of your source tree.
"""

import os
import shutil
import sys


def main(generated: str, golden: str) -> None:
    target = os.path.join(os.environ["BUILD_WORKSPACE_DIRECTORY"], golden)
    shutil.copyfile(generated, target)
    print(f"Updated {golden}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
