from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Optional, Tuple

from click import ClickException, UsageError

from serialtek.cli import ActiveKodiakFile, CliConfig, CliCredentialsManager
from serialtek.credentials import (
    ApiKey,
    Credentials,
    CredentialsManager,
    LoginCredentials,
)
from serialtek.session import ApiSession

from .logging import getLogger
from .output import Output, prompt
from serialtek import Kodiak

if TYPE_CHECKING:
    from pathlib import Path

    from rich.console import Console


log = getLogger(__name__)


@dataclass
class AppContext:
    username_arg: Optional[str]
    password_arg: Optional[str]
    api_key_arg: Optional[str]
    host_arg: Optional[str]
    output_fmt_arg: str
    dir: Path
    verbose_arg: int
    output_console: Console

    @cached_property
    def host(self) -> str:
        """The Kodiak to connect to.

        This is the --host argument if specified, or else it's the active Kodiak.
        """
        if self.host_arg:
            return self.host_arg
        try:
            state = ActiveKodiakFile.model_validate_json(
                (self.dir / "active").read_text()
            )
        except FileNotFoundError as e:
            msg = (
                "There is no active Kodiak. Connect to a Kodiak with `serialtek"
                " login`"
            )
            raise RuntimeError(msg) from e

        self.serial = state.serial
        return state.host

    @cached_property
    def serial(self) -> str:
        """The serial number of the active Kodiak."""
        host = self.host
        # It's possible that when checking the host, the serial number was pulled from
        # the active Kodiak file.
        if "serial" in self.__dict__:
            return self.__dict__["serial"]
        else:
            return ApiSession.host_info(host).serial

    @cached_property
    def args_credentials(self) -> Optional[Credentials]:
        """Get the credentials specified at the command line, if there are any."""
        match self:
            case AppContext(username_arg=str(username), password_arg=password, api_key_arg=None):
                return LoginCredentials(username=username, password=password)
            case AppContext(username_arg=None, password_arg=None, api_key_arg=str(key)):
                return ApiKey(key=key)
            case AppContext(username_arg=None, password_arg=None, api_key_arg=None):
                return None
            case _:
                msg = "Specify either username[+password] or api key, not both."
                raise UsageError(msg)

    @cached_property
    def output(self):
        """Get the Output object to use for the command."""
        return Output.initialize(self.output_fmt_arg, self.output_console)

    def override_default_output(self, arg: str):
        """Override the default output mode.

        This will change the output mode only if it has been left at "auto". Must be
        called before accessing :py:meth:`output`.
        """
        if self.output_fmt_arg == "auto":
            self.output_fmt_arg = arg

    def get_active_kodiak(self) -> Tuple[str, str]:
        an = CliConfig(self.dir).get_active_kodiak()
        if an is None:
            msg = (
                "There is no active Kodiak. Open one with"
                f" `{os.path.basename(sys.argv[0])} login`"
            )
            raise ContextUnavailableException(msg)
        return an

    def set_active_kodiak(self, kodiak: Kodiak):
        CliConfig(self.dir).set_active_kodiak(kodiak)

    def clear_active_kodiak(self):
        CliConfig(self.dir).clear_active_kodiak()

    def open_kodiak(self) -> Kodiak:
        if self.args_credentials:
            credman = CredentialsManager(getpass=self.getpass)
            credman.set(self.serial, self.args_credentials)
        else:
            credman = CliCredentialsManager(self.dir, getpass=self.getpass)

        return Kodiak(self.host, credentials_manager=credman)

    def getpass(self, username: Optional[str], host: Optional[str]) -> str:
        if self.password_arg is not None:
            return self.password_arg
        else:
            return prompt(f"Enter password for {username}@{host}", password=True)


class ContextUnavailableException(ClickException):
    """Raised when needed context isn't present."""
