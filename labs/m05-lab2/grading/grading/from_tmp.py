"""Run the command in argv from /tmp, to prove a test does not depend on its working directory."""

import os
import sys

program = os.path.abspath(sys.argv[1])
os.chdir("/tmp")
os.execv(program, [program, *sys.argv[2:]])
