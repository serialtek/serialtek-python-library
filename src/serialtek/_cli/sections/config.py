from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from serialtek._cli.context import AppContext


@click.group
@click.pass_context
def config(ctx: click.Context):
    """Manage configuration for this application."""


@config.command
@click.pass_context
def dir(ctx: click.Context):
    """Print the directory where configuration is stored."""
    print(ctx.obj["app"].dir)


@config.command
@click.pass_context
def clear(ctx: click.Context):
    """Erase stored configuration."""
    app_ctx: AppContext = ctx.obj["app"]
    if app_ctx.dir.exists():
        shutil.rmtree(app_ctx.dir)
