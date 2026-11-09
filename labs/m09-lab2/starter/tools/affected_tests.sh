#!/usr/bin/env bash
# Print the tests affected by the files given as arguments (paths relative to the
# workspace root), one label per line.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: bazel run //tools:affected_tests -- FILE [FILE...]" >&2
  exit 2
fi

# TODO: this is only the first step. It prints every target that depends on the
# files, not just the tests, and it does not work at all under `bazel run` yet.
bazel query "rdeps(//..., set($*))"
