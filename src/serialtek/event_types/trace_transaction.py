from __future__ import annotations
from typing import Any

from serialtek._model import ModelContext
from serialtek.event_types.trace_event import CursorEvent
from serialtek.timestamp import Ticks
from . import AnyTraceEvent


class AnyTransaction(AnyTraceEvent):
    type: str
    duration: Ticks | None
    events: list[CursorEvent] | None
    nvme_transactions: list[AnyTransaction] | None
    transactions: list[AnyTransaction] | None

    def __init__(self, data: dict[str, Any], context: ModelContext | None) -> None:
        super().__init__(data, context)

    def __str__(self, *, exclude: frozenset[str] = frozenset()):
        return super().__str__(exclude=exclude.union({"events", "nvme_transactions", "transactions"}))


AnyTransaction.recalculate_fields()
