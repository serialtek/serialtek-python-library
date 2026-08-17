import json
from typing import Any

import pytest

from serialtek.decodes import DecodeFieldId, FieldDecodes


@pytest.mark.parametrize(
    "constructor, expected",
    # fmt: off
    [
        ({"events.os": "SKP Ordered Set identifier"},        {"events": {"os": [3148453756]}}),
        ({"events.os": "SKP Ordered Set identifier"},        {"events": {"os": [3148453756]}}),
        ({"events.os": 3148453756},                          {"events": {"os": [3148453756]}}),
        ({"events": {"os": [3148453756]}},                   {"events": {"os": [3148453756]}}),
        ({"events": {"os": ["SKP Ordered Set identifier"]}}, {"events": {"os": [3148453756]}}),
        ({"events.tlp": "Fmt"}, {"events": {"tlp": [570891831]}}),
        ({"nested.unreasonably": {"many.levels": 1234}}, {"nested": {"unreasonably": {"many": {"levels": [1234]}}}}),
        ({"events.tlp": ["FP", 3937818435, DecodeFieldId("Fmt")], "events.dllp": ["Reserved"]}, {"events": {"tlp": [1320868458, 3937818435, 570891831], "dllp": [2485997111]}}),
    ]
    # fmt: on
)
def test_construct_field_decodes(constructor: Any, expected: Any):
    decodes = FieldDecodes(constructor)
    # Dump to json, because the repr for the acutal data is different (due to
    # DecodeFieldId) from the expected's repr. It works fine when the test passes, but
    # when it fails this gives better info.
    assert json.dumps(decodes.to_json()) == json.dumps(expected)
