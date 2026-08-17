#! /usr/bin/env python
from subprocess import run

pyright = run(["pyright"])
exit(pyright.returncode)
