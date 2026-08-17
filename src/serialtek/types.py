import builtins
import functools
from typing import Any, Callable, TypeVar, cast

from typing_extensions import ParamSpec, Protocol


class Writeable(Protocol):
    """Protocol indicating a binary writeable object.

    Arguments that require :py:class:`.Writeable` just need the object to have a
    :py:meth:`write` method.
    """

    def write(self, b: bytes) -> int:
        """Write the given data, and return the number of bytes written.

        This method should behave like the write method on an open file.
        """
        ...


class Readable(Protocol):
    """Protocol indicating a binary readable object.

    Arguments that require :py:class:`.Readable` just need the object to have a
    :py:meth:`read` method.
    """

    def read(self, count: int) -> bytes:
        """Read and return up to ``count`` bytes of data.

        If the end of the data is reached, return only the available bytes.

        This method should behave like the read method on an open file.
        """
        ...


P = ParamSpec("P")
T = TypeVar("T")


def override_return_type(
    original: Callable[P, Any]
) -> Callable[[Callable[..., T]], Callable[P, T]]:
    """:meta private:"""

    def decorator(f: Callable[..., T]) -> Callable[P, T]:
        wrapper = functools.wraps(original)(
            lambda *args, **kwargs: original(*args, **kwargs)  # type: ignore
        )
        wrapper.__doc__ = f.__doc__
        return cast(Callable[P, T], wrapper)

    return decorator


# Sphinx documents the parameters for the __init__/__new__ method on a class alongside
# the class docstring. For classes that aren't meant to be constructed by a user (ie,
# classes that are only ever returned as the result of a function), this can be
# confusing. If we just get rid of __init__ when generating docs, we can hide those
# values where they aren't useful.
try:
    # If builtins.__sphinx_build__ exists, then we're generating documentation.
    # Otherwise, AttributeError will be raised.
    getattr(builtins, "__sphinx_build__")

    def undocumented_constructor(cls: T) -> T:  # type: ignore
        """:meta private:"""

        def blank(self: T):
            return

        cls.__init__ = blank  # type: ignore
        cls.__new__ = blank  # type: ignore
        return cls

except AttributeError:

    def undocumented_constructor(cls: T) -> T:
        """:meta private:"""
        return cls
