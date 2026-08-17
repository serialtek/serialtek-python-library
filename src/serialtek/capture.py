from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator, Optional, Union
from warnings import warn

from serialtek.tasks import PolledTask, WaitParams
from serialtek.types import undocumented_constructor

from .errors import RequestFailedError
from .util import Json, validate_response

if TYPE_CHECKING:
    from typing_extensions import Self

    from .kodiak import Kodiak
    from .lock import Lock
    from .trace import Trace

log: logging.Logger = logging.getLogger(__name__)


@dataclass
class LiveCapture:
    """Class for tracking a capture in progress.

    See :py:meth:`.Kodiak.start_capture` for more information.
    """

    _uri: str
    _lock: Lock
    _kodiak: Kodiak
    strict_locking: bool = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, type: object, value: object, traceback: object) -> None:
        self.stop()

    def join(self, wait_params: Optional[WaitParams] = None) -> None:
        """Wait for this capture to finish.

        :param wait_params: Optionally provide a :py:class:`.WaitParams` object to
            control the waiting behavior (ie, add a timeout or progress callback)
        """
        if wait_params is None:
            wait_params = WaitParams()

        PolledTask.make_task(
            "Wait for capture to finish",
            poll=lambda: not self.recording(),
        ).wait(wait_params)

        self._wait_for_live_trace()

    def recording(self) -> bool:
        """Check whether this capture is still recording."""
        status = self._kodiak.session.get("/kodiak/v1/status").validate().json()
        lock_id = status["lock"]["id"] if status["lock"] else ""
        self._check_lock(lock_id, self.strict_locking, "checking the status")
        return status["recording"] is True

    def triggered(self) -> bool:
        """Check whether this capture has triggered."""
        status = self._kodiak.session.get("/kodiak/v1/status").validate().json()
        lock_id = status["lock"]["id"] if status["lock"] else ""
        self._check_lock(lock_id, self.strict_locking, "checking the status")
        return status["triggered"] is True

    def capture_status(self) -> CaptureStatus:
        """Get the status of capture on this Kodiak.

        :return: A list of the status of all available capture channels.
        """
        return self._kodiak.capture_status()

    def stop(self) -> None:
        """Stop this capture."""
        resp = self._kodiak.session.post(
            f"{self._uri}/stop", json={"lock_key": self._lock.key}
        )

        # Workaround for KODSW-575
        time.sleep(1.5)

        validate_response(resp, permission="ConfigureCapture")
        self._wait_for_live_trace()
        log.info("Manually stopped capture")

    def open_trace(self, *, wait_until_ready: Union[bool, WaitParams] = True) -> Trace:
        """Open the trace created from this capture.

        If called before the capture has finished, this will raise
        :py:exc:`FileNotFoundError`.

        If the lock used for this capture is no longer held, a warning will be emitted.
        If ``only_if_locked`` is ``True``, a :py:exc:`RuntimeError` will be
        raised instead.
        """
        lock_info = self._kodiak.lock_status()
        self._check_lock(lock_info.id, self.strict_locking, "opening a trace")

        try:
            trace = self._kodiak.open_trace(
                "::live", wait_until_ready=wait_until_ready
            )
        except RequestFailedError as err:
            if err.response.status_code == 500:
                msg = "No live trace is available."
                raise FileNotFoundError(msg) from err
            raise

        return trace

    def trigger(self) -> None:
        """Trigger this capture."""
        resp = self._kodiak.session.post(
            f"{self._uri}/trigger", json={"lock_key": self._lock.key}
        )
        validate_response(resp)

    def _wait_for_live_trace(self) -> None:
        # The trace created by this capture isn't created immediately, but if we finish
        # now and release the lock then the trace service will take the lock back up to
        # create the trace. Wait for the trace to be created before returning.
        def try_open():
            try:
                self._kodiak.open_trace("::live", wait_until_ready=False)
            except RequestFailedError as err:
                if err.response.status_code == 500:
                    return False
                raise
            else:
                return True

        PolledTask.make_task(
            "Wait for live trace",
            poll=try_open,
            wait_defaults=WaitParams(timeout=10, poll_interval=0.5),
        ).wait()

    def _check_lock(
        self,
        id: str,
        strict: bool,
        operation: str = "performing an operation",
    ) -> None:
        if id != self._lock.id:
            if strict:
                msg = (
                    f"You are {operation} of a capture, but the lock used to start that"
                    " capture isn't still held (either it has been released, or"
                    " someone else overrode it). It is recommended to hold the lock"
                    " until all work with the live trace is done."
                )
                raise RuntimeError(msg)
            else:
                warn(
                    (
                        f"You are {operation} of a capture, but the lock used"
                        " to start that capture isn't still held (either it has been"
                        " released, or someone else overrode it). It is recommended to"
                        " hold the lock until all work with the live trace is done."
                    ),
                    stacklevel=3,
                )


@undocumented_constructor
class CaptureStatus:
    """A descripton of the Kodiak's capture status.

    The capture status consists of a list of statuses for each of the available channels
    on the Kodiak::

        >>> status = kodiak.capture_status()
        >>> status
        [DataChannelCaptureStatus(...), DataChannelCaptureStatus(...), SidebandChannelCaptureStatus(...)]
        >>> status[2]
        SidebandChannelCaptureStatus(...)
        >>> status.recording
        True
        >>> status.triggered
        False
    """

    def __init__(self, data: list[Any]):
        self.raw_data = data

    @property
    def recording(self) -> bool:
        """Whether the Kodiak is currently recording."""
        return any(r.get("recording") for r in self.raw_data)

    @property
    def triggered(self) -> bool:
        """Whether the capture's trigger condition has been met."""
        return any(r.get("triggered") for r in self.raw_data)

    def __getitem__(self, index: int) -> Json:
        return self.raw_data[index]

    def __iter__(self) -> Iterator[Json]:
        return iter(self.raw_data)
