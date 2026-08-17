from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, TypeVar, Union, cast, overload

from typing_extensions import Self

from serialtek.util import Json
from serialtek.util.json import JsonBacked


class DecodeFieldId(int):
    """A field id to use to identify fields to decode.

    The field id is an integer value determined by taking the first 4 bytes of the md5
    checksum of the field's name and treating them as an unsigned big-endian value. This
    class does the calculation and keeps it paired with the name::

      >>> field_id = DecodeFieldId("Type")
      >>> assert field_id == 2717525879
      >>> int(field_id)
      2717525879
      >>> field_id.name
      'Type'
    """

    name: str | None

    def __new__(cls, id: str | int) -> Self:
        match id:
            case str(name):
                hash = int.from_bytes(
                    hashlib.md5(name.encode("utf-8")).digest()[:4], "big"
                )
            case int(hash):
                name = None

        val = super().__new__(cls, hash)
        val.name = name

        return val

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r}, {int(self)})"


class FieldDecodes:
    """Construct a set of fields for a cursor to decode.

    :param decodes: This should be a mapping of decode categories to decode ids. The
        decode id can be a string, an integer, or a DecodeFieldId, or it can be a list
        consisting of those types.

    FieldDecodes can be used with :py:meth:`.CursorBase.set_decodes`::

        # Decode the Type field for DLLPs and the STP and FCRC field for TLPs
        cursor.set_decodes(FieldDecodes({
            "events.dllp": "Type",
            "events.tlp": ["STP", "FCRC"]
        }))

    You can also use any number of json definitions copied directly from the web ui, so
    this code is equivalent to the above::

        cursor.set_decodes(FieldDecodes(
            {"events": {"dllp": [2717525879]}},
            {"events": {"tlp": [1772807117]}},
            {"events": {"tlp": [3937818435]}},
        ))

    """

    _decodes: Dict[str, Any]

    def __init__(self, *decodes: Dict[str, Any]):
        self._decodes = {}
        for decode in decodes:
            self.update(decode)

    def update(self, decodes: Dict[str, Any]) -> None:
        """Add fields to this set of fields to decode.

        See :py:class:`.FieldDecodes` for how to specify decode fields.
        """
        _decodes_update(decodes, self._decodes)

    def to_json(self) -> Json:
        """Return a json object for use with the kodiak API."""
        return self._decodes


def _decodes_update(
    decodes: Dict[str, Any],
    into: Dict[str, Any],
):
    for key, values in decodes.items():
        if not isinstance(values, list):
            values = [values]

        for value in cast(List[Any], values):
            if isinstance(value, dict):
                field_id = None
            elif isinstance(value, int):
                field_id = value
            elif isinstance(value, str):
                field_id = int(DecodeFieldId(value))
            else:
                raise TypeError(value)

            search: Dict[str, Any] = into
            path = key.split(".")

            for p in path[:-1]:
                if p not in search:
                    search[p] = {}
                search = search[p]

            if field_id is None:
                if path[-1] not in search:
                    search[path[-1]] = {}
                _decodes_update(cast(Dict[str, Any], value), search[path[-1]])
            else:
                if path[-1] not in search:
                    search[path[-1]] = []
                search[path[-1]].append(field_id)


T = TypeVar("T")


class DecodedFields:
    """
    A list of all decoded fields from an event.

    Individual fields can be accessed using :py:meth:`get`, using is either the string
    name, the string's integer id, or a :py:class:`~.DecodeFieldId`. For example, all
    three of these expressions will retrieve the "Type" decode::

        event.fields.get("Type")
        event.fields.get(0xa1fa2777)
        event.fields.get(DecodeFieldId("Type"))

    By default, :py:meth:`get` will raise an exception if more than one decode with the
    given id is present. To handle cases where multiple decodes may be present, either
    use the ``index`` argument to :py:meth:`get` or use :py:meth:`get_all`
    """

    def __init__(self, fields: list[Json]):
        self._fields = fields

    def get_all(self, key: Union[str, int]) -> List[DecodedField]:
        """Get all decodes that have the given id."""
        match key:
            case str():
                id = DecodeFieldId(key)
            case int():
                id = key

        matches = [DecodedField(f) for f in self._fields if f["id"] == id]
        if isinstance(key, str):
            for m in matches:
                m.raw_data["id"] = id
        return matches

    @overload
    def get(
        self, k: Union[str, int], *, default: T, index: Optional[int] = ...
    ) -> Union[DecodedField, T]:
        ...

    @overload
    def get(self, k: Union[str, int], *, index: Optional[int] = ...) -> DecodedField:
        ...

    def get(
        self, k: Union[str, int], *, default: Any = ..., index: Optional[int] = None
    ) -> Any:
        """Get a single decode that has the given id.

        :param index: determines how to handle cases where there are multiple decodes
            present with the given id. If ``None`` (by default), this function will
            raise an exception if there are multiple candidates. If a number, then the
            value at that index will be taken (eg, set to ``0`` to take the first
            value).
        :param default: Specify a value to return if no value is present (or, if
            ``index`` is specified, if there aren't enough elements in the list to get
            to the requested index). If this argument is not given, an exception will be
            raised if the value is not present.

        :raises: :py:exc:`ValueError` if multiple values are present and ``index`` is
            None.
        :raises: :py:exc:`KeyError` if the requested value is not found and ``default``
            is not set.
        """
        decodes = self.get_all(k)
        if index is None:
            if len(decodes) > 1:
                msg = (
                    f"Multiple decodes exist matching {k!r}. Use fields[{k!r}] to get"
                    f" them all, or fields.get({k!r}, index=n) to get a specific one."
                )
                raise ValueError(msg)
            _index = 0
        else:
            _index = index

        if _index >= len(decodes):
            if default is ...:
                msg = str(k)
                if index is not None:
                    msg += f" [{index}]"
                raise KeyError(msg)
            else:
                return default
        return decodes[_index]

    def values(self) -> List[DecodedField]:
        """Retrieve a list of all decodes."""
        return [DecodedField(d) for d in self._fields]


class DecodedField(JsonBacked, init=False):
    """
    A decoded field from an event
    """

    id: DecodeFieldId
    size: int
    value: int
    decoding: str | None

    @property
    def name(self) -> str | None:
        return self.id.name
