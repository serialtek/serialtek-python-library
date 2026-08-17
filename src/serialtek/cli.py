from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional, Tuple, Union, TYPE_CHECKING

from appdirs import AppDirs
from pydantic import BaseModel

from serialtek.types import undocumented_constructor

from .credentials import FileBackedCredentialsManager, GetpassCallback, StoreMode

if TYPE_CHECKING:
    from serialtek.kodiak import Kodiak

app_dirs = AppDirs("stcli", "SerialTek")

class CliConfig:
    """Cli configuration.

    This allows accessing some of the configuration from the CLI from within python
    scripts.
    """

    env_var = "STCLI_CONFIG_DIR"

    dir: Path

    def __init__(self, dir: Optional[Union[str, Path]] = None):
        if dir is None:
            config_dir = app_dirs.user_config_dir
            dir = os.environ.get(self.env_var, config_dir)
            if dir is None:  # pyright: ignore[reportUnnecessaryComparison]
                msg = "Could not determine config location."
                raise RuntimeError(msg)
        self.dir = Path(dir)

    def credentials_manager(
        self,
        save_password: Optional[bool] = None,
        getpass: Optional[GetpassCallback] = None,
        store_mode: StoreMode = StoreMode.STORE,
    ) -> CliCredentialsManager:
        """Return the :py:class:`CliCredentialsManager` associated with the CLI config."""
        return CliCredentialsManager(
            dir=self.dir,
            save_password=save_password,
            getpass=getpass,
            store_mode=store_mode,
        )

    def get_active_kodiak(self) -> Optional[Tuple[str, str]]:
        """Get the host and serial number of the CLI's active Kodiak.

        :return: a tuple with two strings eg. ``(host, serial)``, or ``None`` if the CLI
            doesn't have an active Kodiak.
        """
        state_path = self.dir / "active"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            return state["host"], state["serial"]
        else:
            return None

    def set_active_kodiak(self, kodiak: Kodiak):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "active").write_text(
            ActiveKodiakFile(
                host=kodiak.session.host,
                serial=kodiak.serial,
            ).model_dump_json()
        )

    def clear_active_kodiak(self):
        (self.dir / "active").unlink(missing_ok=True)


@undocumented_constructor
class CliCredentialsManager(FileBackedCredentialsManager):
    """The credentials manager used by the serialtek cli application.

    This class allows access to the same credentials stored by the cli, meaning you
    can log in with ``serialtek login`` at the command line, then later use those
    credentials in a python script.

    Access this class with :py:meth:`.CliConfig.credentials_manager`.
    """

    def __init__(
        self,
        dir: Path,
        save_password: Optional[bool] = None,
        getpass: Optional[GetpassCallback] = None,
        store_mode: StoreMode = StoreMode.STORE,
    ):
        super().__init__(Path(dir) / "auth", save_password, getpass, store_mode)

class ActiveKodiakFile(BaseModel):
    version: Literal[1] = 1
    host: str
    serial: str
