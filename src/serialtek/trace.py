from __future__ import annotations

import logging
import secrets
import string
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional, Union, overload

from serialtek.bookmark import Bookmark, BookmarkType
from serialtek.channel import Channel
from serialtek.statistics import TraceStatistics
from serialtek.tasks import PolledTask, PollProgress, WaitParams
from serialtek.types import undocumented_constructor
from serialtek.util.json import JsonBacked

from ._model import ModelContext
from .cursor import Direction, EventCursor, NvmeBuilder, PcieBuilder
from .errors import RequestFailedError
from .timestamp import Ticks, TicksBaseFactory, TicksLike
from .util import Json, exclude_none, validate_response

if TYPE_CHECKING:
    from typing_extensions import Literal, Self
    from serialtek.event_types import AnyTraceEvent

    from .decodes import FieldDecodes
    from .filter import Filter
    from .session import ApiSession
    from .util import DevicePath

log: logging.Logger = logging.getLogger(__name__)


@undocumented_constructor
class Trace:
    """An open trace.

    To open a trace, use :py:meth:`.Kodiak.open_trace`.
    """

    #: The URI for this trace, without the host component (eg. ``/kodiak/v1/traces/0``)
    uri: str

    #: A reference to the session with this trace's Kodiak
    session: ApiSession

    #: An version of the :py:class:`.Ticks` class that is configured to use the right
    #: ticks-to-seconds conversion value for this trace.
    Ticks: TicksBaseFactory

    def __init__(
        self,
        session: ApiSession,
        uri: str,
        info: TraceInfo,
        close_options: Optional[TraceCloseOptions],
    ):
        """Create a new Trace."""
        self.uri = uri
        self.session = session
        self._trace_info = info
        self.Ticks = Ticks.with_base(info.timestamp_resolution)
        self._model_context = ModelContext(ticks_base=info.timestamp_resolution)
        self._trace_info = info
        self.close_options = close_options

    @overload
    def save(
        self,
        path: DevicePath,
        *,
        start: Optional[TicksLike] = None,
        end: Optional[TicksLike] = None,
        overwrite: bool = False,
        wait: Union[WaitParams, Literal[True]] = True,
    ) -> None:
        ...

    @overload
    def save(
        self,
        path: DevicePath,
        *,
        start: Optional[TicksLike] = None,
        end: Optional[TicksLike] = None,
        overwrite: bool = False,
        wait: Literal[False],
    ) -> PolledTask[None]:
        ...

    def save(
        self,
        path: DevicePath,
        *,
        start: Optional[TicksLike] = None,
        end: Optional[TicksLike] = None,
        overwrite: bool = False,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[None, PolledTask[None]]:
        """Save this trace.

        Specify a start and/or end timestamp to only save a portion of the trace.

        :param path: The path to save to.
        :param overwrite: Whether to overwrite an existing trace file if there's already
            one at the given path.
        :param start: Start of save range.
        :param end: End of save range.
        :param wait: Whether to wait for the save operation to complete before returning.
        """
        save_all = start is None and end is None
        if save_all:
            url = f"{self.uri}/save"
            request = {
                "path": str(path),
                "overwrite": overwrite,
            }
        else:
            if start is None:
                start = 0
            if end is None:
                end = self.Ticks.max()

            url = f"{self.uri}/save_range"
            request = {
                "path": str(path),
                "overwrite": overwrite,
                "start_ts": self.Ticks.ticks_int(start),
                "end_ts": self.Ticks.ticks_int(end),
            }

        try:
            task_info = (
                self.session.post(
                    url,
                    json=request,
                )
                .validate()
                .json()
            )
        except RequestFailedError as err:
            try:
                if (
                    err.response.status_code == 400
                    and "already exists" in err.response.json()["error"]["message"]
                ):
                    err = FileExistsError(f"A trace already exists at {path}")
            except Exception:
                log.debug("Error parsing request failure", exc_info=sys.exc_info())
            raise


        if save_all:
            task_url = f"{self.uri}/save"
        else:
            task_url = f"{self.uri}/save_range/{task_info['id']}"

        # Wait for the save task to finish.
        return PolledTask.make_task(
            "Wait for save to finish",
            poll=lambda: self.session.get(task_url).validate().json()["progress"],
            on_success=lambda _: log.info("Saved trace to %s", path),
        ).maybe_wait(wait)

    def info(self) -> TraceInfo:
        """Retrieve the trace's metadata."""
        return TraceInfo(self.session.get(f"{self.uri}").validate().json())

    def bookmarks(self):
        allBookmarks = self.session.get(f"{self.uri}/bookmarks").validate().json()
        return {
            "global": [
                Bookmark(
                    self.session,
                    f"{self.uri}/bookmarks/{t['type']}/{t['id']}",
                    self.Ticks,
                    t,
                )
                for t in allBookmarks["global"].values()
            ],
            "user": [
                Bookmark(
                    self.session,
                    f"{self.uri}/bookmarks/{t['type']}/{t['id']}",
                    self.Ticks,
                    t,
                )
                for t in allBookmarks["user"].values()
            ],
        }

    def create_bookmark(
        self,
        name: str,
        description: Optional[str] = None,
        type: BookmarkType = BookmarkType.GLOBAL,
        id: Optional[str] = None,
        color: Optional[str] = None,
        source: Optional[str] = "python",
        timestamp: Optional[TicksLike] = None,
        event: Optional[AnyTraceEvent] = None,
        end_timestamp: Optional[TicksLike] = None,
        end_event: Optional[AnyTraceEvent] = None,
        timeout_ms: int = 1000,
    ):
        """Create a bookmark

        :param name: name of the bookmark
        :param type: the type of the bookmark: `global` or `user`
        :param description: description of the bookmark
        :param id: optional id. if none is specified one will be generated after creation
        :param color: color of the bookmark, used for display
        :param source: source indicates what created the bookmark
        :param timestamp: time when the bookmark is located
        :param event: the event the bookmark is associated with. If the timestamp is not specified the timestamp will be extracetd from the event
        :param end_timestamp: time when the bookmark ends
        :param end_event: the event the bookmark ends at. If the end_timestamp is not specified the timestamp will be extracted from the event
        """
        return Bookmark.create(
            trace=self,
            name=name,
            type=type,
            id=id,
            color=color,
            source=source,
            timestamp=timestamp,
            event=event,
            end_timestamp=end_timestamp,
            end_event=end_event,
            timeout_ms=timeout_ms,
            description=description,
        )

    def global_bookmarks(self):
        return [
            Bookmark(
                self.session,
                f"{self.uri}/bookmarks/{t['type']}/{t['id']}",
                self.Ticks,
                t,
            )
            for t in self.session.get(f"{self.uri}/bookmarks/global")
            .validate()
            .json()
            .values()
        ]

    def user_bookmarks(self):
        return [
            Bookmark(
                self.session,
                f"{self.uri}/bookmarks/{t['type']}/{t['id']}",
                self.Ticks,
                t,
            )
            for t in self.session.get(f"{self.uri}/bookmarks/user")
            .validate()
            .json()
            .values()
        ]

    def tasks(self) -> List[TraceTask]:
        """Return a list of all active tasks on this trace."""
        resp = self.session.get(f"{self.uri}/tasks").validate().json()
        return [TraceTask(self.session, t["url"]) for t in resp["tasks"]]

    @overload
    def statistics(
        self,
        *,
        force: bool = False,
        upgrade: Union[bool, int] = False,
        wait: Union[WaitParams, Literal[True]] = True,
    ) -> TraceStatistics:
        ...

    @overload
    def statistics(
        self,
        *,
        force: bool = False,
        upgrade: Union[bool, int] = False,
        wait: Literal[False],
    ) -> TraceStatisticsTask:
        ...

    def statistics(
        self,
        *,
        force: bool = False,
        upgrade: Union[bool, int] = False,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[TraceStatistics, TraceStatisticsTask]:
        """Retrieve the trace statistics.

        See the :py:mod:`serialtek.statistics` documentaiton for how to use these
        statistics.

        :param force: If True, force the statistics to be recalculated even if there are
            already results present.
        :param upgrade: If True, recalculate the statistics if the stored statistics are
            not at the highest version supported by the Kodiak. If an integer,
            recaulculate the statistics if they are older than the given version. For
            example::

                trace.statistics(upgrade=9)

            will recalculate the trace statistics if the current statistics are at 8 or
            lower. The resulting statistics may be at a higher version than 9, since the
            Kodiak always creates new statistics at its current max version.
        :param wait: Whether to wait for the task to finish, or parameters to use when
            waiting.
        """
        resp = None
        id = "pynoconfig"
        body = {
            "id": id,
            # WORKAROUND: 3.45.x requires the settings field to be present, in later
            # versions it is optional (See KODSW-1870)
            "settings": {"start": 0, "end": self.Ticks.max()},
        }

        if upgrade and not force:
            # Check the existing statistics version to see if we need to upgrade.
            resp = (
                self.session.post(f"{self.uri}/statistics", json=body).validate().json()
            )

            stats_version = resp["version"]
            max_version = resp["max_version"]

            # Since we got here, upgrade is either True (meaning upgrade to max version)
            # or an integer (upgrade to at least that version).
            if upgrade is True:
                force = stats_version < max_version
            else:
                if max_version < stats_version:
                    log.warning(
                        (
                            "Requested minimum version (%d) is higher than the"
                            " Kodiak's supported version (%d)"
                        ),
                        upgrade,
                        max_version,
                    )
                    upgrade = max_version
                force = stats_version < upgrade

        if force:
            resp = (
                self.session.post(
                    f"{self.uri}/statistics", json={"force": True, **body}
                )
                .validate()
                .json()
            )

        if resp is None:
            resp = (
                self.session.post(f"{self.uri}/statistics", json=body).validate().json()
            )

        return TraceStatisticsTask(
            self.session, f"{self.uri}/statistics/{id}"
        ).maybe_wait(wait)

    def close(
        self,
        *,
        wait: Union[WaitParams, bool] = False,
        kill_tasks: Optional[bool] = None,
    ) -> None:
        """Close this trace.

        Handling of in-progress tasks, depends on the ``wait`` and ``kill_tasks``
        arguments::

            # By default, the trace will be closed immediately and in-progress tasks
            # will be killed.
            trace.close()

            # Setting `wait` will wait for tasks to complete before closing the trace.
            trace.close(wait=True)

            # You can disable both killing active tasks and waiting. This will fail to
            # close the trace and raise an exception if there are any active tasks
            # preventing it.
            trace.close(wait=True, kill_tasks=False)

        :param wait: Whether to wait for tasks to complete before closing.
        :param kill_tasks: Whether to kill in-progress tasks on close. By default (if
            ``None``), then whether to kill tasks is determined by the value of
            ``wait``: If ``wait`` is ``False`` tasks will be killed, otherwise they
            won't.
        """
        if kill_tasks is None:
            kill_tasks = wait is False
        params = {"force": "true"} if kill_tasks else None

        match wait:
            case True:
                self.wait_until_ready()
            case WaitParams() as wp:
                self.wait_until_ready(wp)
            case False:
                pass

        resp = self.session.delete(f"{self.uri}", params=params)
        validate_response(resp, success_code=[200, 202])
        log.info("Closed trace %s", self.uri)

    def open_cursor(
        self,
        timestamp: Union[TicksLike, Bookmark] = 0,
        direction: Direction = Direction.Forward,
        *,
        filter: Optional[Union[Filter, Json]] = None,
        decodes: Optional[FieldDecodes] = None,
        cursor_id: Optional[str] = None,
    ) -> EventCursor:
        """Open a cursor on this trace with the given settings.

        :param timestamp: The timestamp this cursor should be created.
        :param direction: The direction for this cursor to iterate in.
        :param filter: Optionally create this cursor with a filter.
        :param decodes: Optionally initialize field decodes for this cursor.
        :param cursor_id: An identifier for this cursor. If not sepcified, a random,
            unused id will be generated.
        """
        return EventCursor.open(
            self,
            cursor_id,
            timestamp,
            direction,
            filter=filter,
            decodes=decodes,
            ticks_type=self.Ticks,
            model_context=self._model_context,
        )

    def open_pcie_builder(
        self,
        timestamp: Union[TicksLike, Bookmark] = 0,
        direction: Direction = Direction.Forward,
        *,
        filter: Optional[Union[Filter, Json]] = None,
        decodes: Optional[FieldDecodes] = None,
        builder_id: Optional[str] = None,
    ) -> PcieBuilder:
        """Open a PCIe transaction builder on this trace with the given settings.

        :param timestamp: The timestamp this cursor should be created.
        :param direction: The direction for this cursor to iterate in.
        :param filter: Optionally create this cursor with a filter.
        :param decodes: Optionally initialize field decodes for this cursor.
        :param builder_id: An identifier for this cursor. If not sepcified, a random,
            unused id will be generated.
        """
        return PcieBuilder.open(
            self,
            builder_id,
            timestamp,
            direction,
            filter=filter,
            decodes=decodes,
            ticks_type=self.Ticks,
            model_context=self._model_context,
        )

    def open_nvme_builder(
        self,
        timestamp: Union[TicksLike, Bookmark] = 0,
        direction: Direction = Direction.Forward,
        *,
        filter: Optional[Union[Filter, Json]] = None,
        decodes: Optional[FieldDecodes] = None,
        builder_id: Optional[str] = None,
    ) -> NvmeBuilder:
        """Open an NVMe transaction builder on this trace with the given settings.

        :param timestamp: The timestamp this cursor should be created.
        :param direction: The direction for this cursor to iterate in.
        :param filter: Optionally create this cursor with a filter.
        :param decodes: Optionally initialize field decodes for this cursor.
        :param builder_id: An identifier for this cursor. If not sepcified, a random,
            unused id will be generated.
        """
        return NvmeBuilder.open(
            self,
            builder_id,
            timestamp,
            direction,
            filter=filter,
            decodes=decodes,
            ticks_type=self.Ticks,
            model_context=self._model_context,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, type: object, value: object, traceback: object) -> None:
        if self.close_options is not None:
            self.close_options.close(self)
        else:
            self.close()

    def wait_until_ready(self, wait_params: Optional[WaitParams] = None) -> None:
        """Wait for the trace to be ready to use.

        This waits for postprocessing tasks on the trace to complete, so that the trace
        is ready to be browsed/searched. This is normally done automatically by
        :py:meth:`.Kodiak.open_trace`, but if it is skipped by setting the
        ``wait_until_ready`` argument on that function to ``False``, it can be done with
        this method.

        :param wait_params: Optionally specify the parameters for waiting.
        """
        trace_info = self.info()

        if wait_params is None:
            wait_params = WaitParams()

        PolledTask.make_task(
            f"Wait for post processing on {trace_info.uri} to complete",
            poll=lambda: self.info().post_process_progress,
        ).wait(wait_params)

        def check_all_tasks():
            tasks = self.session.get(f"{self.uri}/tasks").validate().json()["tasks"]
            progresses = [_trace_task_progress(t) for t in tasks]
            progresses = [p for p in progresses if p is not True]
            return True if len(progresses) == 0 else min(progresses)

        PolledTask.make_task(
            f"Wait for tasks to finish for {trace_info.uri}",
            poll=check_all_tasks,
        ).wait(wait_params)

    @overload
    def ltssm_process(
        self,
        *,
        id: Optional[str] = None,
        uuid: Optional[str] = None,
        include_initial_archive: bool = False,
        wait: Union[WaitParams, Literal[True]] = True,
    ) -> None:
        ...

    @overload
    def ltssm_process(
        self,
        *,
        id: Optional[str] = None,
        uuid: Optional[str] = None,
        include_initial_archive: bool = False,
        wait: Literal[False],
    ) -> LtssmProcessTask:
        ...

    def ltssm_process(
        self,
        *,
        id: Optional[str] = None,
        uuid: Optional[str] = None,
        include_initial_archive: bool = False,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[None, LtssmProcessTask]:
        """Run LTSSM post processing on the trace.

        :param wait_params: Optionally specify the parameters for waiting.

        :meta private:
        """
        if id is None:
            id = _generate_task_id()

        postprocess_uri = f"{self.uri}/postprocess"
        self.session.post(
            postprocess_uri,
            json=exclude_none(
                {
                    "type": "ltssm",
                    "id": id,
                    "uuid": uuid,
                    "save": False,
                    "include_initial_archive": include_initial_archive,
                }
            ),
        ).validate(success_code=[200, 201])

        task = LtssmProcessTask(self.session, self.uri, id, self._trace_info.type)

        return task.maybe_wait(wait)


class ChannelInfo(JsonBacked, init=False):
    id: int
    subid: int
    start: Ticks
    end: Ticks

    @property
    def channel(self) -> Channel:
        return Channel({"id": self.id, "subid": self.subid})


class TraceInfo(JsonBacked, init=False):
    uri: str
    timestamp_resolution: int
    channels: list[ChannelInfo]
    post_process_progress: int
    type: str
    start: Ticks | None
    end: Ticks | None

    def __init__(self, data: Json, context: ModelContext | None = None):
        super().__init__(
            data,
            context=ModelContext(
                ticks_base=data["timestamp_resolution"]
            ).update(context)
        )

@dataclass
class TraceCloseOptions:
    """Options for closing a trace when using it as a context manager.

    The parameters for this class are the same as those of :py:meth:`.Trace.close`.
    See :py:meth:`Kodiak.open_trace()<serialtek.kodiak.Kodiak.open_trace>` for how this class is meant
    to be used.
    """

    wait: Union[WaitParams, bool] = False
    kill_tasks: Optional[bool] = None

    def close(self, trace: Trace):
        """Close a trace using these options

        :meta private:
        """
        trace.close(wait=self.wait, kill_tasks=self.kill_tasks)


@undocumented_constructor
class TraceStatisticsTask(PolledTask[TraceStatistics]):
    def __init__(self, session: ApiSession, uri: str):
        super().__init__("Wait for Statistics processing to finish")
        self.session = session
        self.uri = uri
        self._status: Any = None

    def _poll(self) -> PollProgress:
        self._status = self.session.get(self.uri).validate().json()

        return _progress_with_state(self._status["progress"], self._status["state"])

    def _get_result(self) -> TraceStatistics:
        return TraceStatistics(self._status)


class TraceTask(PolledTask[None]):
    """A representation of a task being performed on the trace.

    You can call :py:meth:`~.tasks.PolledTask.wait` to wait for this task to finish.
    """

    _session: ApiSession

    def __init__(self, session: ApiSession, url: str):
        self._session = session
        self.url = url
        super().__init__(f"Waiting for task {url} to complete")

    def _poll(self) -> PollProgress:
        # There are multiple tasks that are used with this class, not all of which have
        # the same interface. The only thing we really know is that the result should
        # have a "progress" field.
        return _trace_task_progress(self._session.get(self.url).validate().json())

    def _get_result(self) -> None:
        return None


class LtssmProcessTask(PolledTask[None]):
    """A handle for an in progress LTSSM post processing task.

    :meta private:
    """

    def __init__(
        self,
        session: ApiSession,
        uri: str,
        task_id: str,
        trace_type: str,
    ):
        super().__init__("Wait for LTSSM processing to finish")

        self.session: ApiSession = session
        self.uri: str = uri
        self.task_id: str = task_id
        self.trace_type = trace_type

    def _poll(self) -> PollProgress:
        tasks = self.session.get(f"{self.uri}/tasks").validate().json()["tasks"]

        # We already know the id we asked the server to use for this task, so look it up
        # in the task list directly rather than parsing the /postprocess response body.
        ltssm_progress = _get_task_progress_by_id(tasks, "postprocess", self.task_id)
        if ltssm_progress is not True:
            self.desc = "Wait for LTSSM processing to finish"
            return ltssm_progress

        # Live traces do not re-save out the trace after LTSSM has run
        if self.trace_type == "live":
            return True

        self.desc = "Wait for trace update to finish"
        update_tasks = [t for t in tasks if t.type == "update"]
        if not update_tasks:
            return True
        # There shouldn't be more than one update task, but if there is, just return the progress of the last one.
        return _trace_task_progress(update_tasks[-1])

    def _get_result(self):
        return None


def _generate_task_id(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _get_task_progress_by_id(
    tasks: list[Json], task_type: str, task_id: Optional[str]
) -> PollProgress:
    # If the task with provided id is not present then assume it has already completed.
    for t in tasks:
        match t:
            case {"type": ty, "task": {"id": id}} if ty == task_type and id == task_id:
                return _trace_task_progress(t)
            case _:
                continue
    return True


def _trace_task_progress(task: Json) -> PollProgress:
    match task:
        case {"progress": progress, "task": {"state": state}}:
            return _progress_with_state(progress, state)
        case {"progress": progress}:
            return progress
        case _:
            return 0.0


def _progress_with_state(progress: float, state: str) -> PollProgress:
    match state.lower():
        case "done" | "cancelled":
            return True
        case _:
            return min(99, progress)
