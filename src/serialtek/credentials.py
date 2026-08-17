from __future__ import annotations

import enum
import json
import logging
from hashlib import sha256
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Set,
    TypeAlias,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import errors as err

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Self

log: logging.Logger = logging.getLogger(__name__)
# pyright:  reportIncompatibleVariableOverride=false


class GetpassCallback(Protocol):
    """Represents the signature a callback for getting a password should take.

    For example::

        def my_getpass(username: Optional[str], host: Optional[str]) -> str:
            return input(f"Enter password for {username}@{host}")
    """

    def __call__(self, username: Optional[str], host: Optional[str]) -> str:
        ...


class CredentialsBase(BaseModel):
    """A set of credentials to use when communicating with the Kodiak API."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    type: str

    def auth_headers(self) -> Dict[str, str]:
        """Return headers to add to a request to authenticate with these credentials."""
        return {}

    def updated(self, **kwargs: Any) -> Self:
        """Return a copy of these credentials with the specified fields changed."""
        constructor_args = self.model_dump()
        constructor_args.update(kwargs)
        return type(self)(**constructor_args)

    def get_password(
        self, getpass: Optional[GetpassCallback] = None, *, host: Optional[str] = None
    ) -> str:
        """Retrieve the password from this store, if there is one.

        :param getpass: If there is no password, call this function to get one.
        :param host: The hostname the password will be used for. Only needed if getpass
            is used.
        """
        if hasattr(self, "password") and getattr(self, "password") is not None:
            return getattr(self, "password")

        if getpass is not None:
            username = getattr(self, "username") if hasattr(self, "username") else ""
            return getpass(username=username, host=host)

        msg = "No password is available."
        raise err.InsufficientCredentialsError(msg)


class LoginCredentials(CredentialsBase):
    """Credentials used to log in with username/password.

    The password may or may not be present, as it may not be saved when the
    credentials are saved to disk.
    """

    type: Literal["login"] = Field(default="login", repr=False)
    username: str
    password: Optional[str] = Field(default=None, repr=False)


class LoginSession(CredentialsBase):
    """A username/password login with an associated session.

    The password may or may not be present, as it may not be saved when the
    credentials are saved to disk.
    """

    type: Literal["login-session"] = Field(default="login-session", repr=False)
    session_token: str = Field(..., repr=False)
    refresh_token: str = Field(..., repr=False)
    username: str
    password: Optional[str] = Field(default=None, repr=False)

    def auth_headers(self) -> Dict[str, str]:
        """Return headers to add to a request to authenticate with these credentials."""
        return {"X-Auth-token": self.session_token}


class ApiKey(CredentialsBase):
    """Credentials for API-key authentication."""

    type: Literal["api-key"] = Field(default="api-key", repr=False)
    key: str = Field(..., repr=False)

    @property
    def id(self) -> str:
        """Return this API key's id."""
        return sha256(self.key.encode()).digest().hex()

    def __repr_args__(self) -> List[Any]:
        return [*super().__repr_args__(), ("id", self.id)]

    def auth_headers(self) -> Dict[str, str]:
        """Return headers to add to a request to authenticate with these credentials."""
        return {"X-Api-key": self.key}

#: A set of credentials used to connect to the Kodiak. See
#: :py:class:`.CredentialsBase` for properties common to credentials.
Credentials: TypeAlias = Union[LoginCredentials, LoginSession, ApiKey]


class StoreMode(enum.Enum):
    """Setting that determines how a :py:class:`CredentialsManager` stores credentials."""

    #: Never save credentials, only use pre-existing credentials
    READ_ONLY = enum.auto()
    #: Only save credentials that are an updated version of the existing authentication
    #: method (for example, refeshing the timeout on a login session).
    REFRESH_ONLY = enum.auto()
    #: Always save credentials.
    STORE = enum.auto()


class CredentialsManager:
    """A store that handles credentials for multiple Kodiaks.

    This default implementation just stores the credentials in program memory, but
    subclasses can implement persistent storage. For example,
    :py:class:`.FileBackedCredentialsManager` and :py:class:`.CliCredentialsManager` store
    credentials in a file.

    :param credentials: A mapping of serial numbers to credentials for the credentials
        manager to use.
    :param getpass: A callback to use to prompt the user for a password if one isn't
        available.
    :param store_mode: Controls when this credentials manager will save passwords to its
        backing media.
    """

    def __init__(
        self,
        credentials: Optional[Dict[str, Credentials]] = None,
        getpass: Optional[GetpassCallback] = None,
        store_mode: StoreMode = StoreMode.STORE,
    ):
        if credentials is None:
            credentials = {}
        self._credentials = credentials
        self.getpass = getpass
        self.store_mode = store_mode

    def set(
        self,
        serial: str,
        credentials: Credentials,
        store_mode: Optional[StoreMode] = None,
    ) -> bool:
        """Set credentials for a given serial number.

        :param serial: The serial number of the Kodiak.
        :param credentials: The credentials to set.
        :param store_mode: Optionally override the default store mode.
        """
        if store_mode is None:
            store_mode = self.store_mode
        match store_mode:
            case StoreMode.READ_ONLY:
                pass

            case StoreMode.REFRESH_ONLY:
                existing = self._credentials.get(serial)
                if (
                    isinstance(existing, LoginSession)
                    and isinstance(credentials, LoginSession)
                    and existing.username == credentials.username
                ):
                    self._credentials[serial] = credentials
                    return True

            case StoreMode.STORE:
                self._credentials[serial] = credentials
                return True

        return False

    def delete(self, serial: str, store_mode: Optional[StoreMode] = None):
        """Delete credentials for a given serial number.

        :param serial: The serial number of the Kodiak.
        :param store_mode: Optionally override the default store mode.
        """
        if store_mode is None:
            store_mode = self.store_mode

        if store_mode == StoreMode.STORE and serial in self._credentials:
            del self._credentials[serial]

    def get(self, serial: str) -> Optional[Credentials]:
        """Retrieve stored credentials for a Kodiak if there are any.

        :param serial: The serial number of the Kodiak.
        """
        try:
            return self._credentials[serial]
        except KeyError:
            return None

    def get_store(self, serial: str) -> CredentialsStore:
        """Get the :py:class:`.CredentialsStore` for a Kodiak by serial number."""
        return CredentialsStore(self, serial, self.getpass)


class CredentialsStore:
    """Access credentials for a single Kodiak through :py:class:`CredentialsManager`."""

    def __init__(
        self,
        credentials: CredentialsManager,
        serial: str,
        getpass: Optional[GetpassCallback] = None,
    ):
        """Create a new CredentialsStore."""
        self._manager = credentials
        self._serial = serial
        self.getpass = getpass

        # If store_mode is not STORE, then sometimes self._manager won't store
        # credentials when we call `set()`. When that happens, we'll start keeping track
        # of the credentials in this object, so that `get()` still returns the last set
        # value.
        self._cached: Optional[Credentials] = None

    def set(
        self, credentials: Credentials, store_mode: Optional[StoreMode] = None
    ) -> bool:
        """Store the given credentials.

        :param credentials: The credentials to set.
        :param store_mode: Optionally override the default store mode.
        """
        stored = self._manager.set(self._serial, credentials, store_mode)
        if stored is False:
            self._cached = credentials
        else:
            self._cached = None
        return stored

    def get(self) -> Optional[Credentials]:
        """Retrieve stored credentials."""
        if self._cached is None:
            self._cached = self._manager.get(self._serial)
        return self._cached

    def delete(self, store_mode: Optional[StoreMode] = None) -> None:
        """Discard stored credentials.

        :param store_mode: Optionally override the default store mode.
        """
        self._manager.delete(self._serial, store_mode)
        self._cached = None

    def get_password(
        self, getpass: Optional[GetpassCallback] = None, *, host: Optional[str] = None
    ) -> str:
        """Retrieve the password from this store, if there is one.

        :param getpass: If there is no password, call this function to get one.
        :param host: The hostname the password will be used for. Only needed if getpass
            is used.
        """
        if getpass is None:
            getpass = self.getpass

        creds = self.get()
        if creds is not None:
            return creds.get_password(getpass, host=host)
        if getpass is not None:
            return getpass(username=None, host=host)

        msg = "No password is available."
        raise err.InsufficientCredentialsError(msg)


class _FileModel(BaseModel):
    version: Literal[1]
    credentials: Dict[str, Credentials]


class FileBackedCredentialsManager(CredentialsManager):
    """A credentials manager that keeps credentials on the File system."""

    def __init__(
        self,
        path: Path,
        save_password: Optional[bool] = None,
        getpass: Optional[GetpassCallback] = None,
        store_mode: StoreMode = StoreMode.STORE,
    ):
        """Create a new FileBackedCredentialsStore.

        :param path: Path to the file to use.
        :param save_password: If set to True, the password will be saved to the file as
            well. If set to False, the password will never be saved. If set to None
            (default), then passwords will be saved only if there was a password present
            when the credentials were first loaded.

            .. warning::

                If this argument is set to True, that means your password will be saved
                on disk in plain text.
        """
        super().__init__(getpass=getpass, store_mode=store_mode)
        self.path = path
        self.save_password = save_password
        self._save_each_password: Dict[str, bool] = {}
        self.reload()

    def set(
        self,
        serial: str,
        credentials: Credentials,
        store_mode: Optional[StoreMode] = None,
    ) -> bool:
        stored = super().set(serial, credentials, store_mode)
        if self.save_password is True:
            self._save_each_password[serial] = True
        self.save()
        return stored

    def delete(self, serial: str, store_mode: Optional[StoreMode] = None) -> None:
        super().delete(serial)
        self._save_each_password.pop(serial, None)
        self.save()

    def save(self) -> None:
        """Save the active credentials to the backing file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "credentials": {
                        s: c.model_dump(
                            exclude=self._exclude_fields(s), exclude_none=True
                        )
                        for s, c in self._credentials.items()
                    },
                },
                indent=2,
            )
        )

    def _exclude_fields(self, serial: str) -> Set[str]:
        if self._save_each_password.get(serial):
            return set()
        else:
            return {"password"}

    def reload(self) -> None:
        """Load all active credentials from the backing file."""
        try:
            file = _FileModel.model_validate_json(self.path.read_text())
            self._credentials = file.credentials

            if self.save_password is None:
                for serial, cred in self._credentials.items():
                    try:
                        cred.get_password()
                        self._save_each_password[serial] = True
                    except err.InsufficientCredentialsError:
                        pass

        except FileNotFoundError:
            self._credentials = {}
        except ValidationError as e:
            msg = f"Could not parse the credentials file at {self.path}."
            raise ValueError(msg) from e
