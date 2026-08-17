#! /usr/bin/env python

import sys
from subprocess import run

black = run("black .".split())
isort = run("isort .".split())
