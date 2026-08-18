from __future__ import annotations

from enum import Enum
import logging
from functools import cached_property
from pathlib import PurePosixPath
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    TypeAlias,
    TypeVar,
    Union,
    overload,
)

import base91
from pydantic_core import CoreSchema, core_schema


if TYPE_CHECKING:
    import requests
    from pydantic import GetCoreSchemaHandler
    from typing_extensions import Self


log: logging.Logger = logging.getLogger(__name__)

Json: TypeAlias = Dict[str, Any]
DevicePath: TypeAlias = Union[str, PurePosixPath]


class Base91Data(str):
    """A string representing base91 encoded data.

    The bytes representation can be accessed through :py:attr:`bytes`
    """

    _bytes: Optional[bytes]

    def __new__(cls, value: str) -> Self:
        s = super().__new__(cls, value)
        s._bytes = None
        return s

    def __repr__(self) -> str:
        return f"Base91Data({super().__repr__()})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(cls._validate, handler(str))

    @classmethod
    def _validate(cls, v: Any) -> Self:
        if not isinstance(v, str):
            msg = "string required"
            raise TypeError(msg)
        else:
            return cls(v)

    def hex(self, sep: str = "", bytes_per_sep: int =1) -> str:
        return self.bytes.hex(sep, bytes_per_sep=bytes_per_sep)

    @cached_property
    def bytes(self) -> bytes:
        """Return the decoded binary value of this data.

        This is a cached property, so it will only be calculated the first time it is
        accessed.
        """
        return base91.decode(self)


# Deprecated: use the method on ApiResponse instead
def validate_response(
    resp: requests.Response,
    permission: Optional[str] = None,
    success_code: Union[int, List[int]] = 200,
) -> None:
    from serialtek.session import ApiResponse

    ApiResponse.validate(
        resp, permission=permission, success_code=success_code  # type: ignore
    )


T = TypeVar("T")


@overload
def human_size(size: int, fmt: str = ...) -> str:
    ...


@overload
def human_size(size: int, fmt: Literal[None]) -> Tuple[float, str]:
    ...


def human_size(
    size: int, fmt: Optional[str] = "{v:.02f} {p}B"
) -> Union[str, Tuple[float, str]]:
    """Format a size in bytes as a human-readable value.

    :param fmt: Format for the output. This string will be formatted as with
        :py:meth:`str.format`, with two variables availabe: ``v`` as the value, and
        ``p`` as the prefix for the unit. If ``None`` is given for the format value, a
        tuple of the value and the prefix will be returned instead.
    """
    div = 1024
    prefixes = iter(["", "k", "M", "G", "T", "P", "E"])
    p = next(prefixes)
    value: float = size
    while value > div:
        value /= div
        p = next(prefixes)
    if fmt is None:
        return (value, p)
    else:
        return fmt.format(v=value, p=p)


def exclude_none(dict: dict[str, Any]) -> dict[str, Any]:
    """Exclude items whose value is None from a dictionary"""
    return {k: v for k, v in dict.items() if v is not None}


E = TypeVar("E", bound=Enum)


def try_enum(enum: type[E], v: T) -> E | T:
    try:
        return enum(v)
    except Exception:

        class UnrecognizedEnumValue(v.__class__):
            @property
            def name(self):
                return f"Unknown({v!r})"

            def value(self):
                return v

            def __str__(self):
                return self.name

        return UnrecognizedEnumValue(v)  # type: ignore
