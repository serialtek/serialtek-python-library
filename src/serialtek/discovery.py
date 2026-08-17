from __future__ import annotations
from dataclasses import dataclass
from functools import cached_property
from ipaddress import IPv4Address, IPv6Address, ip_address
import logging
import re
import threading
import time
from typing import Any, Callable, Iterator, List, Optional, Union, TYPE_CHECKING

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

from serialtek.kodiak import Kodiak
from serialtek.session import ApiSession
from serialtek.types import undocumented_constructor

if TYPE_CHECKING:
    from typing_extensions import Self

log: logging.Logger = logging.getLogger(__name__)


DISCOVERY_TIMEOUT_DEFAULT = 4


def find_kodiak(
    timeout: Optional[float] = 60,
    serial: Optional[str] = None,
    alias: Optional[str] = None,
    match: Optional[Callable[[DiscoveredKodiak], bool]] = None,
) -> DiscoveredKodiak:
    """Perform a discovery and return the Kodiak matching the given criterea.

    :param timeout: How long to search for.

    Only one of the following parameters can be specified:

    :param serial: Look for the Kodiak with this serial number.
    :param alias: Look for a Kodiak with this alias.
    :param match: The provided function will be called on each
        :py:class:`.DiscoveredKodiak`, and if the function returns ``True``, the
        Kodiak will be returned.

    :returns: A :py:class:`.DiscoveredKodiak`, which can be opened with
        :py:meth:`.DiscoveredKodiak.open`.

    ::

        kodiak = find_kodiak(alias="My Kodiak").open()
        kodiak.login(username="user", password="1234")
    """
    with KodiakFind(serial=serial, alias=alias, match=match) as find:
        return find.wait(timeout=timeout)

@undocumented_constructor
class KodiakDiscovery:
    """Start a discovery of Kodiaks on the local network.

    :param timeout: How long to spend looking for Kodiaks.

    You can iterate over the found Kodiaks, with
    :py:meth:`~.KodiakDiscovery.iter`, and create a :py:class:`.Kodiak` with
    :py:meth:`~.DiscoveredKodiak.open`.

    You must call :py:meth:`~.KodiakDiscovery.close` on this discovery when done.
    To do so automatically, use ``with``::

        from serialtek import Kodiak

        kodiak = None
        with KodiakDiscovery() as discovery:
            for found in discovery.iter(timeout=5):
                print(found.serial)
                if ...: # Logic to choose which Kodiak to open
                    kodiak = found.open()

        if kodiak is not None:
            kodiak.login(username="user", password="1234")
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._available: List[DiscoveredKodiak] = []

        self._zc = Zeroconf()
        self._listener = _KodiakDiscoveryListener()
        self._browser = ServiceBrowser(
            self._zc, "_g5_serialtek._tcp.local.", self._listener
        )
        log.debug("Starting discovery")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, type: object, value: object, traceback: object) -> None:
        self.close()

    def pop(self) -> Optional[DiscoveredKodiak]:
        """Return the next discovered Kodiak, if there is one.

        If there isn't, returns ``None`` immediately.
        """
        return self._listener.pop()

    def pop_wait(self, timeout: Optional[float] = None) -> DiscoveredKodiak:
        """Return the next discovered Kodiak.

        :param timeout: How long to wait for a Kodiak to be discovered, or ``0`` to
            wait indefinitely.

        :raises: :py:exc:`TimeoutError` if the timeout expires without finding an
            Kodiak.
        """
        return self._listener.pop_wait(timeout)

    def pop_wait_maybe(
        self, timeout: Optional[float] = None
    ) -> Optional[DiscoveredKodiak]:
        """Return the next discovered Kodiak, potentially waiting, if there is one.

        :param timeout: How long to wait for a Kodiak to be discovered, or ``0`` to
            wait indefinitely.

        If no Kodiak is found and the timeout expires, returns ``None``.
        """
        return self._listener.pop_wait_maybe(timeout)

    def iter(
        self,
        timeout: Optional[float] = DISCOVERY_TIMEOUT_DEFAULT,
    ) -> Iterator[DiscoveredKodiak]:
        """Create an iterator that will yield discovered Kodiaks.

        :param timeout: How long after the iterator is created to time out and stop
            waiting for Kodiaks.

        Kodiaks will be yielded as they are discovered, and when the timeout is
        reached the iterator will finish.
        """
        return _KodiakDiscoveryIterator(self, timeout)

    def available_iter(self) -> Iterator[DiscoveredKodiak]:
        """Create an iterator that will yield currently available discovered Kodiaks.

        This will yield as many Kodiaks as possible without waiting, then finish.
        """
        while found := self.pop():
            yield found

    def close(self):
        """Stop the discovery thread."""
        log.debug("Stopping discovery")
        self._zc.close()


class _KodiakDiscoveryIterator:
    def __init__(
        self,
        discovery: KodiakDiscovery,
        timeout: Optional[float],
    ):
        if timeout is not None:
            self.end = time.monotonic() + timeout
        else:
            self.end = None
        self.discovery = discovery
        self.found_first = False

    def __iter__(self):
        return self

    def __next__(self) -> DiscoveredKodiak:
        wait_time = None
        if self.end is not None:
            wait_time = self.end - time.monotonic()

        if wait_time is not None and wait_time < 0:
            found = self.discovery.pop()
        else:
            found = self.discovery.pop_wait_maybe(wait_time)

        if found is None:
            raise StopIteration
        self.found_first = True

        return found


@dataclass
class _KodiakDiscoveryListener(ServiceListener):
    _condition: threading.Condition
    _available: List[DiscoveredKodiak]

    def __init__(self):
        self._condition = threading.Condition()
        self._available = []

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info is None:
            return

        if len(info.addresses) > 0:
            ip = ".".join(str(b) for b in info.addresses[0])
        else:
            return

        if info.server is not None and (
            host_match := re.match(r"^kodiak-(?P<sn>[^-]+)\.local\.$", info.server)
        ):
            serial = host_match.group("sn")
            url = "https://" + info.server.removesuffix(".")
        else:
            return

        found = DiscoveredKodiak(url=url, ip=ip_address(ip), serial=serial)
        log.debug("Discovered %s", found)

        with self._condition:
            self._available.append(found)
            self._condition.notify()

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        return

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        return

    def pop(self) -> Optional[DiscoveredKodiak]:
        with self._condition:
            if len(self._available):
                return self._available.pop()
            else:
                return None

    def pop_wait(self, timeout: Optional[float] = None) -> DiscoveredKodiak:
        found = self.pop_wait_maybe(timeout)
        if found is None:
            raise TimeoutError
        return found

    def pop_wait_maybe(
        self, timeout: Optional[float] = None
    ) -> Optional[DiscoveredKodiak]:
        with self._condition:
            if not len(self._available) > 0:
                cv = self._condition.wait_for(lambda: len(self._available) > 0, timeout)
                if cv is False:
                    return None
            return self._available.pop()


@dataclass
class DiscoveredKodiak:
    """Information on a discovered Kodiak.

    The Kodiak can be opened (creating an :py:class:`.Kodiak` object) with
    :py:meth:`.open`.
    """

    #: The url to use to access this Kodiak.
    url: str
    #: This Kodiak's serial number.
    serial: str
    #: This Kodiak's ip address.
    ip: Union[IPv4Address, IPv6Address]

    @cached_property
    def alias(self) -> str:
        """This Kodiak's configured alias."""
        return ApiSession.host_info(f"http://{self.ip}").alias

    def open(self, **kwargs: Any) -> Kodiak:
        """Open the Kodiak at this address.

        This function takes the same arguments as the :py:meth:`.Kodiak` class (except
        for the ``host`` argument), see that class for all available arguments.
        """
        return Kodiak(**kwargs)


@undocumented_constructor
class KodiakFind:
    """A handle representing a search started by :py:meth:`.find_kodiak`"""

    _match: Callable[[DiscoveredKodiak], bool]
    _found: Optional[DiscoveredKodiak]

    def __init__(
        self,
        *,
        serial: Optional[str] = None,
        alias: Optional[str] = None,
        match: Optional[Callable[[DiscoveredKodiak], bool]] = None,
    ):
        self._discovery = KodiakDiscovery()

        if sum(1 if x is not None else 0 for x in (serial, alias, match)) != 1:
            msg = "Specify only one of: serial, alias, or match"
            raise ValueError(msg)

        if serial is not None:
            self._match = lambda f: f.serial == serial
        elif alias is not None:
            self._match = lambda f: f.alias == alias
        elif match is not None:
            self._match = match
        self._found = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, type: object, value: object, traceback: object) -> None:
        self.close()

    def poll(self) -> Optional[DiscoveredKodiak]:
        """Return the result of the search so far.

        If a Kodiak has been found, that Kodiak will be returned. Otherwise,
        ``None`` will be returned.
        """
        if self._found is None:
            for found in self._discovery.available_iter():
                if self._match(found):
                    self._found = found
        return self._found

    def wait(
        self,
        timeout: Optional[float] = 60,
    ) -> DiscoveredKodiak:
        """Wait for the search to finish and return the result.

        :param timeout: How long to wait for, or 0 to wait indefinitely.

        :raises: :py:exc:`TimeoutError` if the timeout expires without anything being
            found.
        """
        for found in self._discovery.iter(timeout=timeout):
            if self._match(found):
                return found
        raise TimeoutError

    def close(self):
        """Stop the discovery thread."""
        self._discovery.close()
