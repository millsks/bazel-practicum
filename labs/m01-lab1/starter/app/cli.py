"""The command-line entry point. Run it with: bazel run //app:cli -- --name Ada"""

import argparse

from lib.greet import greet


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a greeting.")
    parser.add_argument("--name", default="world", help="who to greet")
    args = parser.parse_args()
    print(greet(args.name))


if __name__ == "__main__":
    main()
