import sys

import requests

from .kodiak import Kodiak, TraceService
from .cli import CliConfig
from .cursor import Direction
from .decodes import DecodeFieldId, FieldDecodes
from .filter import Filter
from .logging import configure_logging
from .session import ApiSession

# Disable insecure request warnings - Kodiaks use self signed certificates
requests.packages.urllib3.disable_warnings()  # type: ignore

__all__ = (
    "Kodiak",
    "TraceService",
    "ApiSession",
    "CliConfig",
    "FieldDecodes",
    "DecodeFieldId",
    "Filter",
    "configure_logging",
    "Direction",
)

if "pytest" in sys.modules:
    import pytest

    pytest.register_assert_rewrite("serialtek._sample_tests")
