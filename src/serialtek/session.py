from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)

import requests
from requests import Response, Session

from . import errors as err
from .credentials import (
    ApiKey,
    Credentials,
    CredentialsManager,
    CredentialsStore,
    GetpassCallback,
    LoginCredentials,
    LoginSession,
)
from .errors import InsufficientCredentialsError, RequestFailedError
from .types import override_return_type
from typing_extensions import Self

if TYPE_CHECKING:
    from requests.structures import CaseInsensitiveDict

log: logging.Logger = logging.getLogger(__name__)
requests_log: logging.Logger = logging.getLogger("serialtek_api_full")

_log_body = False


class ApiSession(Session):
    """A session for accessing the kodiak API.

    This class has methods similar to :py:class:`requests.Session` that can be called to
    access API endpoints. There are two differences:

        1. When specifying the URL for the request, the hostname portion of the URL is
           not included.
        2. The session will automatically add the necessary authentication headers to
           all requests (and refresh the session if needed).

    The most common way to use this class is not to create one on its own, but to access
    the one available on a logged in Kodiak as :py:attr:`.Kodiak.session` ::

        >>> kodiak = Kodiak()
        >>> kodiak.login(username=... password=...)
        >>> resp = kodiak.session.get("/kodiak/v1/status")
        >>> resp.status_code
        200
        >>> resp.json()
        {'device_alias': 'kodiak','hostname': ...

    To create an ApiSession on its own, without an associated :py:class:`.Kodiak`::

        >>> from serialtek import ApiSession
        >>> session = ApiSession("192.168.1.123")
        >>> session.login(username="my_username", password="12345")
        >>> resp = session.get("/kodiak/v1/status")

    :param host: The address of the Kodiak to connect to.
    :param login_url: The url of the login endpoint on the host.
    :param credentials: Credentials for this connection. This can be:

        * A :py:class:`.CredentialsManager`, in which case the session will retrieve
          a credentials store for the connected Kodiak based on its serial number.
        * A :py:class:`.CredentialsStore`, which will be used to retrieve
          credentials.
        * A :py:class:`.Credentials` object containing the actual credentials to
          use.
        * ``None``, in which case credentials will need to be supplied when calling
          the :py:meth:`login` method.

        For example, you can use the SerialTek CLI's credentials manager to retrieve the
        credentials last used with ``serialtek login``::

            from serialtek import ApiSession, CliConfig

            cli_creds = CliConfig().credentials_manager()
            session = ApiSession("192.168.1.123", cli_creds)

    An :py:class:`.ApiSession` supports the same http methods (:py:meth:`get`, :py:meth:`post`,
    etc.) as a :py:class:`requests.Session` object, with a couple convenience methods
    added. See the `requests module documentation
    <https://requests.readthedocs.io/en/latest/>`_ and :py:class:`.ApiResponse`.
    """

    #: The host to use for requests to the Kodiak for this session.
    host: str

    def __init__(
        self,
        host: str,
        credentials: Union[
            CredentialsManager,
            CredentialsStore,
            Credentials,
            None,
        ] = None,
        *,
        login_url: str = "/kodiak/v1/login",
    ):
        super().__init__()
        self.host = self._canonical_host(host)
        self.login_url = login_url
        self.verify: bool = False  # pyright: ignore[reportIncompatibleVariableOverride]

        self.credentials_store: CredentialsStore
        if isinstance(credentials, CredentialsManager):
            serial = self.host_info(host).serial
            self.credentials_store = credentials.get_store(serial)
        elif isinstance(credentials, CredentialsStore):
            self.credentials_store = credentials
        else:
            self.credentials_store = CredentialsManager().get_store("")
            if credentials:
                self.credentials_store.set(credentials)

        self.hooks["response"].append(self._log_response)

    @classmethod
    def _canonical_host(cls, host: str) -> str:
        if not re.match("^[^:/]*://", host):
            host = "https://" + host
        return host

    @classmethod
    def host_info(cls, host: str) -> KodiakInfo:
        """Retrieve info on a Kodiak without logging in."""
        host = cls._canonical_host(host)
        resp = requests.get(f"{host}/kodiak/v1/status", verify=False)
        ApiResponse.from_response(resp).validate()

        serial = resp.json()["serial_number"]
        alias = resp.json()["device_alias"]
        return KodiakInfo(host=host, serial=serial, alias=alias)

    @overload
    def login(self, *, username: str, password: Optional[str] = None) -> Self:
        ...

    @overload
    def login(self, *, api_key: str) -> Self:
        ...

    @overload
    def login(self, credentials: Optional[Credentials]) -> Self:
        ...

    @overload
    def login(self) -> Self:
        ...

    def login(
        self,
        credentials: Optional[Credentials] = None,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Self:
        """Perform authentication for this session.

        See :py:meth:`.Kodiak.login`, which has the same usage.
        """
        if credentials is None:
            if username is not None:
                credentials = LoginCredentials(username=username, password=password)
            elif api_key is not None:
                credentials = ApiKey(key=api_key)

        if credentials is None:
            credentials = self.credentials_store.get()

        getpass = self.credentials_store.getpass

        log.debug("Log in to %s%s with %r", self.host, self.login_url, credentials)
        if credentials is None:
            msg = "No credentials supplied"
            raise InsufficientCredentialsError(msg)
        elif isinstance(credentials, LoginCredentials):
            self._login_user_pass(credentials, getpass)
        elif isinstance(credentials, LoginSession):
            self._login_session(credentials, getpass)
        elif isinstance(
            credentials, ApiKey
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            self._login_api(credentials)
        else:
            msg = f"Invalid login credentials: {credentials!r}"
            raise RuntimeError(msg)

        return self

    def _login_user_pass(
        self, credentials: LoginCredentials, getpass: Optional[GetpassCallback] = None
    ):
        if getpass is None:
            getpass = self.credentials_store.getpass

        credentials = credentials.updated(
            password=credentials.get_password(getpass, host=self.host)
        )

        resp = self.request(
            "POST",
            self.login_url,
            json={
                "username": credentials.username,
                "password": credentials.password,
            },
            use_auth=False,
        )

        if resp.status_code == 401:
            msg = "Login failed (invalid credentials)"
            raise RequestFailedError(msg, resp)
        if resp.status_code != 200:
            msg = "Login Failed"
            raise RequestFailedError(msg, resp)

        resp_data = resp.json()
        session_token = resp_data.get("session_token")
        refresh_token = resp_data.get("refresh_token")

        self.credentials_store.set(
            LoginSession(
                username=credentials.username,
                password=credentials.password,
                session_token=session_token,
                refresh_token=refresh_token,
            )
        )

    def _login_session(
        self, credentials: LoginSession, getpass: Optional[GetpassCallback] = None
    ):
        # Just refresh the session
        self.credentials_store.set(credentials)
        self.refresh()

    def _login_api(self, credentials: ApiKey):
        # Verify that the api key is valid
        resp = self.request("get", f"{self.login_url}", use_creds=credentials)
        if resp.status_code == 401:
            msg = "Login failed (invalid credentials)"
            raise RequestFailedError(msg, resp)
        # Nothing to do to log in with an API key, but we can update the credential
        # store
        self.credentials_store.set(credentials)

    @staticmethod
    def _fmt_headers(headers: CaseInsensitiveDict[str], body: Union[str, bytes, None]):
        hdrs = "\n".join(f"{k}: {v}" for k, v in headers.items())
        if body is None:
            return hdrs

        if isinstance(body, bytes):
            body = body.decode()

        return hdrs + "\n\n" + body

    def _log_response(self, resp: Response, **kwargs: Any) -> None:
        # There's a log of processing going into this logging call, so skip it if we're
        # not actually logging.
        if _log_body and requests_log.isEnabledFor(logging.DEBUG):
            filter_reason = _log_response_filter(resp, **kwargs)
            text = f"<body suppressed: {filter_reason}>" if filter_reason else resp.text

            req = resp.request
            requests_log.debug(
                (
                    "\n---------------- request ----------------\n"
                    f"{req.method} {req.url}\n"
                    f"{self._fmt_headers(req.headers, req.body)}\n"
                    "---------------- response ----------------\n"
                    f"{resp.status_code} {resp.reason} {resp.url}\n"
                    f"{self._fmt_headers(resp.headers, text)}\n"
                    "------------------------------------------"
                ),
                stacklevel=7,
            )

    def refresh(self, *, retry_login: bool = False) -> None:
        """Refresh this session's authentication."""
        credentials = self.credentials_store.get()

        if isinstance(credentials, LoginSession):
            refresh_token = credentials.refresh_token

            resp = self.request(
                "POST",
                f"{self.login_url}/refresh",
                json={"token": refresh_token},
                use_auth=False,
            )

            if resp.status_code == 200:
                log.info("Successfully refreshed session.")
                resp_data = resp.json()
                session_token = resp_data.get("session_token")
                refresh_token = resp_data.get("refresh_token")
                self.credentials_store.set(
                    credentials.updated(
                        session_token=session_token, refresh_token=refresh_token
                    )
                )
            else:
                log.info("Session refresh failed")
                if retry_login:
                    log.info("Attempting to log in")
                    self.credentials_store.set(
                        LoginCredentials(
                            username=credentials.username,
                            password=credentials.password,
                        )
                    )
                    self.login()

    def request(  # type: ignore
        self,
        method: Union[str, bytes],
        url: Union[str, bytes],
        *,
        use_auth: bool = True,
        use_creds: Optional[Credentials] = None,
        retry_login: bool = True,
        **kwargs: Any,
    ) -> Response:
        """Make a request, refreshing authentication if needed."""
        url = self.host + url if isinstance(url, str) else self.host.encode() + url

        if not use_auth:
            return super().request(method, url, **kwargs)

        creds = use_creds if use_creds else self.credentials_store.get()
        headers = creds.auth_headers() if creds is not None else {}

        if "headers" in kwargs:
            headers.update(kwargs["headers"])
            del kwargs["headers"]

        resp = super().request(method, url, headers=headers, **kwargs)
        if resp.status_code == 401 and isinstance(creds, LoginSession):
            log.info(
                "Request failed with 401 when logged in with session, attempting"
                " refresh."
            )
            self.refresh(retry_login=retry_login)
            creds = self.credentials_store.get()
            if creds is not None:
                headers.update(creds.auth_headers())
            resp = super().request(method, f"{url}", headers=headers, **kwargs)

        return ApiResponse.from_response(resp)

    @override_return_type(Session.delete)
    def delete(self, *args: Any, **kwargs: Any) -> ApiResponse:
        """Perform a DELETE request to the given URL.

        The URL given shouldn't include the host component (it should start with
        "/kodiak/v1"). Otherwise, see `requests module
        documentation <https://requests.readthedocs.io/en/latest/>`_ for usage.
        """
        ...

    @override_return_type(Session.get)
    def get(self, *args: Any, **kwargs: Any) -> ApiResponse:
        """Perform a GET request to the given URL.

        The URL given shouldn't include the host component (it should start with
        "/kodiak/v1"). Otherwise, see `requests module
        documentation <https://requests.readthedocs.io/en/latest/>`_ for usage.
        """
        ...

    @override_return_type(Session.head)
    def head(self, *args: Any, **kwargs: Any) -> ApiResponse:
        """Perform a HEAD request to the given URL.

        The URL given shouldn't include the host component (it should start with
        "/kodiak/v1"). Otherwise, see `requests module
        documentation <https://requests.readthedocs.io/en/latest/>`_ for usage.
        """
        ...

    @override_return_type(Session.options)
    def options(self, *args: Any, **kwargs: Any) -> ApiResponse:
        """Perform a OPTIONS request to the given URL.

        The URL given shouldn't include the host component (it should start with
        "/kodiak/v1"). Otherwise, see `requests module
        documentation <https://requests.readthedocs.io/en/latest/>`_ for usage.
        """
        ...

    @override_return_type(Session.patch)
    def patch(self, *args: Any, **kwargs: Any) -> ApiResponse:
        """Perform a PATCH request to the given URL.

        The URL given shouldn't include the host component (it should start with
        "/kodiak/v1"). Otherwise, see `requests module
        documentation <https://requests.readthedocs.io/en/latest/>`_ for usage.
        """
        ...

    @override_return_type(Session.post)
    def post(self, *args: Any, **kwargs: Any) -> ApiResponse:
        """Perform a POST request to the given URL.

        The URL given shouldn't include the host component (it should start with
        "/kodiak/v1"). Otherwise, see `requests module
        documentation <https://requests.readthedocs.io/en/latest/>`_ for usage.
        """
        ...

    @override_return_type(Session.put)
    def put(self, *args: Any, **kwargs: Any) -> ApiResponse:
        """Perform a PUT request to the given URL.

        The URL given shouldn't include the host component (it should start with
        "/kodiak/v1"). Otherwise, see `requests module
        documentation <https://requests.readthedocs.io/en/latest/>`_ for usage.
        """
        ...


T = TypeVar("T")


@dataclass
class ApiResponse(requests.Response):
    """
    This is a subclass of :py:class:`requests.Response`, and should be used in the same
    way as that class. Two additional methods are provided for convenience.
    """

    @classmethod
    def from_response(cls, resp: requests.Response) -> Self:
        """Create a response from an ApiResponse.

        :meta private:
        """
        resp.__class__ = cls
        return cast("Self", resp)

    def __repr__(self) -> str:
        return super().__repr__()

    def validate(
        self,
        permission: Optional[str] = None,
        success_code: Union[int, List[int]] = 200,
    ) -> ApiResponse:
        """Validate the response code.

        This performs the same validaton that is used internally when making API
        requests.
        """
        exc = None
        try:
            # ruff: noqa: TRY301
            if permission is not None and self.status_code == 403:
                msg = f"{permission!r} permissions are required for this action."
                raise err.InsufficientPermissionsError(msg, self)
            if self.status_code == 409:
                data = self.json()
                if data["error"]["code"] == "LockError":
                    exc = err.LockError(self)
            elif self.status_code == 400:
                data = self.json()
                if data["error"]["code"] == "InvalidParameter":
                    exc = err.InvalidParameterError(
                        data["error"]["message"],
                        self,
                        data["error"]["data"]["parameter"],
                    )

        except Exception:
            log.exception("Exception parsing a response")
            # If anything goes wrong looking for a specific error, just go ahead
            # and check the status code.

        if exc is not None:
            raise exc

        if isinstance(success_code, int):
            valid = self.status_code == success_code
        else:
            valid = self.status_code in success_code

        if not valid:
            msg = "A request failed."
            raise err.RequestFailedError(msg, self)

        return self


@dataclass
class KodiakInfo:
    """Information that can be retrieved about a Kodiak without logging in.

    This information is retrieved with :py:meth:`.ApiSession.host_info` and can be used
    to determine how to connect.
    """

    host: str
    serial: str
    alias: str


def _log_response_filter(resp: Response, **kwargs: Any) -> Optional[str]:
    # If this request is streaming, then attempting to print the body here will
    # cause us to wait until the whole body is received--cancelling out the
    # benefit of streaming in the first place. This probably means we're
    # downloading a big file anyway, so don't include it in the log.
    if kwargs.get("stream"):
        return "streamed content excluded"
    return None
