from __future__ import annotations

import functools
import json
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

import rich.json
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt
from rich.table import Table

from serialtek.logging import stderr_consle as stderr
from serialtek.tasks import WaitParams

if TYPE_CHECKING:
    from rich.console import Console
    from typing_extensions import Self

prompt = functools.partial(Prompt().ask, console=stderr)

FORMATS = ["auto", "pretty", "plain", "json", "json-pretty", "json-plain"]

T = TypeVar("T")


def human_size(size: int) -> str:
    """Convert a number of bytes to a human-readable size."""
    div = 1024
    magnitudes = iter(["B", "kB", "MB", "GB", "TB"])
    m = next(magnitudes)
    hsize: float = size
    while hsize >= div:
        hsize /= div
        m = next(magnitudes)
    return f"{hsize:.02f} {m}"


named_colors = {
    "red": "red3",
    "orange": "orange_red1",
    "tangerine": "orange1",
    "yellow_orange": "orange1",
    "yellow": "gold1",
    "light_green": "spring_green3",
    "green": "dark_sea_green4",
    "dark_green": "chartreuse4",
    "lime_green": "chartreuse2",
    "very_light_green": "dark_sea_green3",
    "teal": "light_sea_green",
    "light_teal": "aquamarine3",
    "blue": "deep_sky_blue4",
    "light_blue": "steel_blue3",
    "very_light_blue": "dark_slate_gray3",
    "violet": "medium_orchid",
    "lavender": "dark_violet",
    "purple": "purple",
    "brown": "orange4",
    "light_brown": "indian_red",
    "charcoal": "grey30",
    "grey": "grey62",
}

theme_colors = {
    "speed.spd2_5": named_colors["orange"],
    "speed.spd5": named_colors["light_green"],
    "speed.spd8": named_colors["blue"],
    "speed.spd16": named_colors["yellow"],
    "speed.spd32": named_colors["teal"],
    "width.x1": named_colors["orange"],
    "width.x2": named_colors["light_green"],
    "width.x4": named_colors["blue"],
    "width.x8": named_colors["yellow"],
    "width.x12": named_colors["teal"],
    "width.x16": named_colors["green"],
}

colors: DefaultDict[str, str] = defaultdict(
    lambda: "default",
    **named_colors,
    **theme_colors,
)


class Output(ABC):
    """Class to handle CLI output in different formats."""

    # whether this output format allows pretty output: arbitrary output to stdout should
    # only happen if this is True, otherwise one of the print_methods of this class
    # should be used.
    pretty: Optional[Console] = None

    @staticmethod
    def initialize(output_arg: Optional[str], console: Console) -> Output:
        if output_arg is None:
            output_arg = "auto"

        if output_arg == "auto":
            # Do pretty output on a tty, simple output otherwise.
            output_arg = "pretty" if sys.stdout.isatty() else "plain"

        if output_arg == "json":
            output_arg = "json-pretty" if sys.stdout.isatty() else "json-plain"

        try:
            ocls: Type[Output] = {
                "pretty": PrettyOutput,
                "plain": PlainOutput,
                "json-plain": PlainJsonOutput,
                "json-pretty": PrettyJsonOutput,
            }[output_arg]
        except KeyError:
            msg = f"Invalid output format {output_arg!r}"
            raise TypeError(msg) from None

        return ocls(console)

    def __init__(self, con: Console) -> None:
        super().__init__()
        self._con = con

    def print_objects(self, **kwargs: Any) -> None:
        """Print multiple objects, each with its own title.

        When printing as json, this will collect the objects into a dictionary.
        """
        self.print_object(kwargs)

    @abstractmethod
    def print_object(self, obj: Any) -> None:
        """Print a single object."""
        ...

    def print_list(self, l: List[Any]) -> None:
        """Print a list of objects.

        Each object in the list should have a reasonable string representation on its
        own, no recursive rendering will be done.
        """
        self.print_object(str(o) for o in l)

    @abstractmethod
    def print_table_async(
        self,
        cols: Tuple[Union[TableColumn, str], ...],
        rows: Iterable[Iterable[Any]],
    ) -> None:
        """Print a list of objects from an iterator, as they come in."""
        ...

    @abstractmethod
    def print_table(self, cols: Tuple[str, ...], rows: Iterable[Iterable[Any]]):
        """Print a table of values."""
        ...


class PrettyOutput(Output):
    """Print output in a human-readable format."""

    def __init__(self, con: Console) -> None:
        super().__init__(con)
        self.pretty = self._con

    def print_objects(self, **kwargs: Any) -> None:
        for title, value in kwargs.items():
            self._con.print(
                f"==[{title}]==", style="b bright_cyan", highlight=False, markup=False
            )
            self._print_object(value, identify_collection=False)

    def print_object(self, obj: Any) -> None:
        if isinstance(obj, str):
            self._con.print(obj, highlight=False, soft_wrap=True)
        else:
            self._print_object(obj, identify_collection=False)

    def _print_object(
        self,
        object: Any,
        indent: int = 0,
        min_width: int = 0,
        nl: bool = True,
        identify_collection: bool = True,
        prefix: Optional[str] = None,
    ):
        i = " " * indent if prefix is None else prefix
        end = "\n" if nl else ""

        if hasattr(object, "__rich__") or hasattr(object, "__rich_console__"):
            self._con.print(f"{i}", end="")
            self._con.print(object, end=end)

        elif isinstance(object, BaseModel):
            values = {
                k: getattr(object, k) for k in object.model_dump(exclude_unset=True)
            }
            self._print_object(
                values,
                indent=indent,
                prefix=prefix,
                identify_collection=identify_collection,
            )

        elif isinstance(object, dict):
            object = cast(Dict[str, Any], object)
            if identify_collection:
                self._con.print(
                    f"{i}[bright_black]({'' if len(object) else 'empty '}object)[/bright_black]"
                )
                indent += 2
                i += "11"

            width = max([len(k) for k in object] + [min_width])
            dict_indent = " " * (indent)
            for key, value in object.items():
                self._con.print(
                    f"{dict_indent}{key}", highlight=False, markup=False, end=""
                )
                self._con.print(
                    "." * (width - len(key)),
                    end="",
                    style="bright_black",
                    highlight=False,
                )
                self._con.print(": ", highlight=False, end="")

                self._print_object(value, indent=indent, prefix="")

        elif isinstance(object, list):
            object = cast(List[Any], object)
            if identify_collection:
                self._con.print(
                    "(list)" if len(object) else "(empty list)",
                    highlight=False,
                    style="bright_black",
                )
                indent += 2

            for el in object:
                self._print_object(el, indent=indent, prefix=(indent * " ") + "- ")

        elif isinstance(object, Enum):
            if isinstance(object.value, str):
                self._con.print(
                    f"{i}[repr.str]{object.value}[/repr.str]", highlight=False
                )
            else:
                self._print_object(object.value, indent=indent, nl=False)
                self._con.print(f" ({object.name})", highlight=False)

        elif isinstance(object, datetime):
            self._con.print(
                f"{i}[iso8601.date]{object.isoformat()}[/iso8601.date]",
                highlight=True,
                end=end,
            )

        else:
            self._con.print(f"{i}{object!r}", end=end)

    def print_table(self, cols: Tuple[str, ...], rows: Iterable[Iterable[Any]]):
        output = Table()
        for col in cols:
            output.add_column(col, style="b white")

        for row in rows:
            output.add_row(*row)
        self._con.print(output)

    def print_table_async(
        self,
        cols: Tuple[Union[TableColumn, str], ...],
        rows: Iterable[Iterable[Any]],
    ) -> None:
        table = Table()
        for col in cols:
            col = TableColumn.from_str(col)
            table.add_column(
                col.name if col.pretty_header is None else col.pretty_header,
                min_width=col.width,
                style=col.style,
            )
        with Live(table, auto_refresh=False, vertical_overflow="visible") as live:
            for row in rows:
                table.add_row(*row)
                live.refresh()


class PlainJsonOutput(Output):
    """Print output as a single json object."""

    def print_object(self, obj: Any) -> None:
        print(json.dumps(jsonable_encoder(obj)))

    def print_table(self, cols: Tuple[str, ...], rows: Iterable[Iterable[Any]]):
        obj = [dict(zip(cols, row)) for row in rows]
        self.print_object(obj)

    def print_table_async(
        self,
        cols: Tuple[Union[TableColumn, str], ...],
        rows: Iterable[Iterable[Any]],
    ) -> None:
        sys.stdout.write("[")
        sys.stdout.flush()
        try:
            first = True
            for row in rows:
                sys.stdout.write(
                    ("," if not first else "")
                    + json.dumps({str(k): v for k, v in zip(cols, row)})
                )
                sys.stdout.flush()
                first = False
        finally:
            print("]")


class PrettyJsonOutput(PlainJsonOutput):
    """Print output as colored json objects."""

    def print_object(self, obj: Any) -> None:
        json_object = jsonable_encoder(obj)
        self._con.print_json(data=json_object)

    def print_table_async(
        self,
        cols: Tuple[Union[TableColumn, str], ...],
        rows: Iterable[Iterable[Any]],
    ) -> None:
        self._con.print("[", end="")
        try:
            first = True
            for row in rows:
                row_json = rich.json.JSON.from_data(
                    {str(k): v for k, v in zip(cols, row)}
                )
                if not first:
                    self._con.print(",", end="")
                self._con.print(row_json, end="")
                first = False
        finally:
            self._con.print("]")


class PlainOutput(Output):
    def print_object(self, obj: Any) -> None:
        self._print_object(obj)

    def _str(self, obj: Any) -> str:
        if isinstance(obj, Enum):
            return str(obj.value)
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif obj is None:
            return "null"
        else:
            return str(obj)

    def _print_object(
        self,
        object: Any,
        prefix: Tuple[str, ...] = (),
    ):
        i = ".".join(prefix) + "\t" if prefix else ""

        if isinstance(object, BaseModel):
            values = {
                k: getattr(object, k) for k in object.model_dump(exclude_unset=True)
            }
            self._print_object(values, prefix=prefix)

        elif isinstance(object, dict):
            object = cast(Dict[str, Any], object)

            for key, value in object.items():
                self._print_object(value, prefix=(*prefix, key))

        elif isinstance(object, list):
            for i, el in enumerate(object):  # type: ignore
                self._print_object(el, prefix=(*prefix, str(i)))
        else:
            print(f"{i}{self._str(object)}")

    def print_list(self, l: List[Any]) -> None:
        for o in l:
            print(str(o))

    def print_table(self, cols: Tuple[str, ...], rows: Iterable[Iterable[Any]]):
        max_widths = [0] * len(cols)
        srows = [[self._str(e) for e in row] for row in rows]
        for row in srows:
            for i, e in enumerate(row):
                max_widths[i] = max(max_widths[i], len(e))

        for row in srows:
            print(
                "\t".join(
                    format(self._str(e), f"{min(40, w)}")
                    for e, w in zip(row, max_widths)
                )
            )

    def print_table_async(
        self,
        cols: Tuple[Union[TableColumn, str], ...],
        rows: Iterable[Iterable[Any]],
    ) -> None:
        widths = [TableColumn.from_str(c).width for c in cols]
        for row in rows:
            print(
                "\t".join(
                    format(self._str(v), str(w) if w else "")
                    for v, w in zip(row, widths)
                )
            )


class WaitProgress:
    """Class allowing us to use a WaitParams callback to render progress."""

    def __init__(self, *, eta: bool = True):
        self.status: Any = None
        self.status_type: Optional[str] = None
        self.eta = eta

        self.task_name: Optional[str] = None
        self.task: Optional[TaskID] = None
        self.last_progress = 0.0

    def __enter__(self):
        return WaitParams(progress_cb=self.progress)

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object):
        if self.status:
            self.status.__exit__(exc_type, exc_val, exc_tb)

    def _change_status(self, status: Literal["prog", "spin", None]):
        if self.status_type == status:
            return

        self.status_type = status

        if self.status:
            self.status.__exit__(None, None, None)

        if status == "prog":
            cols: List[Any] = [
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
            ]
            if self.eta:
                cols.append(TimeRemainingColumn())

            self.status = Progress(
                *cols,
                console=stderr,
                transient=True,
            ).__enter__()
        elif status == "spin":
            self.status = stderr.status("").__enter__()
        else:
            self.status = None

    def progress(self, message: str, progress: Union[float, bool]):
        if progress is True:
            self._change_status(None)
        elif progress is False:
            self._change_status("spin")
            self.status.update(message)
        else:
            self._change_status("prog")
            if message != self.task_name:
                if self.task is not None:
                    self.status.update(self.task, description=message)
                else:
                    self.task = self.status.add_task(message, total=100)
                    self.task_name = message
                    self.last_progress = 0.0
            assert self.task is not None
            self.status.update(self.task, advance=progress - self.last_progress)
            self.last_progress = progress


@dataclass
class TableColumn:
    name: str
    width: Optional[int] = None
    pretty_header: Optional[Any] = None
    style: Optional[Any] = None

    def __str__(self):
        return self.name

    @classmethod
    def from_str(cls, s: Union[str, Self]):
        if isinstance(s, str):
            return cls(s)
        else:
            return s
