from __future__ import annotations

from typing import Any, Dict, Tuple

from bidict import bidict
from pydantic import GetCoreSchemaHandler, PlainSerializer
from pydantic_core import CoreSchema, core_schema
from typing_extensions import Annotated, Self

#: A reversible mapping of channel id values to string names for those channels.
#:
#: To get the name of a channel given the id, use eg. ``CHANNEL_IDS[0]``. To get the id of
#: a channel given the name, use eg. ``CHANNEL_IDS.inverse["dn.data"]``.
CHANNEL_IDS = bidict(
    {
        0: "dn.data",
        1: "up.data",
        2: "dn.lsm",
        3: "up.lsm",
        4: "sideband",
        5: "smbus",
        6: "itapdata.in",
        7: "itapdata.out",
        8: "dn.g4data",
        9: "up.g4data",
    }
)

# Not all the places in the backend follow the standard naming convention when referring
# to a channel. This dictionary maps nonstandard names where they're used to the proper
# channel id.
_CHANNEL_ALIASES = {
    "downstream": 0,
    "upstream": 1,
    "downstream-ltssm": 2,
    "dn.ltssm": 2,
    "upstream-ltssm": 3,
    "up.ltssm": 3,
    "sidebands": 4,
}


class Channel:
    """Class representing a channel in a trace."""

    #: The channel id, indicating what type of channel this is.
    id: int
    #: The subid of the channel
    subid: int

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls, handler(int | Tuple[int, int] | str)
        )

    def __new__(cls, value: ChannelLike) -> Self:
        new = super().__new__(cls)

        match value:
            case {"id": int(id), "subid": int(subid)}:
                new.id = id
                new.subid = subid
            case dict():
                msg = f"{value!r} does not have id and subid keys"
                raise ValueError
            case Channel():
                new.id = value.id
                new.subid = value.subid
            case str():
                parts = value.split(".")
                chid = ".".join(parts[:-1])
                subid = int(parts[-1])

                if subid > 0xFF or subid < 0:
                    msg = f"{subid} is not a valid subid"
                    raise ValueError(msg)

                try:
                    new.id = CHANNEL_IDS.inverse[chid]
                except KeyError:
                    try:
                        new.id = _CHANNEL_ALIASES[chid]
                    except KeyError:
                        msg = f"{chid} does not represent a valid channel"
                        raise ValueError(msg) from None

                new.subid = int(parts[-1])
            case int(i):
                if i > 0xFFFF or i < 0:
                    msg = "Channel id must be a positive 16-bit value"
                    raise ValueError(msg)
                new.id = i & 0xFF
                new.subid = i >> 8
                if new.id not in CHANNEL_IDS:
                    msg = (
                        f"0x{i:04x} does not represent a valid channel"
                        f" (0x{new.id:02x} is not a supported channel id)"
                    )
                    raise ValueError(msg) from None
            case (int(id), int(subid)):
                new.id = id
                new.subid = subid
        return new

    @property
    def id_name(self) -> str:
        """The main id of the channel, as a string"""
        return CHANNEL_IDS[self.id]

    @property
    def name(self) -> str:
        """The string name for this channel"""
        return f"{CHANNEL_IDS[self.id]}.{self.subid}"

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id}, subid={self.subid})"

    def __eq__(self, other: object) -> bool:
        match other:
            case Channel():
                return self.id == other.id and self.subid == other.subid
            case str() | int() | (int(), int()):
                try:
                    otherch = Channel(other)  # type: ignore
                except ValueError:
                    return False
                return self == otherch
            case _:
                return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.__dict__.items())))

    def as_int(self) -> int:
        """Representation of this channel as a single integer.

        The channel id is stored in the lower 4 bits of the value, and the subid is
        stored in the upper 4 bits.
        """
        return (self.id & 0xFF) | (self.subid << 8)

    def as_pair(self) -> Tuple[int, int]:
        """Get an (id, subid) pair representing this channel."""
        return (self.id, self.subid)

    def as_dict(self) -> Dict[str, int]:
        """Return a dictionary representing this channel.

        :return: A dictionary, eg. ``{"id": 0, "subid": 0}``
        """
        return {"id": self.id, "subid": self.subid}


#: All the different ways a channel can be represented, including:
#:
#:   * As a single integer, with the id in the lower 4 bits and the subid in the upper 4
#:   * As an (id, subid) tuple
#:   * As a string (eg. dn.data.0)
ChannelLike = int | Tuple[int, int] | str | Channel | dict[str, Any]


# Aliases for use in API models. These specify how a Channel should be serialized for a
# particular model.
ChannelInt = Annotated[Channel, PlainSerializer(Channel.as_int)]
ChannelPair = Annotated[Channel, PlainSerializer(Channel.as_pair)]
