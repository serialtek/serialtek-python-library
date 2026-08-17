from datetime import datetime
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from typing_extensions import Self

from serialtek.session import ApiSession
from serialtek.util.json import JsonBacked

from .errors import LockError
from .util import Json, validate_response

log: logging.Logger = logging.getLogger(__name__)


class LockStatus(JsonBacked, init=False):
    """
    Status information about the lock on the system
    """

    accessed: datetime | None
    acquired: datetime | None
    key: str | None
    lock_name: str
    owner: str
    id: str


@dataclass
class Lock:
    """A representation of a held lock.

    This is generally created with :py:meth:`.Kodiak.lock`, see the documentation of
    that function for typical usage.
    """

    #: The URI that to access this lock, without the host component (eg. ``/kodiak/v1/device``)
    uri: str

    #: The key associated with this lock. This key needs to be included in requests that
    #: require the lock. If this lock was created with :py:meth:`.Kodiak.lock`, this
    #: will be done automatically in most cases, but if you are accessing the API
    #: directly this value may be necessary for some operations::
    #:
    #:      with kodiak.lock() as lock:
    #:          kodiak.session.post("/kodiak/v1/...", json={"lock_key": lock.key})
    key: str
    #: The id of this lock.
    id: str

    #: A reference to API session with this trace's Kodiak
    session: ApiSession

    #: Whether to raise an error if this lock is no longer held when it is unlocked
    strict_unlock: bool = False
    _locked: bool = True
    _unlock_cb: Optional[Callable[[], None]] = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, type: object, value: object, traceback: object) -> None:
        self.unlock()

    @classmethod
    def lock(
        cls,
        uri: str,
        session: ApiSession,
        *,
        key: Optional[str] = None,
        name: Optional[str] = None,
        force: bool = False,
        strict_unlock: bool = False,
        _unlock_cb: Optional[Callable[[], None]] = None,
    ) -> Self:
        """Take a lock.

        :meta private:
        """
        request: Json = {"force": force}
        if name is not None:
            request["lock_name"] = name
        if key is not None:
            request["key"] = key

        resp = session.post(f"{uri}/lock", json=request).validate().json()
        resp = LockStatus(resp)
        assert resp.key is not None
        log.info(
            "Kodiak has been locked by %r. Lock name: %r key: %r id: %r",
            resp.owner,
            resp.lock_name,
            resp.key,
            resp.id,
        )

        return cls(
            session=session,
            uri=uri,
            key=resp.key,
            id=resp.id,
            strict_unlock=strict_unlock,
            _unlock_cb=_unlock_cb,
        )

    def held(self) -> bool:
        """Check whether this lock is held or not."""
        resp = self.session.get(f"{self.uri}/lock").validate().json()
        resp = LockStatus(resp)
        return resp.id == self.id

    def unlock(self, strict: Optional[bool] = None) -> None:
        """Unlock this lock."""
        try:
            resp = self.session.post(
                f"{self.uri}/unlock",
                json={"key": self.key},
            )
            validate_response(resp)
            log.info("Successfully unlocked Kodiak")

        except LockError as err:
            if strict is None:
                strict = self.strict_unlock

            owner = err.data.get("lock_owner")
            if owner:
                log.info(
                    (
                        "Attempted to unlock Kodiak, but the lock is not held."
                        " Current owner: %s"
                    ),
                    owner,
                )
                if strict:
                    raise
            elif owner == "":
                log.info("Attempted to unlock Kodiak, but it was already unlocked.")
            else:
                log.exception("Received a Lock error without any lock owner data.")
                raise
        finally:
            self._locked = False
            if self._unlock_cb:
                self._unlock_cb()
