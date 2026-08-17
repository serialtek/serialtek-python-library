import contextlib
from typing import Optional

import click
import requests
from rich.text import Text

from serialtek import Kodiak
from serialtek import errors as err
from serialtek._cli.context import AppContext, ContextUnavailableException
from serialtek._cli.logging import getLogger
from serialtek._cli.output import TableColumn, prompt
from serialtek.cli import CliCredentialsManager
from serialtek.credentials import (
    ApiKey,
    CredentialsManager,
    LoginCredentials,
    LoginSession,
)
from serialtek.discovery import DISCOVERY_TIMEOUT_DEFAULT, KodiakDiscovery

log = getLogger(__name__)


@click.command
@click.argument("host")
@click.option("-u", "--username", default=None, help="Username to log in with.")
@click.option("-p", "--password", default=None, help="Password to log in with.")
@click.option("-k", "--key", default=None, help="API Key to log in with.")
@click.option(
    "-n",
    "--no-activate",
    is_flag=True,
    help="Log in and save credentials, but do not update the active Kodiak.",
)
@click.option(
    "--save-password", is_flag=True, default=False, help="Save password to disk."
)
@click.pass_context
def login(
    ctx: click.Context,
    host: str,
    username: Optional[str],
    password: Optional[str],
    key: Optional[str],
    save_password: bool,
    no_activate: bool,
):
    """Connect to a Kodiak and set its connection as active.

    The connection can either be made with a username and password, or with an
    API key. If the connection is successful, the credentials are stored and the
    Kodiak is marked as the active Kodiak for future commands.

    By default, when logging in with a password the password will not be saved.
    In most cases the session can be preserved after login without the password,
    but for some operations the password may need to be re-prompted. To save the
    password to disk, use --save-password. Note that this saves the password in
    plain text on disk.

    To log in with a username and password:

    \b
        $ serialtek login --username USERNAME [--password PASSWORD] HOST

    To log in with an API key:

    \b
        $ serialtek login --key API_KEY HOST

    API_KEY can be any of the following:

    \b
        * The "key" value for any API key
        * The "name" or "id" for a locally saved API key (see the help for the `keys` command).

    To log in to a host using prevously stored credentials:

    \b
        $ serialtek login HOST

    """
    app_ctx: AppContext = ctx.obj["app"]

    # Pass the credentials args from here into the context, preferring ones set here
    # over earlier.
    if app_ctx.username_arg is None:
        app_ctx.username_arg = username
    if app_ctx.password_arg is None:
        app_ctx.password_arg = password
    if app_ctx.api_key_arg is None:
        app_ctx.api_key_arg = key
    app_ctx.host_arg = host

    # Get the credentials specified by the arguments.
    credentials = app_ctx.args_credentials

    # Open the credentials file
    credman = CliCredentialsManager(app_ctx.dir, save_password=save_password)
    credstore = credman.get_store(app_ctx.serial)

    # If we don't have credentials from the command line, look for saved
    # ones.
    if credentials is None:
        credentials = credstore.get()

    # If we don't have any credentials, ask for a user name.
    if credentials is None:
        credentials = LoginCredentials(username=click.prompt("Enter user name"))

    try:
        # Open a Kodiak *without* a connection to the credentials file.
        an = Kodiak(
            host,
            credentials_manager=CredentialsManager(
                getpass=lambda username, host: prompt(
                    f"Enter password for {username}@{host}", password=True
                )
            ),
        )
        an.login(credentials)

    except (err.RequestFailedError, err.InsufficientCredentialsError) as e:
        msg = "Login failed (invalid credentials)"
        raise RuntimeError(msg) from e

    if not an.check_credentials():
        msg = "Login failed (invalid credentials)."
        raise RuntimeError(msg)

    used_creds = an.session.credentials_store.get()
    if used_creds is not None:
        log.info("Login successful using %r", used_creds)
    else:
        log.info("Login successful")

    if no_activate is False:
        app_ctx.set_active_kodiak(an)

    # Finally, save the credentials we used.
    if used_creds:
        credstore.set(used_creds)


@click.command
@click.pass_context
def active(ctx: click.Context):
    """Show the active Kodiak connection/authentication"""
    app_ctx: AppContext = ctx.obj["app"]
    output = app_ctx.output

    host, serial = app_ctx.get_active_kodiak()

    credman = CliCredentialsManager(app_ctx.dir, getpass=app_ctx.getpass)
    credentials = credman.get_store(serial).get()

    match credentials:
        case LoginSession() | LoginCredentials():
            cred_desc = f"User ({credentials.username})"
        case ApiKey():
            cred_desc = f"API key ({credentials.id})"
        case _:
            cred_desc = "none"

    connected = False
    authenticated = False
    try:
        an = app_ctx.open_kodiak()
        connected = an.check()
        if connected:
            if isinstance(credentials, LoginSession):
                an.session.refresh(retry_login=False)
            authenticated = an.check_credentials(retry_login=False)
    except (err.RequestFailedError, requests.exceptions.ConnectionError):
        pass

    output.print_object(
        {
            "host": host,
            "serial": serial,
            "credentials": cred_desc,
            "connected": connected,
            "authenticated": authenticated,
        }
    )


@click.command
@click.pass_context
@click.option("--clear", "-c", is_flag=True, help="clear the active Kodiak as well.")
def logout(ctx: click.Context, clear: bool):
    """Log out of the active Kodiak.

    This will clear the credentials used for connecting to this Kodiak.
    """
    app_ctx: AppContext = ctx.obj["app"]
    with contextlib.suppress(ContextUnavailableException):
        CliCredentialsManager(app_ctx.dir).delete(app_ctx.serial)
    app_ctx.clear_active_kodiak()


@click.command
@click.pass_context
@click.option(
    "-t",
    "--timeout",
    help="Timeout this many seconds after starting (0 to run indefinitely)",
    default=DISCOVERY_TIMEOUT_DEFAULT,
    show_default=True,
)
@click.option(
    "-c",
    "--count",
    help="Stop after discovering this many Kodiaks",
    default=0,
)
@click.option(
    "-I",
    "--ip-url",
    help="populate the URL field with the ip address instead of the host name.",
    is_flag=True,
)
def discover(ctx: click.Context, timeout: float, count: int, ip_url: bool):
    """Discover Kodiaks on the network."""
    app_ctx: AppContext = ctx.obj["app"]
    output = app_ctx.output

    ip_col = TableColumn(
        "ip", width=15, pretty_header=Text("IP Address", "b"), style="green"
    )
    serial_col = TableColumn(
        "serial", width=12, pretty_header=Text("Serial", "b"), style="cyan"
    )
    alias_col = TableColumn("alias", pretty_header=Text("Alias", "b"), style="b")
    url_col = TableColumn(
        "url",
        width=33,
        pretty_header=Text("URL", "b"),
    )

    cols = (
        ip_col,
        serial_col,
        url_col,
        alias_col,
    )

    with KodiakDiscovery() as disc:
        def disc_iter():
            for i, d in enumerate(disc.iter(timeout=None if timeout == 0 else timeout)):
                url = f"https://{d.ip}" if ip_url else d.url
                yield (
                    str(d.ip),
                    d.serial,
                    url,
                    d.alias,
                )

                if count and i + 1 == count:
                    return

        output.print_table_async(cols, disc_iter())
