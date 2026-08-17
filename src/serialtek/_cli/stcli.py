import atexit
import os
import shlex
import sys
from pathlib import Path
from typing import Optional

import click
from click_option_group import optgroup
from rich.console import Console

from serialtek.cli import CliConfig, app_dirs

from .context import AppContext
from .logging import configure_logging, getLogger
from .output import FORMATS
from .sections.login import active, discover, login, logout
from .sections.config import config
from .sections.request import request

log = getLogger(__name__)


@click.group()
@click.pass_context
@click.option(
    "-f",
    "--format",
    envvar="STCLI_FORMAT",
    type=click.Choice(FORMATS, case_sensitive=False),
    default="auto",
    help="How to format output from commands",
    show_envvar=True,
)
@click.option(
    "-c",
    "--config",
    envvar=CliConfig.env_var,
    default=app_dirs.user_config_dir,
    type=click.Path(path_type=Path),
    help="Path to save configuration to",
    show_envvar=True,
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable verbose logging. Use multiple times (eg -vv, -vvvv) for more.",
)
@optgroup.group(
    "Connection parameters.",
    help="""
                Override connection parameters for the Kodiak for this command
                only. use `serialtek login` for persistent connection
                settings.""",
)
@optgroup.option("-u", "--username", default=None, help="Username to log in with")
@optgroup.option("-p", "--password", default=None, help="Password to log in with")
@optgroup.option("-k", "--key", default=None, help="API Key to log in with")
@optgroup.option("-h", "--host", default=None, help="host to connect to.")
def cli(
    ctx: click.Context,
    username: Optional[str],
    password: Optional[str],
    key: Optional[str],
    host: Optional[str],
    format: str,
    config: Path,
    verbose: int,
):
    """SerialTek CLI application.

    This application consists of a number of subcommands, listed below. To see
    detailed help for any subcommand, run that command with the --help flag.

    Some arguments (such as --format) can have their default values configured
    with environment variables, see the help for the different options for more
    info.
    """
    svg = os.environ.get("_STCLI_EXPORT_SVG")
    if svg:
        print("Generating SVG of command ouput...")
        if os.environ.get("_STCLI_SVG_COMMAND"):
            cmds = os.environ["_STCLI_SVG_COMMAND"].split(";")
        else:
            cmds = [shlex.join(["serialtek"] + sys.argv[1:])]
        con = Console(record=True, width=max(max(len(cmd) for cmd in cmds) + 4, 80))
        for cmd in cmds:
            con.print(f"[bright_black]$[/bright_black] {cmd}  ", highlight=False)

        @atexit.register
        def save_svg():  # type: ignore
            con.print("")
            con.save_svg(svg, title="")
            print(f"Output saved to {svg}")

    else:
        con = Console()

    ctx.obj = {}
    ctx.obj["app"] = AppContext(
        username,
        password,
        key,
        host,
        format,
        config,
        verbose,
        con,
    )

    configure_logging(verbose)


cli.add_command(active)
cli.add_command(login)
cli.add_command(logout)
cli.add_command(discover)
cli.add_command(config)
cli.add_command(request)


def main():
    try:
        cli.main()
    except Exception as e:
        if os.environ.get("_STCLI_DEV"):
            log.exception("Failed with exception:")
        else:
            log.debug("Failed with exception:", exc_info=sys.exc_info())
        log.error("[%s] %s", type(e).__name__, e)  # noqa: TRY400
        sys.exit(1)


if __name__ == "__main__":
    main()
