from __future__ import annotations

from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypeAlias, Union

from .channel import Channel, ChannelLike, CHANNEL_IDS

if TYPE_CHECKING:
    from typing_extensions import Self

    from . import trace
    from .util import Json


FilterChannel: TypeAlias = Union[List[ChannelLike], bool]

@dataclass(frozen=True)
class Filter:
    """Construct a filter to apply to a cursor.

    :param basic: A description of the basic filter. This should be a dictionary where
        the keys are filter terms and the values are either:

          * ``True``: To apply this filter to all applicable channels.
          * A list of :py:class:`~serialtek.channel.ChannelLike` indicating the channels on which this term
            should be active.

    :param advanced: An advanced filter to apply. An advanced filter can be created and
        downloaded from the SerialTek GUI application.

    :param filter_in: If ``True``, only elements matching the filter will be shown. If
        ``False``, only elements that do not match the filter will be shown.
        :py:meth:`.Filter.In` and :py:meth:`.Filter.Out` are also available to create
        these two types of filters.


    Filters can be used with :py:meth:`.CursorBase.set_filter`::

        # Filter in only TLP memory reads on channel
        cursor.set_filter(Filter.In({"data.tlp.mrd": True}))

        # Filter out all ordered sets on channel dn.data.0
        cursor.set_filter(Filter.Out({"data.os.all": ["dn.data.0"]}))

        # Show only data matching an advanced filter with
        open("my_advanced_filter.json") as f:
            advanced_filter = json.load(f)
        cursor.set_filter(Filter.In(advanced=advanced_filter))

        # Clear the filter on a cursor
        cursor.set_filter(Filter.Clear())

    """

    basic: Optional[Dict[str, FilterChannel]] = None
    _: KW_ONLY
    advanced: Optional[Json] = None
    filter_in: bool

    @classmethod
    def In(
        cls,
        basic: Optional[Dict[str, FilterChannel]] = None,
        *,
        advanced: Optional[Json] = None,
    ) -> Self:
        """Create a filter that will filter in events."""
        return cls(basic=basic, advanced=advanced, filter_in=True)

    @classmethod
    def Out(
        cls,
        basic: Optional[Dict[str, FilterChannel]] = None,
        *,
        advanced: Optional[Json] = None,
    ) -> Self:
        """Create a filter that will filter out events."""
        return cls(basic=basic, advanced=advanced, filter_in=False)

    @classmethod
    def Clear(cls) -> Self:
        """Create an empty filter that won't filter any events."""
        return cls(filter_in=False)

    def to_json(self, trace: trace.Trace) -> Dict[str, Any]:
        """Convert this filter to its json representation for use with the API.

        :param trace: The trace this filter will be used on.
        """
        entries: List[Dict[str, Any]] = []

        def get_entry(channel_group: str, channel_id: int, subid: int) -> Dict[str, Any]:
            try:
                return next(
                    e
                    for e in entries
                    if e["type"] == channel_group and e["subid"] == subid
                )
            except StopIteration:
                entry: Dict[str, Any] = {
                    "type": channel_group,
                    "id": channel_id,
                    "subid": subid,
                    "terms": [],
                }
                entries.append(entry)
                return entry

        structure = trace.session.get("/kodiak/v1/traces/filter_structure").json()

        channels = trace.info().channels

        # Workaround KODSW-524 - filter in needs empty groups
        if self.filter_in:
            for main_group in structure:
                for channel_name in main_group["channels"]:
                    channel_id = CHANNEL_IDS.inverse[channel_name]
                    for channel in channels:
                        if channel.id == channel_id:
                            get_entry(channel_name, channel_id, channel.subid)

        if self.basic:
            for term, target in self.basic.items():
                if target is False:
                    continue

                groups = term.split(".")

                if target is True:
                    # The filter structure will tell us which channels in the filter this term
                    # should go in.
                    try:
                        group_structure = next(
                            sg for sg in structure if sg["name"] == groups[0]
                        )
                    except StopIteration:
                        msg = (
                            f"{groups[0]} is not a valid top-level filter group (valid"
                            f" values are {[sg['name'] for sg in structure]})"
                        )
                        raise ValueError(msg) from None
                    if group_structure["channels"]:
                        for main_group in group_structure["channels"]:
                            channel_id = CHANNEL_IDS.inverse[main_group]
                            for channel in channels:
                                if channel.id == channel_id:
                                    entry = get_entry(
                                        main_group, channel_id, channel.subid
                                    )
                                    entry["terms"].append(term)
                    else:
                        channel_id = CHANNEL_IDS.inverse[groups[0]]
                        entry = get_entry(groups[0], channel_id, 0)
                        entry["terms"].append(term)
                else:
                    for ch in target:
                        channel = Channel(ch)
                        main_group = channel.id_name
                        entry = get_entry(main_group, channel.id, channel.subid)
                        entry["terms"].append(term)

        data: Dict[str, Any] = {
            "basic": entries,
            "filter_in": self.filter_in,
            "devices": [],
        }
        if self.advanced:
            data["advanced"] = self.advanced
        return data
