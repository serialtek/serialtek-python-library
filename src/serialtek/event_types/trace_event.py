from typing import Any

from serialtek._model import ModelContext
from serialtek.channel import Channel
from serialtek.pcie import PcieSpeed, PcieWidth
from serialtek.timestamp import Ticks
from serialtek.util import Base91Data

from . import AnyTraceEvent


class CursorEvent(AnyTraceEvent):
    channel: Channel
    type: str
    subtype: int
    width: PcieWidth | None
    speed: PcieSpeed | None
    payload: Base91Data | None
    duration: Ticks | None

    def __init__(self, data: dict[str, Any], context: ModelContext | None) -> None:
        super().__init__(data, context)
