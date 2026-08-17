from __future__ import annotations

import abc
from enum import Enum
import json
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generic,
    Iterable,
    Iterator,
    Optional,
    TypeVar,
    Union,
)
from urllib.parse import urlencode

from serialtek.bookmark import Bookmark
from serialtek.event_types.trace_event import CursorEvent
from serialtek.event_types.trace_transaction import AnyTransaction
from serialtek.types import undocumented_constructor
from serialtek.util.json import JsonBacked

from ._model import ModelContext
from .decodes import FieldDecodes
from .filter import Filter
from .timestamp import Ticks, TicksBaseFactory, TicksLike
from .util import Json, validate_response

if TYPE_CHECKING:
    from typing_extensions import Self

    from .session import ApiSession
    from .trace import Trace

log: logging.Logger = logging.getLogger(__name__)


EventType = TypeVar("EventType")
ResponseType = TypeVar("ResponseType")


class Direction(Enum):
    Forward = "Forward"
    Backward = "Backward"


@undocumented_constructor
class CursorBase(abc.ABC, Generic[EventType]):
    """Common interface for objects that allow iterating over events in a trace."""

    _path: str
    _type: Optional[str] = None

    def __init__(
        self,
        session: ApiSession,
        trace: Trace,
        uri: str,
        context: CursorContext,
        ticks_type: Optional[TicksBaseFactory] = None,
    ):
        self.trace = trace
        self.Ticks = TicksBaseFactory(None) if ticks_type is None else ticks_type
        self.session = session
        self.uri = uri
        self.context = context

    @classmethod
    def open(
        cls,
        trace: Trace,
        cursor_id: Optional[str] = None,
        timestamp: Union[TicksLike, Bookmark] = 0,
        direction: Direction = Direction.Forward,
        filter: Optional[Union[Filter, Json]] = None,
        decodes: Optional[FieldDecodes] = None,
        ticks_type: Optional[TicksBaseFactory] = None,
        model_context: Optional[ModelContext] = None,
    ) -> Self:
        """Open a new cursor in a trace.

        This won't often be called directly, see :py:meth:`.Trace.open_cursor`.

        :meta private:
        """
        if ticks_type is None:
            ticks_type = TicksBaseFactory(None)

        params: Json = {
            "timestamp": ticks_type.ticks_int(
                timestamp.timestamp if (isinstance(timestamp, Bookmark)) else timestamp
            ),
            "direction": direction.value,
        }
        if cursor_id is not None:
            params["id"] = cursor_id
        if cls._type is not None:
            params["type"] = cls._type
        resp = (
            trace.session.post(f"{trace.uri}" + cls._path, json=params)
            .validate()
            .json()
        )
        data = CursorContext(resp, ModelContext(trace.Ticks.base))
        cursor_uri = trace.uri + cls._path + "/" + data.id

        cur = cls(trace.session, trace, cursor_uri, data, ticks_type=ticks_type)

        if filter is not None:
            cur.set_filter(filter)

        if decodes is not None:
            cur.set_decodes(decodes)

        return cur

    @property
    def timestamp(self) -> Ticks:
        """The timestamp this cursor is currently pointing at.

        Setting this property will cause the cursor to jump to the given timestamp.
        """
        return self.Ticks(self.context.timestamp)

    @timestamp.setter
    def timestamp(self, value: TicksLike) -> None:
        self.update(timestamp=value)

    @property
    def direction(self) -> Direction:
        """The direction for this cursor to move.

        This can be set to change the direction.
        """
        return Direction(self.context.direction)

    @direction.setter
    def direction(self, value: Direction) -> None:
        self.update(direction=value)

    def update(
        self,
        timestamp: Optional[Union[TicksLike, Bookmark]] = None,
        direction: Optional[Direction] = None,
    ) -> None:
        """Update the parameters of this cursor.

        :param timestamp: If specified, move the cursor to this timestamp.
        :param direction: If specified, change the cursor's iteration direction to this
            value.
        """
        cursor_req: Json = {}

        if timestamp is not None:
            cursor_req["timestamp"] = self.Ticks(
                timestamp.timestamp if (isinstance(timestamp, Bookmark)) else timestamp
            )

        if direction is not None:
            cursor_req["direction"] = direction.value

        resp = self.session.patch(self.uri, json=cursor_req).validate().json()
        ctx = CursorContext(resp, ModelContext(self.trace.Ticks.base))
        self.context = ctx

    def get_events(
        self,
        count: int = 25,
        fields: Optional[Iterable[str]] = None,
        not_fields: Optional[Iterable[str]] = None,
    ) -> CursorResponse[EventType]:
        """Retrieve a number of events from this cursor with a single request.

        This will return events as unparsed json-like objects instead of parsing them
        into the models found in :py:mod:`serialtek.api`
        """
        params: Dict[str, Any] = {"count": count}

        if fields is not None and not_fields is not None:
            msg = "Cannot specify both fields and not_fields."
            raise TypeError(msg)
        elif fields is not None:
            params["fields"] = ",".join(fields)
        elif not_fields is not None:
            params["notFields"] = ",".join(not_fields)

        resp = self.session.get(
            f"{self.uri}/events", params=urlencode(params, safe=",")
        )
        validate_response(resp)
        return self._response(resp.json())

    def get(
        self,
        count: int = 0,
        *,
        start: Optional[TicksLike] = None,
        end: Optional[TicksLike] = None,
        direction: Optional[Direction] = None,
        chunk_size: int = 1000,
        filter: Optional[Union[Filter, Json]] = None,
        decodes: Optional[Union[FieldDecodes, Json]] = None,
        fields: Optional[Iterable[str]] = None,
        not_fields: Optional[Iterable[str]] = None,
    ) -> Iterator[EventType]:
        """Iterate through events in this trace.

        :param count: Retrieve up to this many events. If 0, retrieve events
            indefinitely.
        :param start: Starting timestamp.
        :param end: If specified, only return events up to this timestamp.
        :param direction: The direction to iterate. If not specified, it will be
            inferred based on the start and end values if both are present, or else will
            default to the cursor's current direction.
        :param filter: If specified, set the filter on the cursor to this value before
            starting.
        :param chunk_size: How many events to get in each network request.
        :param fields: If specified, only retrieve the named fields (type, timestamp,
            and channel are always included). Mutually exclusive with ``not_fields``.
        :param not_fields: If specified, do not retrieve the named fields (type,
            timestamp, and channel are always included). Mutually exclusive with
            ``fields``.
        :param raw: if ``True``, this will return events as unparsed json-like objects
            instead of parsing them into the models found in :py:mod:`serialtek.event_types`
        :return: An iterator yielding :py:class:`~serialtek.event_types.trace_event.CursorEvent` objects (or
            events as raw json if ``raw`` is set).
        """
        start = self.Ticks(start) if start is not None else self.timestamp

        # Figure out the direction to iterate
        if end is not None:
            end = self.Ticks(end)
            expected_direction = (
                Direction.Forward if start < end else Direction.Backward
            )
            if direction is None:
                direction = expected_direction
            elif direction != expected_direction:
                msg = (
                    f"start={start} and end={end} implies iterating"
                    f" {expected_direction.value}, but direction is {direction!r}"
                )
                raise ValueError(msg)

        if direction is None:
            direction = self.direction

        if filter is not None:
            self.set_filter(filter)

        if decodes is not None:
            self.set_decodes(decodes)

        total = 0
        self.update(start, direction)

        while count == 0 or total < count:
            to_get = min(chunk_size, count - total) if count else chunk_size

            result = self.get_events(to_get, fields=fields, not_fields=not_fields)
            for evt in result.iter():
                if end is not None and result.timestamp > end:
                    return

                yield evt
                total += 1

            if result.at_end:
                return

    def set_filter(self, filter: Union[Filter, Json]) -> None:
        """Set the filter for this cursor.

        :param filter: Either a :py:class:`~.filter.Filter` or a json-like object
            containing raw filter data.
        """
        if isinstance(filter, Filter):
            data = json.dumps(filter.to_json(self.trace))
        else:
            data = json.dumps(filter)
        resp = self.session.put(f"{self.uri}/filter", data=data)
        validate_response(resp)
        log.info("Set filter on cursor %s", self.context.id)
        log.debug("Set filter on cursor %s to %s", self.context.id, data)

    def set_decodes(self, decodes: Union[FieldDecodes, Json]) -> None:
        """Set the field decodes for this cursor.

        :param decodes: A :py:class:`~.decodes.FieldDecodes` object containing the
            decodes to use.

        .. code-block::

            from serialtek.decodes import FieldDecodes

            # Decode the Type field for DLLPs and the STP and FCRC field for TLPs
            cursor.set_decodes(FieldDecodes({
                "events.dllp": "Type",
                "events.tlp": ["STP", "FCRC"]
            }))

        You can also use any number of json definitions copied directly from the web ui
        to initialize :py:class:`~.decodes.FieldDecodes`, so this code is equivalent to
        the above::

            cursor.set_decodes(FieldDecodes(
                {"events": {"dllp": [2717525879]}},
                {"events": {"tlp": [1772807117]}},
                {"events": {"tlp": [3937818435]}},
            )
        """
        data = decodes.to_json() if isinstance(decodes, FieldDecodes) else decodes
        resp = self.session.put(f"{self.uri}/field_decodes", json=data)
        validate_response(resp)
        log.info("Set decodes on cursor %s", self.context.id)
        log.debug("Set decodes on cursor %s to %s", self.context.id, data)

    def close(self) -> bool:
        """Close this cursor."""
        resp = self.session.delete(self.uri)
        if resp.status_code == 200 or resp.status_code == 202:
            return True
        return False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, type: object, value: object, traceback: object) -> None:
        self.close()

    @abc.abstractmethod
    def _response(self, data: Json) -> CursorResponse[EventType]:
        ...


class EventCursor(CursorBase[CursorEvent]):
    """A cursor that can be used to iterate over events in a trace.

    The main way to create a cursor is from an open :py:class:`~.trace.Trace` using the
    :py:meth:`.Trace.open_cursor` method::

        with kodiak.open_trace("/media/NVMeDrive0/my_trace.sttrace") as trace:
            with trace.open_cursor("000.000.045.123.5") as cur:
                # Do something with cur...

    A cursor can be used as a context manager, as shown above. If it is not, then
    :py:meth:`.CursorBase.close()` should be called when done.

    See :py:class:`.CursorBase` for a description of methods available to an
    EventCursor.
    """

    _path = "/cursors"

    def _response(self, data: Json) -> CursorResponse[CursorEvent]:
        return EventCursorResponse(data, ModelContext(self.Ticks.base))


class PcieBuilder(CursorBase[AnyTransaction]):
    """A transaction builder that can be used to iterate over PCIe Transactions in a trace.

    The main way to create this is from an open :py:class:`~.trace.Trace` using the
    :py:meth:`.Trace.open_pcie_builder` method::

        with kodiak.open_trace("/media/NVMeDrive0/my_trace.sttrace") as trace:
            with trace.open_pcie_builder("000.000.045.123.5") as builder:
                # Do something with builder...

    A transaction builder can be used as a context manager, as shown above. If it is
    not, then :py:meth:`.CursorBase.close()` should be called when done.

    See :py:class:`.CursorBase` for a description of methods available to a PcieBuilder.
    """

    _path = "/transactions"
    _type = "pcie"

    def _response(self, data: Json) -> CursorResponse[AnyTransaction]:
        return TransactionBuilderResponse(data, ModelContext(self.Ticks.base))

class NvmeBuilder(CursorBase[AnyTransaction]):
    """A transaction builder that can be used to iterate over NVMe Transactions in a trace.

    The main way to create this is from an open :py:class:`~.trace.Trace` using the
    :py:meth:`.Trace.open_nvme_builder` method::

        with kodiak.open_trace("/media/NVMeDrive0/my_trace.sttrace") as trace:
            with trace.open_nvme_builder("000.000.045.123.5") as builder:
                # Do something with builder...

    A transaction builder can be used as a context manager, as shown above. If it is
    not, then :py:meth:`.CursorBase.close()` should be called when done.

    See :py:class:`.CursorBase` for a description of methods available to an NvmeBuilder.
    """

    _path = "/transactions"
    _type = "nvme"

    def _response(self, data: Json) -> CursorResponse[AnyTransaction]:
        return TransactionBuilderResponse(data, ModelContext(self.Ticks.base))

class DoeCursor(CursorBase[CursorEvent]):
    """A cursor that can be used to iterate over events in a trace.

    The main way to create a cursor is from an open :py:class:`~.trace.Trace` using the
    :py:meth:`.Trace.open_doe_cursor` method::

        with kodiak.open_trace("/media/NVMeDrive0/my_trace.sttrace") as trace:
            with trace.open_doe_cursor("000.000.045.123.5") as cur:
                # Do something with cur...

    A cursor can be used as a context manager, as shown above. If it is not, then
    :py:meth:`.CursorBase.close()` should be called when done.

    See :py:class:`.CursorBase` for a description of methods available to an
    DoeCursor.
    """

    _path = "/doe_cursors"

    def _response(self, data: Json) -> CursorResponse[CursorEvent]:
        return EventCursorResponse(data, ModelContext(self.Ticks.base))

class CursorContext(JsonBacked, init = False):
    id: str
    direction: Direction
    timestamp: Ticks


class CursorResponse(Generic[EventType], CursorContext, init = False):
    at_end: bool

    @abc.abstractmethod
    def iter(self) -> Iterator[EventType]:
        ...


class EventCursorResponse(CursorResponse[CursorEvent], init=False):
    def iter(self) -> Iterator[CursorEvent]:
        yield from (CursorEvent(e, self._context) for e in self["events"])


class TransactionBuilderResponse(CursorResponse[AnyTransaction], init=False):
    def iter(self) -> Iterator[AnyTransaction]:
        yield from (AnyTransaction(e, self._context) for e in self["transactions"])
