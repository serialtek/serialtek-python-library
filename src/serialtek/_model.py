from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, Optional, Tuple, TypeVar

import pydantic
from pydantic import ConfigDict


model_context: ContextVar[Optional[ModelContext]] = ContextVar("test", default=None)


@dataclass(frozen=True)
class ModelContext:
    """Context to use when parsing models.

    When parsing models, we can sometimes make more information available based on the
    trace context (for example, determining the base for Ticks values).
    """

    ticks_base: Optional[int]

    @staticmethod
    @contextmanager
    def set(context: Optional[ModelContext]):
        tok = model_context.set(context)

        tok = model_context.set(context) if context is not None else None
        try:
            yield
        finally:
            if tok is not None:
                model_context.reset(tok)

    def update(self, other: ModelContext | None) -> ModelContext:
        if other is None:
            return self
        return ModelContext(**{**self.__dict__, **other.__dict__})

class BaseModel(pydantic.BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="allow",
    )

    def __extra_fields__(self) -> Iterable[Tuple[str, Any]]:
        yield from (
            (k, v)
            for k, v in self.model_dump(exclude_unset=True).items()
            if k not in self.__class__.model_fields
        )

    def __str__(self) -> str:
        return super().__repr__()

    def try_attr(self, attr: str, default: Any = None) -> Any:
        try:
            return getattr(self, attr)
        except AttributeError:
            return default


T = TypeVar("T")
