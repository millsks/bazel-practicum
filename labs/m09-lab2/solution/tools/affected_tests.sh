#!/usr/bin/env bash
# Print the tests affected by the files given as arguments (paths relative to the
# workspace root), one label per line.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: bazel run //tools:affected_tests -- FILE [FILE...]" >&2
  exit 2
fi

# `bazel run` starts us inside the runfiles tree, where Bazel refuses to run.
# BUILD_WORKSPACE_DIRECTORY is the workspace the user ran `bazel run` from.
cd "${BUILD_WORKSPACE_DIRECTORY:?run this with bazel run}"

# Every test that depends on a changed file, minus the manual ones that
# `bazel test //...` would skip anyway.
query="tests(rdeps(//..., set($*))) except attr(tags, manual, //...)"

# --keep_going skips files that belong to no package (README.md, docs/...);
# Bazel then exits with 3 ("partial success"), which is fine here.
status=0
bazel query --keep_going "$query" || status=$?
if [ "$status" -ne 0 ] && [ "$status" -ne 3 ]; then
  exit "$status"
fi
