from enum import Enum
from typing import Iterator

from serialtek._model import ModelContext
from serialtek.channel import Channel
from serialtek.decodes import DecodedFields
from serialtek.timestamp import Ticks

from serialtek.util import Json
from serialtek.util.json import JsonBacked


class AnyTraceEvent(JsonBacked):
    """An event or transaction in a trace, retrieved from a cursor."""
    timestamp: Ticks

    def __init__(self, data: Json, context: ModelContext | None) -> None:
        super().__init__(data, context)

    @property
    def fields(self) -> DecodedFields:
        return self.inner_get_as(DecodedFields, "fields", DecodedFields([]))

    def __str__(self, *, exclude: frozenset[str] = frozenset()):
        return f"{', '.join(f'{k}={v}' for k, v in self._props_strs() if k not in exclude)}"

    def _props_strs(self) -> Iterator[tuple[str, str]]:
        yield from (
            (k, self._prop_str(k)) for k in self.raw_data
        )

    def _prop_str(self, k: str) -> str:
        a = self[k]
        match a:
            case Ticks() | Channel():
                return str(a)
            case Enum(name=name):
                return name
            case _:
                return repr(a)
