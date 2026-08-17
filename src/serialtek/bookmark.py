from __future__ import annotations

from enum import Enum
import logging
from typing import TYPE_CHECKING, Optional

from .util import Json, exclude_none, validate_response

if TYPE_CHECKING:
    from serialtek.event_types import AnyTraceEvent
    from serialtek.timestamp import Ticks
    from serialtek.timestamp import TicksBaseFactory, TicksLike
    from serialtek.trace import Trace

    from .session import ApiSession

log = logging.getLogger(__name__)


class BookmarkType(Enum):
    GLOBAL = "global"
    USER = "user"


class Bookmark:
    def __init__(
        self,
        session: ApiSession,
        uri: str,
        Ticks: TicksBaseFactory,
        data: Json,
    ):
        self.uri = uri
        self.session = session
        self.data = data
        self.Ticks = Ticks

    @classmethod
    def create(
        cls,
        *,
        trace: Trace,
        name: str,
        type: BookmarkType = BookmarkType.GLOBAL,
        description: Optional[str] = None,
        id: Optional[str] = None,
        color: Optional[str] = None,
        source: Optional[str] = "python",
        timestamp: Optional[TicksLike] = None,
        event: Optional[AnyTraceEvent] = None,
        end_timestamp: Optional[TicksLike] = None,
        end_event: Optional[AnyTraceEvent] = None,
        timeout_ms: int = 1000,
    ) -> Bookmark:
        """create a bookmark.

        :param trace: the trace to which the bookmark will be attached
        :param name: name of the bookmark
        :param type: the type of the bookmark: `global` or `user`
        :param description: description of the bookmark
        :param id: optional id. if none is specified one will be generated after creation
        :param color: color of the bookmark, used for display
        :param source: source indicates what created the bookmark
        :param timestamp: time when the bookmark is located
        :param event: the event the bookmark is associated with. If the timestamp is not specified the timestamp will be extracted from the event
        :param end_timestamp: time when the bookmsrk ends
        :param end_event: the event the bookmark ends at. If the end_timestamp is not specified the timestamp will be extracted from the event
        """
        if timestamp is not None:
            timestamp = trace.Ticks(timestamp)
        if event is not None:
            timestamp = trace.Ticks(event.timestamp)
        if timestamp is None:
            msg = "Must specify a start of bookmark"
            raise TypeError(msg)

        if end_timestamp is not None:
            end_timestamp = trace.Ticks(end_timestamp)
        if end_event is not None:
            end_timestamp = trace.Ticks(end_event.timestamp)

        assert trace.Ticks.base is not None

        resp = (
            trace.session.post(
                f"{trace.uri}/bookmarks/{type}",
                params={"timeout": timeout_ms},
                json=exclude_none(
                    {
                        "name": name,
                        "id": id,
                        "color": color,
                        "source": source,
                        "timestamp": timestamp,
                        "event": (event.raw_data if event else None),
                        "end_timestamp": end_timestamp,
                        "end_event": (end_event.raw_data if end_event else None),
                        "description": description,
                        "timestamp_resolution": trace.Ticks.base,
                    }
                ),
            )
            .validate()
            .json()
        )

        return Bookmark(
            trace.session,
            f"{trace.uri}/bookmarks/{resp['type']}/{resp['id']}",
            trace.Ticks,
            resp,
        )

    def update(
        self,
        *,
        name: Optional[str] = None,
        color: Optional[str] = None,
        source: Optional[str] = None,
        timestamp: Optional[TicksLike] = None,
        event: Optional[AnyTraceEvent] = None,
        end_timestamp: Optional[TicksLike] = None,
        end_event: Optional[AnyTraceEvent] = None,
        timeout_ms: int = 1000,
    ):
        """Modify this bookmark.

        :param name: name of the bookmark
        :param description: description of the bookmark
        :param color: color of the bookmark, used for display
        :param source: source indicates what created the bookmark
        :param timestamp: time when the bookmark is locaetd
        :param event: the event the bookmark is associated with
        :param end_timestamp: time when the bookmark ends
        :param end_event: the event the bookmark ends at
        """
        if timestamp is not None:
            timestamp = self.Ticks(timestamp)
        if event is not None:
            timestamp = self.Ticks(event.timestamp)

        resp = self.session.patch(
            f"{self.uri}",
            params={"timeout": timeout_ms},
            json=exclude_none(
                {
                    "name": name if name is not None else self.data["name"],
                    "color": color,
                    "source": source,
                    "event": (event.raw_data if event else None),
                    "end_timestamp": end_timestamp,
                    "end_event": (end_event.raw_data if end_event else None),
                    "timestamp_resolution": self.Ticks.base,
                }
            ),
        )

        self.data = resp.validate().json()

    def delete(
        self,
    ):
        """Delete this bookmark."""
        resp = self.session.delete(f"{self.uri}")
        validate_response(resp)

    @property
    def timestamp(self) -> Ticks:
        """The start timestamp of this event"""
        return self.Ticks(self.data["timestamp"])
