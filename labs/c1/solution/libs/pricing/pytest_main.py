"""Entry point for py_test targets that run pytest.

Bazel runs a py_test's `main` file as a script. This one hands the command-line
arguments (the test files, from the target's `args`) to pytest and exits with
pytest's status, so a failing test fails the Bazel test.
"""

import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:]))
