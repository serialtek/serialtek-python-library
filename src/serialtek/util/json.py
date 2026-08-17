from __future__ import annotations

import builtins
import datetime
import sys
from contextlib import suppress
from enum import Enum
from typing import (
    Any,
    Generic,
    Iterator,
    SupportsIndex,
    TypeVar,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from typing_extensions import dataclass_transform, Unpack

from serialtek._model import ModelContext, model_context
from serialtek.util import Json, try_enum

T = TypeVar("T")
D = TypeVar("D")

_RAISE = object()


@dataclass_transform(frozen_default=True)
class JsonBacked:
    raw_data: Json
    _context: ModelContext | None
    _fields: dict[str, Any]

    def __init__(self, data: Json, context: ModelContext | None = None):
        self.raw_data = data
        self._context = context

    @classmethod
    def _from_json(cls, data: Any, **args: FromJsonArgs):
        context = model_context.get()
        return cls(data, context)

    def __init_subclass__(cls, init: bool = False) -> None:
        super().__init_subclass__()
        # Annotations that reference a name which isn't bound yet (for example a
        # self-reference to the class currently being defined, or a forward
        # reference to a sibling class defined later in the module) can't be
        # resolved until the module has finished loading. Callers with such
        # annotations must call `recalculate_fields()` again once those names
        # are available.
        with suppress(NameError):
            cls.recalculate_fields()

    @classmethod
    def recalculate_fields(cls) -> None:
        """Re-resolve this class's annotations and rebuild its fields.

        `__init_subclass__` calls this automatically, but annotations that
        forward-reference a name not yet bound in the module (such as a class
        referencing itself, e.g. ``nvme_transactions: list[AnyTransaction]``
        inside ``AnyTransaction`` itself) can't be resolved at that point. For
        those cases, call this again after the module has finished defining
        all the relevant names.
        """
        cls._fields = {}
        module_globals = vars(sys.modules[cls.__module__])

        fields = {
            name: annotation
            for name, annotation in cls.__annotations__.items()
            if not name.startswith("_")
        }

        resolved = _resolve_annotations(fields, module_globals)
        for name, annotation in resolved.items():
            setattr(cls, name, _make_field(name, annotation))
            cls._fields[name] = annotation

    @overload
    def inner_get_as(self, ty: type[T], key: str) -> T:
        ...

    @overload
    def inner_get_as(self, ty: type[T], key: str, default: D) -> T | D:
        ...

    def inner_get_as(self, ty: type[Any], key: str, default: Any = _RAISE) -> Any:
        with ModelContext.set(self._context):
            return get_as(self.raw_data, ty, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return self.__getattribute__(key)
        except AttributeError:
            return self.raw_data[key]

    def __str__(self):
        return str(self.raw_data)

    def __repr__(self):
        return str(self.raw_data)

    def __contains__(self, item: str):
        return item in self.raw_data

class JsonArrayBacked(Generic[T], list[T]):
    @property
    def raw_data(self) -> list[T]:
        return list(self)

    def __init__(self, data: list[T], ty: type[T], context: ModelContext | None = None):
        super().__init__(data)
        self._context = context
        self._ty = ty

    @overload
    def __getitem__(self, i: SupportsIndex, /) -> T: ...
    @overload
    def __getitem__(self, s: slice[SupportsIndex | None], /) -> list[T]: ...

    def __getitem__(self, index: SupportsIndex | slice[SupportsIndex | None]):
        match index:
            case slice():
                return [convert_type(self._ty, item) for item in super().__getitem__(index)]
            case _:
                return convert_type(self._ty, super().__getitem__(index))

    def __iter__(self) -> Iterator[T]:
        yield from (convert_type(self._ty, t) for t in super().__iter__())

    def __contains__(self, value: object) -> bool:
        return any(item == value for item in self)

    @classmethod
    def _from_json(
        cls, v: Any, **args: Unpack[FromJsonArgs]
    ) -> JsonArrayBacked[Any]:
        (ty,) = get_args(args["ty"])
        return cls(v, ty, model_context.get())

class FromJsonArgs(TypedDict):
    ty: Any


def _resolve_annotations(
    annotations: dict[str, Any], globalns: dict[str, Any]
) -> dict[str, Any]:
    """Resolve (possibly stringized) annotations to real types.

    ``get_type_hints`` is used against a throwaway carrier so that string
    annotations produced by ``from __future__ import annotations`` are
    evaluated in ``globalns`` (the defining module's namespace)."""

    def _carrier() -> None:
        ...

    _carrier.__annotations__ = annotations
    return get_type_hints(_carrier, globalns)


def _make_field(name: str, annotation: type) -> property:
    """Build a read-only property that reads ``self.data[name]`` and wraps it in
    the annotated type.

    For a required field a missing key raises ``AttributeError`` (not
    ``KeyError``) so that ``hasattr`` reports the field as absent. For an
    optional field (``X | None``) a missing key returns ``None``, and the value
    is wrapped in the non-``None`` member type when present."""

    members = [arg for arg in get_args(annotation) if arg is not type(None)]
    optional = len(members) < len(get_args(annotation))
    if optional and len(members) == 1:
        annotation = members[0]

    def getter(self: JsonBacked) -> Any:
        try:
            return self.inner_get_as(annotation, name, None if optional else _RAISE)  # type: ignore
        except KeyError:
            if optional:
                return None
            raise AttributeError(name) from None

    getter.__name__ = name
    return property(getter)


@overload
def get_as(d: dict[str, Any], ty: type[T], key: str) -> T:
    ...


@overload
def get_as(d: dict[str, Any], ty: type[T], key: str, default: D) -> T | D:
    ...


def get_as(d: dict[str, Any], ty: type[Any], key: str, default: Any = _RAISE) -> Any:
    try:
        raw = d[key]
    except KeyError:
        if default is _RAISE:
            raise
        else:
            return default
    if raw is None and default is None:
        return default
    try:
        return convert_type(ty, raw)
    except TypeError as e:
        e.args = (f"{e.args[0]} for {key}",)
        raise


def convert_type(ty: type[Any], raw: Any) -> Any:
    match ty:
        case ty if hasattr(ty, "_from_json"):
            return ty._from_json(raw, ty=ty)
        case ty if hasattr(ty, "_validate"):
            # backwards compatibility with types that support pydantic
            return ty._validate(raw)
        case datetime.datetime:
            if not isinstance(raw, str):
                msg = f"Expected str, got `{raw!r}`"
                raise TypeError(msg)
            return datetime.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
        case builtins.bool | builtins.str | builtins.int | builtins.float:
            if not isinstance(raw, ty):
                msg = f"Expected {ty.__name__}, got `{raw!r}`"
                raise TypeError(msg)
            return raw
        case ty if get_origin(ty) is list:
            (el,) = get_args(ty)
            return JsonArrayBacked._from_json(  # pyright: ignore[reportPrivateUsage]
                raw, ty=JsonArrayBacked[el]
            )
        case ty if issubclass(ty, Enum):
            return try_enum(ty, raw)
        case ty if get_origin(ty) is dict:
            msg = "Not supported"
            raise RuntimeError(msg)
        case ty:
            return ty(raw)
