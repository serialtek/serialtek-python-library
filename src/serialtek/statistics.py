"""
Statistics can be retrieved from a trace using :py:meth:`.Trace.statistics`::

    >>> stats = trace.statistics()

The trace statistics contain 3 types of information:

* **Basic statistics**: Counts of different types of events in the trace
* **PCIe transaction statistics**: Information on the statuses of PCIe Transactions,
  organized by requester and completer ids.
* **CXL transaction statistics**: Information on the status of the different CXL
  operations in the trace.

Basic Statistics
----------------

Basic statistics can be accessed with
:py:meth:`~serialtek.statistics.TraceStatistics.stat`, for example::

    >>> stats.stat("summary.total_tlps")
    79476

The returned value will be an instance of ``int`` or ``float``, representing the
total of all channels containing that statistic. The ``channels`` member of a
statistic allows accessing individual channels::

    >>> stats.stat("summary.total_tlps").channels
    {Channel('dn.data.0'): 39760, Channel('up.data.0'): 39716}

The ``channels`` member can be indexed with a :py:class:`~serialtek.channel.Channel`,
or any :py:class:`~serialtek.channel.ChannelLike`::

    >>> stats.stat("sumary.total_tlps").channels["dn.data.0"]
    39760
    >>> stats.stat("summary.total_tlps").channels[Channel("dn.data.0")]
    39760

To get the statistics key to use for a statistic from the serialtek web ui, hover over
the statistic name with the mouse. The statistic key will be shown in the tooltip:

.. image:: ../../img/statistic-tooltip.png

PCIe Transaction Statistics
---------------------------

Access PCIe transaction statistics with
:py:attr:`~serialtek.statistics.TraceStatistics.pcie_txn_stats`. Statistics are organized
by link and by the requester/completer ids for transactions.

    >>> stats.pcie_txn_stats.link(0).transactions(0x0000, 0x00a1).total
    1234

See :py:class:`~statistics.PcieTransactionStatistics`
:py:class:`~statistics.PcieLinkStatistics` and
:py:class:`~statistics.PcieTransactionCounts` for more usage info.

CXL Transaction Statistics
--------------------------

Access CXL transaction statistics with :py:attr:`.cxl_txn_stats`. Statistics are
organized by link, command format, and opcode.

    >>> stats.cxl_txn_stats().link(0).cachemem.m2s_req.opcode(0).total
    127
"""

from __future__ import annotations

import itertools
import logging
import warnings
from functools import cached_property
from typing import (
    Any,
    Dict,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)

from pydantic import BaseModel, Field

from serialtek.channel import Channel, ChannelLike
from serialtek.types import undocumented_constructor

log = logging.getLogger(__name__)

MIN_SUPPORTED_VERSION = 9

T = TypeVar("T")
D = TypeVar("D")


@undocumented_constructor
class TraceStatistics:
    """Statistics calculated on a trace.

    These statistics can be retrieved from a trace using :py:meth:`.Trace.statistics`::

        >>> stats = trace.statistics()
    """

    #: The raw stats object as it was returned from the API.
    raw_stats: Any

    def __init__(self, stats: Any):
        self.raw_stats = stats
        self.version = stats["version"]

        if self.version < MIN_SUPPORTED_VERSION:
            warnings.warn(
                (
                    f"Stats are version {self.version}, at least version"
                    f" {MIN_SUPPORTED_VERSION} is recommended for use with this"
                    " library. Consider using `trace.statistics(upgrade=True)` to"
                    " upgrade statistics, or"
                    f" `trace.statistics(upgrade={MIN_SUPPORTED_VERSION})` to only"
                    " upgrade when the current version is less than"
                    f" {MIN_SUPPORTED_VERSION}."
                ),
                stacklevel=1,
            )

    @cached_property
    def all_stats(self) -> Set[str]:
        """List the keys for all basic statistics present in these statistics."""
        return set(
            itertools.chain(*(_riter(s) for s in self.raw_stats["stats"].values()))
        )

    def stat(self, path: str) -> Union[TraceStatisticInt, TraceStatisticFloat]:
        """Get a statistic from the trace."""
        channels: Dict[Channel, Any] = {}
        value = 0

        for ch, ch_stats in self.raw_stats["stats"].items():
            stat = _rget(ch_stats, path)
            if stat is not None:
                channels[Channel(ch)] = stat

        if not channels:
            raise KeyError(path)

        for stat in channels.values():
            if not isinstance(stat, (int, float)):
                try:
                    try_path = next(_riter(stat, tuple(path.split("."))))
                    try_msg = f" Try something like {try_path} instead."
                except StopIteration:
                    try_msg = ""

                msg = (
                    f"{path} is not a stat, it is a category.{try_msg}\n"
                    "The category had these values for different channels:\n"
                    f"{channels!r}"
                )
                raise TypeError(msg)
            value += stat

        match value:
            case int():
                return TraceStatisticInt(value, channels)
            case float():
                return TraceStatisticFloat(value, channels)

    def get_stat(
        self, path: str, default: D = None
    ) -> Union[TraceStatisticInt, TraceStatisticFloat, D]:
        """Get a statistic from the trace, or return a default value.

        :returns: The requested statistic, or the value of ``default`` if the statistic
            isn't present.
        """
        try:
            return self.stat(path)
        except KeyError:
            return default

    @cached_property
    def pcie_txn_stats(self) -> PcieTransactionStatistics:
        """Get the PCIe Transaction Statistics for the trace."""
        return PcieTransactionStatistics(self.raw_stats["transactions"]["links"])

    @cached_property
    def cxl_txn_stats(self) -> CxlTransactionStatistics:
        """Get the CXL Transaction Statistics for the trace."""
        return CxlTransactionStatistics(self.raw_stats["transactions"]["cxl_links"])


@undocumented_constructor
class TraceStatisticFloat(float):
    """A trace statistic represented as a :py:class:`float`.

    This class behaves like a :py:class:`float` in all cases, but also provides
    :py:attr:`channels`, which contains the value for this statistic on each channel.
    """

    #: A mapping containing the value for this statistic on each channel.
    channels: TraceStatisticsChannels[float]

    def __new__(cls, _value: float, _channels: Dict[Channel, float]):
        ret = float.__new__(cls, _value)
        ret.channels = TraceStatisticsChannels(_channels)
        return ret

    @property
    def value(self) -> float:
        """Get this value as a plain :py:class:`float`"""
        return float(self)


@undocumented_constructor
class TraceStatisticInt(int):
    """A trace statistic represented as a :py:class:`int`.

    This class behaves like a :py:class:`int` in all cases, but also provides
    :py:attr:`channels`, which contains the value for this statistic on each channel.
    """

    #: A mapping containing the value for this statistic on each channel.
    channels: TraceStatisticsChannels[int]

    def __new__(cls, _value: int, _channels: Dict[Channel, int]):
        ret = int.__new__(cls, _value)
        ret.channels = TraceStatisticsChannels(_channels)
        return ret

    @property
    def value(self) -> int:
        """Get this value as a plain :py:class:`int`"""
        return int(self)


class TraceStatisticsChannels(Generic[T]):
    """A mapping containing trace statistic values for multiple channels.

    This can be indexed using a :py:class:`~serialtek.channel.Channel`, or with a
    :py:class:`~serialtek.channel.ChannelLike` (eg ``"dn.data.0"`` or ``(0,0)``)
    """

    _dict: Dict[Channel, T]

    def __init__(self, d: Dict[Channel, T]) -> None:
        self._dict = d

    def __getitem__(self, key: ChannelLike) -> T:
        return self._dict[Channel(key)]

    def __len__(self) -> int:
        return len(self._dict)

    def __iter__(self) -> Iterator[Channel]:
        return iter(self._dict)

    def __repr__(self) -> str:
        inner = ", ".join(f"Channel({ch.name!r}): {v}" for ch, v in self._dict.items())
        return f"{{{inner}}}"

    def keys(self) -> Iterable[Channel]:
        return self._dict.keys()

    def values(self) -> Iterable[T]:
        return self._dict.values()

    def items(self) -> Iterable[Tuple[Channel, T]]:
        return self._dict.items()

    def get(self, key: ChannelLike, default: D = None) -> Union[T, D]:
        return self._dict.get(Channel(key), default)


@undocumented_constructor
class PcieTransactionStatistics:
    """Top-level PCIe Transaction statistics for all links.

    To get statistics for a specific link, use :py:meth:`link`
    """

    #: Mapping of all links in this satatistic object, by link id.
    links: Dict[int, PcieLinkStatistics]

    def __init__(self, pcie_links: Any):
        self.links = {}
        for link in pcie_links:
            link_id = link["link"]
            self.links[link_id] = PcieLinkStatistics(link)

    def link(self, link_id: int) -> PcieLinkStatistics:
        """Retrieve transaction statistics for the given link."""
        return self.links[link_id]


@undocumented_constructor
class PcieLinkStatistics:
    """PCIe transaction statistics for a link.

    To see statistics for transactions between a specific requester and completer, use
    :py:meth:`transactions`.
    """

    #: A dictionary mapping (requester_id, completer_id) to transaction counts for all
    #: requester/completer device pairs on this link.
    device_pairs: Dict[Tuple[int, int], PcieTransactionCounts]

    #: Number of incomplete transactions
    incomplete: int
    #: Number of partial transactions
    partial: int
    #: Number of successful transactions
    successful: int
    #: Number of terminated transactions
    terminated: int
    #: Number of timed out transactions
    timed_out: int
    #: Number of unsuccessful transactions
    unsuccessful: int
    #: Number of posted transactions
    posted: int
    #: Number of non-posted transactions
    nonposted: int
    #: Total number of transactions
    total: int

    def __init__(self, link: Any) -> None:
        self.incomplete = link["incomplete"]
        self.partial = link["partial"]
        self.successful = link["successful"]
        self.terminated = link["terminated"]
        self.timed_out = link["timedOut"]
        self.unsuccessful = link["unsuccessful"]
        self.posted = link["posted"]
        self.nonposted = link["nonposted"]
        self.total = link["total"]

        self.device_pairs = {}
        for dev_pair in link["devices"]:
            req = dev_pair["requester"]
            cpl = dev_pair["completer"]
            txns = PcieTransactionCounts.model_validate(dev_pair)
            self.device_pairs[req, cpl] = txns

    def transactions(
        self, requester_id: int, completer_id: int
    ) -> PcieTransactionCounts:
        """Get statistics for transactions between the given requester and completer."""
        return self.device_pairs[requester_id, completer_id]


class PcieTransactionCounts(BaseModel):
    """Statistics for transactions between a requester and completer."""

    incomplete: int = Field(..., description="Number of incomplete transactions")
    partial: int = Field(..., description="Number of partial transactions")
    successful: int = Field(..., description="Number of successful transactions")
    terminated: int = Field(..., description="Number of terminated transactions")
    timed_out: int = Field(
        ..., description="Number of timed out transactions", alias="timedOut"
    )
    unsuccessful: int = Field(..., description="Number of unsuccessful transactions")
    posted: int = Field(..., description="Number of posted transactions")
    nonposted: int = Field(..., description="Number of non-posted transactions")
    total: int = Field(..., description="Total number of transactions")


@undocumented_constructor
class CxlTransactionStatistics:
    """Top-level CXL Transaction statistics for all links.

    To get statistics for a specific link, use :py:meth:`link`
    """

    #: A dictionary of links by link id.
    links: Dict[int, CxlLinkStatistics]

    def __init__(self, links: Any) -> None:
        self.links = {link["link"]: CxlLinkStatistics(link) for link in links}

    def link(self, link: int) -> CxlLinkStatistics:
        """Retrieve transaction statistics for the given link."""
        return self.links[link]


@undocumented_constructor
class CxlLinkStatistics:
    """CXL transaction statistics for a link.

    This contains statistics on cache/mem transactions in :py:attr:`cachemem`.
    """

    cachemem: CxlCacheMemStatistics

    def __init__(self, link: Any):
        self.cachemem = CxlCacheMemStatistics(link["cachemem"])


@undocumented_constructor
class CxlCacheMemStatistics:
    """CXL Cache/Mem transaction statistics.

    To see statistics for a specific command format, use :py:attr:`d2h`, :py:attr:`h2d`,
    :py:attr:`m2s_rwd`, or `m2s_req`.
    """

    #: Number of incomplete transactions
    incomplete: int
    #: Number of partial transactions
    partial: int
    #: Number of successful transactions
    successful: int
    #: Number of terminated transactions
    terminated: int
    #: Number of timed out transactions
    timed_out: int
    #: Number of unsuccessful transactions
    unsuccessful: int
    #: Total number of transactions
    total: int

    #: Stats for d2h transactions
    d2h: CxlCacheMemFormatStatistics
    #: Stats for h2d transactions
    h2d: CxlCacheMemFormatStatistics
    #: Stats for m2s Rwd transactions
    m2s_rwd: CxlCacheMemFormatStatistics
    #: Stats for m2s Req transactions
    m2s_req: CxlCacheMemFormatStatistics

    def __init__(self, cm: Any):
        self.incomplete = cm["incomplete"]
        self.partial = cm["partial"]
        self.successful = cm["successful"]
        self.terminated = cm["terminated"]
        self.timed_out = cm["timedOut"]
        self.unsuccessful = cm["unsuccessful"]
        self.total = cm["total"]

        self.d2h = CxlCacheMemFormatStatistics(cm["d2h"])
        self.h2d = CxlCacheMemFormatStatistics(cm["h2d"])
        self.m2s_rwd = CxlCacheMemFormatStatistics(cm["m2sRwd"])
        self.m2s_req = CxlCacheMemFormatStatistics(cm["m2sReq"])


@undocumented_constructor
class CxlCacheMemFormatStatistics:
    """Statistics for a CXL Cache/Mem format, grouped by opcode."""

    # A dictionary of statistics for each opcode.
    opcodes: Dict[int, CxlCacheMemOpcodeStatistics]

    def __init__(self, fmt: Any):
        self.opcodes = {
            op["opcode"]: CxlCacheMemOpcodeStatistics.model_validate(op) for op in fmt
        }

    def opcode(self, opcode: int) -> CxlCacheMemOpcodeStatistics:
        """Get the statistics for the given opcode."""
        return self.opcodes[opcode]


class CxlCacheMemOpcodeStatistics(BaseModel):
    """Statistics for all transactions for a given opcode."""

    incomplete: int = Field(..., description="Number of incomplete transactions")
    partial: int = Field(..., description="Number of partial transactions")
    successful: int = Field(..., description="Number of successful transactions")
    terminated: int = Field(..., description="Number of terminated transactions")
    timed_out: int = Field(
        ..., description="Number of timed out transactions", alias="timedOut"
    )
    unsuccessful: int = Field(..., description="Number of unsuccessful transactions")
    total: int = Field(..., description="Total number of transactions")


def _rget(d: Any, path: str) -> Optional[Any]:
    """Recursively get a stats path.

    :meta private:
    """
    try:
        split_path = path.split(".")
        for key in split_path:
            match d:
                case dict():
                    d = cast(Any, d[key])
                case list():
                    d = cast(List[Any], d)
                    return d[int(key)]

                case _:
                    return None

    except (KeyError, IndexError):
        return None
    return d


def _riter(o: Any, path: Tuple[str, ...] = ()) -> Iterator[str]:
    """Iterate over all of the leaf-nodes (entries containing a number) in stats.

    :meta private:
    """
    match o:
        case dict():
            o = cast(Any, o)  # type: ignore
            for k, v in o.items():
                yield from _riter(v, (*path, k))
        case list():
            o = cast(Any, o)  # type: ignore
            for i, el in enumerate(o):
                yield from _riter(el, (*path, str(i)))
        case int() | float():
            yield ".".join(path)
        case _:
            pass
