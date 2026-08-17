import json
import logging
from dataclasses import dataclass

import click
from typing_extensions import Literal

import serialtek.logging


@dataclass(frozen=True)
class _Cfg:
    cli: int
    lib: int
    request: Literal["url", "body", None]


def configure_logging(level: int):
    """Configure logging based on the given level."""
    # Configure logging
    cfgs = [
        _Cfg(
            cli=logging.INFO,
            lib=logging.WARN,
            request=None,
        ),
        _Cfg(
            cli=logging.INFO,
            lib=logging.INFO,
            request=None,
        ),
        _Cfg(
            cli=logging.DEBUG,
            lib=logging.DEBUG,
            request=None,
        ),
        _Cfg(
            cli=logging.DEBUG,
            lib=logging.DEBUG,
            request="url",
        ),
        _Cfg(
            cli=logging.DEBUG,
            lib=logging.DEBUG,
            request="body",
        ),
    ]
    level = max(0, min(level, len(cfgs) - 1))
    cfg = cfgs[level]

    handler = serialtek.logging.configure_logging(
        cfg.lib,
        log_requests=cfg.request,
    )

    handler.tracebacks_suppress.append(click)  # type: ignore
    handler.tracebacks_suppress.append(json)  # type: ignore

    cli = logging.getLogger("stcli")
    cli.addHandler(handler)
    cli.setLevel(cfg.cli)


def getLogger(name: str) -> logging.Logger:
    """Get a logger with a friendlier name for cli modules.

    The convention of calling getLogger(__name__) will give us a name like
    `serialtek._cli.(whatever)`. Which is fine, but a shorter/more descriptive name
    would be a bit better.
    """
    return logging.getLogger(name.replace("serialtek._cli", "stcli"))
