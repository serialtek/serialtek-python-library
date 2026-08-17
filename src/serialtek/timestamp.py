from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Iterable, Literal, Optional, Union, overload

from pydantic_core import CoreSchema, core_schema

from ._model import model_context

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler
    from typing_extensions import Self

__all__ = (
    "TimestampLike",
    "TicksLike",
    "TimestampBase",
    "Timestamp",
    "Ticks",
    "HALF_NANOSECOND",
)

HALF_NANOSECOND = 2_000_000_000
PICOSECOND = 1_000_000_000_000


class TimestampBase(ABC):
    """Representation of a duration of time, usually a timestamp in a trace.

    This class can also be used to represent the difference between two timestamps.
    """

    @property
    @abstractmethod
    def seconds(self) -> int:
        """The seconds portion of this timestamp."""
        ...

    @property
    @abstractmethod
    def milliseconds(self) -> int:
        """The milliseconds portion of this timestamp."""
        ...

    @property
    @abstractmethod
    def microseconds(self) -> int:
        """The microseconds portion of this timestamp."""
        ...

    @property
    @abstractmethod
    def nanoseconds(self) -> int:
        """The nanoseconds portion of this timestamp."""
        ...

    @property
    @abstractmethod
    def picoseconds(self) -> int:
        """The picoseconds portion of this timestamp."""
        ...

    def in_seconds(self) -> float:
        """The full duration of this timestamp, represented in seconds as a floating-point number."""
        result = 0.0
        for magnitude in (
            "picoseconds",
            "nanoseconds",
            "microseconds",
            "milliseconds",
            "seconds",
        ):
            result /= 1000
            result += getattr(self, magnitude)
        return result

    @property
    def ticks_per_second(self) -> Optional[int]:
        """The resolution of this timestamp, represented as ticks per second, if known."""
        return None

    def dotted_str(self, digits: int) -> str:
        """Format this timestamp as a dotted string with the given number of digits."""
        output = ""
        for magnitude in (
            "seconds",
            "milliseconds",
            "microseconds",
            "nanoseconds",
            "picoseconds",
        ):
            if digits >= 3:
                output += format(getattr(self, magnitude), "03d") + "."
            else:
                value = getattr(self, magnitude) // (10 ** (3 - digits))
                output += format(value, f"0{digits}d")
            digits -= 3
            if digits <= 0:
                break
        return output.rstrip(".")

    @staticmethod
    def parse_dotted_str(value: str) -> Iterable[int]:
        """Parse a timestamp formatted as a dotted string.

        A dotted string takes the form of ``AAA.BBB.CCC.XYZ``, where ``AAA``, ```BBB``,
        ``CCC``, etc. are any number of three-digit values, starting with seconds and
        each representing 1/1000th of the previous (seconds, milliseconds, microseconds,
        etc.). The last set (``XYZ``), may be fewer than 3 digits. If it is, it behaves
        like the value after a normal decimal point, eg ``000.000.000.000.5`` represents
        500 picoseconds, ``000.000.000.32`` represents 320 picoseconds, and
        ``000.000.000.000.123`` represents 123 picoseconds.

        :meta private:
        """
        groups = value.split(".")
        for i, group in enumerate(groups):
            if i != len(groups) - 1 and len(group) != 3:
                msg = (
                    "All groups in a dotted timestamp except for the last must be 3"
                    f" digits ({group!r} is {len(group)})"
                )
                raise ValueError(msg)
            if len(group) not in range(1, 4):
                msg = f"{group!r} has an invalid number of digits (1-3 are allowed)"
                raise ValueError(msg)
            yield int(group) * (10 ** (3 - len(group)))


class Timestamp(TimestampBase):
    """A simple representation of a timestamp."""

    @property
    def seconds(self) -> int:
        """The seconds portion of this timestamp."""
        return self._seconds

    @seconds.setter
    def seconds(self, value: int) -> None:
        self._seconds = value

    @property
    def milliseconds(self) -> int:
        """The milliseconds portion of this timestamp."""
        return self._milliseconds

    @milliseconds.setter
    def milliseconds(self, value: int) -> None:
        self._milliseconds = value

    @property
    def microseconds(self) -> int:
        """The microseconds portion of this timestamp."""
        return self._microseconds

    @microseconds.setter
    def microseconds(self, value: int) -> None:
        self._microseconds = value

    @property
    def nanoseconds(self) -> int:
        """The nanoseconds portion of this timestamp."""
        return self._nanoseconds

    @nanoseconds.setter
    def nanoseconds(self, value: int) -> None:
        self._nanoseconds = value

    @property
    def picoseconds(self) -> int:
        """The picoseconds portion of this timestamp."""
        return self._picoseconds

    @picoseconds.setter
    def picoseconds(self, value: int) -> None:
        self._picoseconds = value

    @overload
    def __init__(self, value: TimestampLike) -> None:
        ...

    @overload
    def __init__(
        self,
        *,
        seconds: int = 0,
        milliseconds: int = 0,
        microseconds: int = 0,
        nanoseconds: int = 0,
        picoseconds: int = 0,
    ) -> None:
        ...

    def __init__(self, value: Optional[TimestampLike] = None, **kwargs: int) -> None:
        if isinstance(value, TimestampBase):
            self.seconds = value.seconds
            self.milliseconds = value.milliseconds
            self.microseconds = value.microseconds
            self.nanoseconds = value.nanoseconds
            self.picoseconds = value.picoseconds
        elif isinstance(value, str):
            groups = list(self.parse_dotted_str(value))
            l = len(groups)
            self.seconds = groups[0]
            self.milliseconds = groups[1] if l >= 2 else 0
            self.microseconds = groups[2] if l >= 3 else 0
            self.nanoseconds = groups[3] if l >= 4 else 0
            self.picoseconds = groups[4] if l >= 5 else 0
        elif isinstance(value, int):
            if value == 0:
                self.seconds = 0
                self.milliseconds = 0
                self.microseconds = 0
                self.nanoseconds = 0
                self.picoseconds = 0
            else:
                msg = (
                    "Cannot create a `Timestamp` from any integer value other than `0`."
                    " Use `Ticks` and specify a base."
                )
                raise ValueError(msg)
        else:
            assert value is None
            self.seconds = kwargs.get("seconds", 0)
            self.milliseconds = kwargs.get("milliseconds", 0)
            self.microseconds = kwargs.get("microseconds", 0)
            self.nanoseconds = kwargs.get("nanoseconds", 0)
            self.picoseconds = kwargs.get("picoseconds", 0)

    def __str__(self) -> str:
        return f"{self.seconds:03d}.{self.milliseconds:03d}.{self.microseconds:03d}.{self.nanoseconds:03d}.{self.picoseconds//500}"


class Ticks(int, TimestampBase):
    """Integer representing a number of Kodiak ticks.

    :param value: The ticks value to use. If `value` is a string, it must be in the
        format SSS.MMM.UUU.NNN or SSS.MMM.UUU.NNN.P where S is the number of
        seconds, M is milliseconds, U is microseconds, N is nanoseconds, and P is 0
        or 5 for the remaining 1/2 nanosecond.
    :param base: The base value for the ticks. This value is the number of ticks in
        one second. For example, for 1/2 nanosecond ticks, use a base of
        ``2_000_000_000``.
    """

    _base: int

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls._validate, handler(int))

    @classmethod
    def _validate(cls, v: TicksLike) -> Self | TicksUnknownBase:
        # When parsing Ticks as part of a pydantic model, we should be able to know the
        # context of what trace we're in, which will tell us what the base for the ticks
        # value is. That information should be stored in `model_context` by whatever
        # code started the parsing.
        ctx = model_context.get()
        base = None
        if ctx is not None:
            base = ctx.ticks_base

        if base is None and type(v) is int:  # noqa: E721
            # If we don't have the context, create ticks with an unknown base.
            return TicksUnknownBase(v)
        else:
            return cls(v, base)

    def __new__(cls, value: TicksLike, base: Optional[int] = None) -> Self:
        """Create a new ticks value.

        :param value: The ticks value to use. If `value` is a string, it must be in the
            format SSS.MMM.UUU.NNN or SSS.MMM.UUU.NNN.P where S is the number of
            seconds, M is milliseconds, U is microseconds, N is nanoseconds, and P is 0
            or 5 for the remaining 1/2 nanosecond.
        :param base: The base value for the ticks. This value is the number of ticks in
            one second. For example, for 1/2 nanosecond ticks, use a base of
            ``2_000_000_000``.
        """
        ticks_int: int

        # If it's a dotted string, parse it.
        if isinstance(value, str):
            if base is None:
                msg = "Can't convert a dotted string timestamp to Ticks without a base."
                raise ValueError(msg)
            try:
                calc_base = base
                ticks_int = 0
                for group in cls.parse_dotted_str(value):
                    ticks_int += int(group * calc_base)
                    calc_base /= 1000
            except (AssertionError, ValueError, IndexError) as err:
                msg = f"{value!r} isn't a valid timestamp"
                raise ValueError(msg) from err

        elif isinstance(value, Ticks):
            if not hasattr(value, "_base") or value._base == base or base is None:
                if base is None:
                    base = value._base
                ticks_int = int(value)
            else:
                # In theory we *could* do a conversion here, but it's not likely that
                # anyone will need to.
                msg = (
                    f"Cannot create ticks with base {base} from ticks with base"
                    f" {value._base}"
                )
                raise ValueError(msg)

        elif isinstance(value, TimestampBase):
            if base is None:
                msg = (
                    f"Can't convert {value.__class__.__name__} to ticks without a base."
                )
                raise ValueError(msg)
            return cls(value.dotted_str(cls._dotted_str_digits(base)), base)

        elif isinstance(value, int):  # pyright: ignore[reportUnnecessaryIsInstance]
            ticks_int = value

        else:
            msg = f"Can't convert `{value!r}` of type {type(value)} to Ticks"
            raise TypeError(msg)

        if base is None:
            msg = f"Can't convert `{value!r}` int to Ticks without a base."
            raise ValueError(msg)

        ret = int.__new__(cls, ticks_int)
        ret._base = base
        return ret

    def __repr__(self) -> str:
        return f"Ticks({super().__repr__()}, {self._base})"

    def __str__(self) -> str:
        try:
            return self.dotted_str(self._dotted_str_digits(self._base))
        except AttributeError:
            # If we got this ticks from an integer with an unknown base, just print the
            # integer
            return str(int(self))

    @classmethod
    def with_base(cls, base: int) -> TicksBaseFactory:
        """Create a :py:class:`.TicksBaseFactory` using the given base."""
        return TicksBaseFactory(base)

    @property
    def seconds(self) -> int:
        """The seconds portion of this timestamp."""
        return self // self._base

    @property
    def milliseconds(self) -> int:
        """The milliseconds portion of this timestamp."""
        return int(self / (self._base / 1000)) % 1000

    @property
    def microseconds(self) -> int:
        """The microseconds portion of this timestamp."""
        return int(self / (self._base / 1_000_000)) % 1000

    @property
    def nanoseconds(self) -> int:
        """The nanoseconds portion of this timestamp."""
        return int(self / (self._base / 1_000_000_000)) % 1000

    @property
    def picoseconds(self) -> int:
        """The picoseconds portion of this timestamp."""
        return int(self / (self._base / 1_000_000_000_000)) % 1000

    def in_seconds(self) -> float:
        """The full duration of this timestamp, represented in seconds as a floating-point number."""
        return self / self._base

    @property
    def ticks_per_second(self) -> Optional[int]:
        """The resolution of this timestamp, represented as ticks per second, if known."""
        return self._base

    @staticmethod
    def _dotted_str_digits(base: int):
        return 3 + len(str(base))


class TicksBaseFactory:
    """Factory object for creating ticks with a known base.

    :param base: The base to use when creating ticks.
    """

    def __init__(self, base: Optional[int]):
        self.base = base

    def __call__(self, value: TicksLike) -> Ticks:
        return Ticks(value, base=self.base)

    def ticks_int(self, value: TicksLike) -> int:
        """Create an in value from a TicksLike.

        The only differences between this and just using ``TicksBaseFactory(x)`` are:

        * This returns an ``int``, not ``Ticks`` (meaning, the value has no base
          attached.)
        * This method will accept an ``int`` even if no base is specified, and will just
          pass the value through (the assumption being that that ``int`` came from
          somewhere that knew the ticks base).
        """
        if type(value) is int:  # noqa: E721
            return value
        else:
            return int(Ticks(value, self.base))

    def max(self) -> Ticks:
        """The maximum possible ticks value."""
        return self(0xFFFFFFFFFFFFFFFF)


class TicksUnknownBase(Ticks):
    """Representation of a number of ticks with an unknown base.

    This is returned when parsing :py:class:`~serialtek.timestamp.Ticks` members of API
    models if no trace context is given.
    """

    def __new__(cls, value: int) -> Self:
        return int.__new__(cls, value)


#: Type alias representing an object that can be converted into a timestamp. This
#: includes anything that is already a timestamp such as
#: :py:class:`~serialtek.timestamp.Ticks`, a string formatted like a timestamp (e.g.
#: ``"000.000.123.456.5"``), or 0 (which indicates the start of a trace).
TimestampLike = Union[TimestampBase, str, Literal[0]]

#: Type alias representing an object that could represent a number of ticks (given a tick
#: base).
TicksLike = Union[TimestampLike, int]
