import json
import logging
import sys
from http.client import responses
from typing import TYPE_CHECKING

import click
from requests import Session

from serialtek._cli.logging import getLogger

if TYPE_CHECKING:
    from serialtek._cli.context import AppContext

log = getLogger(__name__)


METHODS = [
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "DELETE",
    "CONNECT",
    "OPTIONS",
    "TRACE",
    "PATCH",
]

cmd_help = """\
Send a single API request to the Kodiak and return the response.

URL should be the path to the endpoint, not including the host name (ie, starting
with "/kodiak"):

\b
    serialtek request GET /kodiak/v1/status

BODY can be used to specify the body of the request:

\b
    serialtek request POST /kodiak/v1/traces/open '{"path": "/media/SATADrive0/my-trace.sttrace"}'

Since this command deals almost exlusively with JSON data, the default output format
for this command is overridden to "json".
"""

if "win32" in sys.platform:
    cmd_help += """
Note: On Windows, it is recommended to use PowerShell for this command instead of
cmd.exe: cmd's quoting isn't quite as flexible, and the above command would need to
be escaped:

\b
    serialtek request POST /kodiak/v1/traces/open "{\\"path\\": \\"/media/SATADrive0/my-trace.sttrace\\"}"

In PowerShell, single quotes can be used like in the initial example.
"""


@click.command(help=cmd_help)
@click.argument("method", type=click.Choice(METHODS, case_sensitive=False))
@click.argument("url")
@click.argument("body", default="")
@click.option("-n", "--no-auth", is_flag=True, help="Do not log in.")
@click.option(
    "-r",
    "--raw",
    is_flag=True,
    help="Output raw response contents (no formatting, no newline at end, etc)",
)
@click.option(
    "-x",
    "--exit-code",
    is_flag=True,
    help=(
        "Exit the program with an error status code if the status code of the response"
        " is not a success."
    ),
)
@click.pass_context
def request(
    ctx: click.Context,
    method: str,
    url: str,
    body: str,
    no_auth: bool,
    raw: bool,
    exit_code: bool,
):
    """Send a single API request to the Kodiak and return the response."""
    app_ctx: AppContext = ctx.obj["app"]

    # The "pretty" format isn't super useful here since we're dealing
    # directly with json, may as well use json output by default.
    app_ctx.override_default_output("json")

    if no_auth:
        session = Session()
        session.verify = False
    else:
        session = app_ctx.open_kodiak().session

    data = body if body else None

    resp = session.request(
        method, url, data=data, headers={"Content-Type": "application/json"}
    )
    log.log(
        logging.INFO if resp.status_code == 200 else logging.WARNING,
        "Status code: %d (%s)",
        resp.status_code,
        responses[resp.status_code],
    )

    if raw:
        sys.stdout.buffer.write(resp.content)
    else:
        if resp.headers.get("content-type") == "application/json":
            try:
                app_ctx.output.print_object(resp.json())
            except json.JSONDecodeError:
                print(resp.text)
        else:
            print(resp.text)

    if exit_code and (resp.status_code >= 400):
        # We only have 1-255 available for exit codes, so use the 100s 200s to represent
        # the 400/500 errors.
        sys.exit(resp.status_code - 300)
