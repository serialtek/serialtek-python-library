from __future__ import annotations

import abc
import logging
import time
from dataclasses import asdict, dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Optional,
    TypeAlias,
    TypeVar,
    Union,
)

if TYPE_CHECKING:
    from typing_extensions import Self

log: logging.Logger = logging.getLogger(__name__)

PollProgress: TypeAlias = Union[float, bool]
ResultType = TypeVar("ResultType")
T = TypeVar("T")


@dataclass(frozen=True)
class WaitParams:
    """A set of parameters to use when waiting for an event.

    Some functions that need to wait for the Kodiak to do something will take a
    :py:class:`.WaitParams` as an optional parameter to change the details of how to
    wait for the event::

        # Save a trace, but raise a TimeoutException if doing so takes longer than 10 seconds
        trace.save("/media/NVMeDrive0/my_trace", wait=WaitParams(timeout=10))
    """

    #: How long to wait in total before giving up, in seconds. If waiting takes longer
    #: than this, a :py:exc:`TimeoutException` will be raised, but the underlying task
    #: won't be cancelled. If 0, then wait indefinitely. Default: 0
    timeout: Optional[float] = None

    #: How long to wait between checking whether the condition has been met, in seconds.
    #: Default: 1
    poll_interval: Optional[float] = None

    #: An optional callback that should have the signature
    #: ``progress_cb(desc: str, progress: Union[float, bool])->None``.
    #: It will will be periodically called while waiting, with two arguments:
    #:
    #:   :param desc: A short description of the waiting task.
    #:   :param progress: One of:
    #:
    #:     * ``True`` : The task has completed
    #:     * ``False``: The task has not completed, and no estimated
    #:       completion percentage is available.
    #:     * a float value: The task has not completed, and this is the
    #:       estimated completion percentage.
    #:
    #: This function will not be called if no waiting takes place, but if it is called
    #: then it will always be called once with a progress of ``True`` when the waiting
    #: completes.
    progress_cb: Optional[Callable[[str, Union[float, bool]], None]] = None

    def update(self, other: Optional[WaitParams] = None, **kwargs: Any) -> Self:
        """Return a new WaitParams with the specified values changed.

        You can update either from another :py:class:`.WaitParams`, or update individual
        fields::

            >>> original = WaitParams(timeout=1, poll_interval=2)
            >>> updated = original.update(WaitParams(timeout=3))
            >>> updated
            WaitParams(timeout=3, poll_interval=2, progress_cb=None)
            >>> updated2 = original.update(poll_interval=5)
            >>> updated2
            WaitParams(timeout=1, poll_interval=5, progress_cb=None)
        """
        params = asdict(self)
        if other:
            params.update({k: v for k, v in asdict(other).items() if v is not None})
        params.update(kwargs)

        return self.__class__(**params)

    def get_timeout(self, default: float = 0) -> float:
        """Get the timeout value from these params, or a default value."""
        if self.timeout is None:
            return default
        else:
            return self.timeout

    def get_poll_interval(self, default: float = 1) -> float:
        """Get the poll interval from these params, or a default value."""
        if self.poll_interval is None:
            return default
        else:
            return self.poll_interval


class PolledTask(Generic[ResultType], abc.ABC):
    """Handle for a task that is running on the Kodiak.

    Many functions that take a :py:class:`.WaitParams` can be passed `False` for the
    wait argument instead, in which case they will return a :py:class:`.PolledTask`.
    Call :py:meth:`wait` to wait for the task to finish and get its result.

    Most tasks that need to wait for the Kodiak to finish something are implemented
    using a :py:class:`PolledTask`. For example, :py:meth:`.Path.compress` waits for
    compression to complete, then returnes the path to the new archive::

        # Using the default value for the `wait` param, which is True
        >>> path = kodiak.Path("/media/NVMeDrive0/trace.sttrace").compress()
        # (time passes)
        >>> path
        KodiakPath("/media/NVMeDrive0/trace.sttrace.gz")

    If you pass ``False`` for the ``wait`` parameter, the function will return a
    :py:class:`.path.CompressionTask` (which is a subclass of PolledTask), which can
    then be waited on.

        >>> task = kodiak.Path("/media/NVMeDrive0/trace.sttrace").compress()
        # returns a CompressionTask immediately
        >>> path = task.wait()
        # (time passes)
        >>> path
        KodiakPath("/media/NVMeDrive0/trace.sttrace.gz")
    """

    #: A human-readable description of this task.
    desc: str

    _wait_defaults: WaitParams
    _finished: bool

    def __init__(
        self,
        desc: str,
        *,
        wait_defaults: Optional[WaitParams] = None,
    ):
        self.desc = desc
        if wait_defaults is None:
            self._wait_defaults = WaitParams()
        else:
            self._wait_defaults = wait_defaults
        self._finished = False

    @staticmethod
    def make_task(
        desc: str,
        *,
        poll: Callable[[], PollProgress],
        get_result: Callable[[], T] = lambda: None,
        on_success: Callable[[T], None] = lambda _: None,
        wait_defaults: Optional[WaitParams] = None,
    ) -> PolledTask[T]:
        """Helper function for creating a simple task.

        :meta private:
        """

        class SimplePolledTask(PolledTask[Any]):
            def _poll(self) -> PollProgress:
                return poll()

            def _get_result(self) -> T:
                return get_result()

            def _on_success(self, result: T) -> None:
                on_success(result)

        return SimplePolledTask(desc, wait_defaults=wait_defaults)

    def wait(self, params: Optional[WaitParams] = None) -> ResultType:
        """Wait for this task to complete, and return its result."""
        if params is None:
            params = WaitParams()
        params = params.update(self._wait_defaults)
        timeout = params.get_timeout(0)
        poll_interval = params.get_poll_interval(1)

        start_time = time.monotonic()

        def done(p: PollProgress) -> bool:
            return p if isinstance(p, bool) else p >= 100

        progress = self.poll()

        if done(progress):
            log.debug("Task %r is already done, no need to wait.", self.desc)
        if not done(progress):
            log.info("%s...", self.desc)
            if params.progress_cb:
                params.progress_cb(self.desc, progress)

        last_progress: Optional[float] = None

        while not done(progress):
            if timeout > 0 and time.monotonic() - start_time > timeout:
                msg = "An operation timed out"
                raise TimeoutError(msg)
            time.sleep(poll_interval)
            progress = min(self.poll(), 100)

            if params.progress_cb:
                if done(progress):
                    params.progress_cb(self.desc, True)
                else:
                    params.progress_cb(self.desc, progress)

            if not isinstance(progress, bool) and (
                self.desc
                and progress
                != last_progress  # pyright: ignore[reportUnnecessaryComparison]
            ):
                last_progress = progress
                log.debug("%s (%d%%)", self.desc, progress)

        return self.get_result()

    def maybe_wait(self, params: Union[WaitParams, bool]) -> Union[Self, ResultType]:
        """Wait for this task to finish or return the task's handle.

        It's a common pattern for a function that might wait for something to take an
        argument that's either:

        * True: wait, with default parameters.
        * False: Don't wait.
        * :py:class:`.WaitParams`: Use custom wait parameters.

        This is a convenience function that handles that logic.

        :meta private:
        """
        match params:
            case False:
                return self
            case True:
                return self.wait()
            case WaitParams():
                return self.wait(params)

    def poll(self) -> PollProgress:
        """Check the status of this task.

        :return: One of three things:

            * ``True`` : The task has completed
            * ``False``: The task has not completed, and no estimated
              completion percentage is available.
            * a float value: The task has not completed, and this is the
              estimated completion percentage.
        """
        if self._finished:
            return True

        progress = self._poll()
        if progress >= 100:
            progress = True

        # This function is also responsible for calling _on_success() exactly once if
        # the task succeeds.
        if progress is True:
            self._finished = True
            self._on_success(self._get_result())

        return progress

    def done(self) -> bool:
        """Return whether this task is done.

        This is the same as calling poll(), except that it will always return a boolean
        instead of a float progress.
        """
        match self.poll():
            case bool(done):
                return done
            case progress:
                return progress >= 100

    def progress(self) -> float:
        """Return the progress of this task.

        This is the same as calling poll(), except that it will always return a float
        value: A value of ``False`` from poll() will map to 0 and ``True`` will map to
        100.
        """
        progress = self.poll()
        if isinstance(progress, bool):
            return 100 if progress else 0
        else:
            return progress

    def get_result(self) -> ResultType:
        """Get the result of this task.

        If this is called before the task finished, an exception will be raised. If you
        are not manually tracking the progress of the task, :py:meth:`wait` is
        recommended instead.
        """
        if not self._finished:
            msg = "Called get_result before the task was finished."
            raise RuntimeError(msg)
        return self._get_result()

    @abc.abstractmethod
    def _poll(self) -> PollProgress:
        raise NotImplementedError

    @abc.abstractmethod
    def _get_result(self) -> ResultType:
        raise NotImplementedError

    def _on_success(self, result: ResultType) -> None:
        pass
