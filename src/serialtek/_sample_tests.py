"""
This module provides some helper functions to be used when writing runnable example
tests for documentation. It should not be used during normal operation.
"""

import os
import textwrap
from typing import Any, List

_print = print
_output: List[str] = []


def init():
    global _output
    _output = []


def print(*args: Any, **kwargs: Any):
    _print(*args, **kwargs)
    _output.append(str(args[0]))


def expect_output(name: str, output: str):
    global _output
    if "PYTEST_CURRENT_TEST" in os.environ:
        actual_output = "\n".join(_output)
        assert actual_output.strip() == textwrap.dedent(output.lstrip("\n")).strip()
    _output = []
