"""Prints a greeting. Bazel runs this file as the main module of //hello:hello."""

from hello.greeting import greeting

print(greeting("Bazel"))
