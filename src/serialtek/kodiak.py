from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Type,
    Union,
    cast,
    overload,
)

import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

from serialtek.license import License

from . import cli
from . import errors as err
from .capture import CaptureStatus, LiveCapture
from .credentials import (
    Credentials,
    CredentialsManager,
    GetpassCallback,
    StoreMode,
)
from .lock import Lock, LockStatus
from .path import KodiakPath
from .session import ApiSession
from .tasks import PollProgress, PolledTask, WaitParams
from .trace import Trace, TraceCloseOptions, TraceInfo
from .util import (
    DevicePath,
    validate_response,
)

if TYPE_CHECKING:
    from typing_extensions import Self

log: logging.Logger = logging.getLogger(__name__)

class Kodiak:
    """Class representing a connection to a Kodiak.

    After creating a :py:class:`~serialtek.Kodiak`, you must log in before you can use
    it::

        from serialtek import Kodiak
        kodiak = Kodiak("192.168.1.123")
        kodiak.login(username="user", password="12345")

    See :py:meth:`login` for more ways to log in to the Kodiak.

    :param host: The host address of the Kodiak, eg. ``"192.168.1.123"``. If the CLI
        extras are available, then if this is not specified then the active Kodiak
        from the CLI will be used. Otherwise, this is a required parameter.

    :param credentials: Credentials for this connection. This can be:

            * A :py:class:`.CredentialsManager`, in which case the session will retrieve a
              credentials store for the connected Kodiak based on its serial number.
            * A :py:class:`.CredentialsStore`, which will be used to retrieve credentials.
            * A :py:class:`.Credentials` object containing the actual credentials to use.

        by default, this will use the credentials stored in the CLI config (see above).
    """

    #: An :py:class:`~serialtek.session.ApiSession` that can be used to make
    #: authenticated requests directly to the Kodiak's API endpoints.
    session: ApiSession

    #: A Path type that can be used to interact with the file system on the Kodiak.
    #: See :py:class:`.KodiakPath` for details.
    Path: Type[KodiakPath]

    #: This Kodiak's serial number
    serial: str

    _lock: Optional[Lock]
    _capture: Optional[LiveCapture]

    def __init__(
        self,
        host: Optional[str] = None,
        *,
        credentials_manager: Optional[CredentialsManager] = None,
    ) -> None:
        try:
            cli_config = cli.CliConfig()
        except Exception:
            log.debug("Unable to open CLI config", exc_info=sys.exc_info())
            cli_config = None

        if host is None:
            active = cli_config.get_active_kodiak() if cli_config else None

            if active is None:
                msg = (
                    "No active host found. Specify the `host` argument (eg"
                    " `Kodiak(host)`) or connect to one using the cli: `serialtek"
                    " login <kodiak-ip> [--key...]`"
                )
                raise ValueError(msg)

            host, _ = active

        # Determine the Kodiak's serial number
        info = ApiSession.host_info(host)
        self.serial = info.serial

        # Create the authenticated session
        if credentials_manager is None:
            if cli_config:
                credentials_manager = cli.CliConfig().credentials_manager(
                    store_mode=StoreMode.REFRESH_ONLY
                )
            else:
                credentials_manager = CredentialsManager()
        credstore = credentials_manager.get_store(self.serial)

        self.session = ApiSession(info.host, credstore)

        self._lock = None
        self._capture = None
        self.Path = KodiakPath._make_bound(  # pyright: ignore[reportPrivateUsage]
            self
        )

    @overload
    def login(self, *, username: str, password: Optional[str] = None) -> Self:
        ...

    @overload
    def login(self, *, api_key: str) -> Self:
        ...

    @overload
    def login(self, credentials: Credentials) -> Self:
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
        """Log in to the Kodiak.

        This method can be used to log in, using a few different strategies to retrieve
        credentials.

        * **Log in using credentials from the Credentials Manager**::

            from serialtek import Kodiak
            kodiak = Kodiak("192.168.1.123")
            kodiak.login()

          When called without any arguments, credentials will be retrieved from the
          :py:class:`~.serialtek.Kodiak`'s
          :py:class:`~serialtek.credentials.CredentialsManager`. The default credentials
          manager is
          :py:meth:`CliConfig().credentials_manager(store_mode=StoreMode.REFRESH_ONLY)<serialtek.cli.CliConfig.credentials_manager>`
          That means that by default, calling :py:meth:`login` with no arguments will
          log into any Kodiak that has been logged into using the CLI, but credentials
          used in scripts will not be saved to disk.

        * **Log in using explicit credentials**::

            kodiak.login(username="user", password="123")
            kodiak.login(api_key="123abc")
        """
        self.session.login(  # pyright: ignore[reportCallIssue]
            credentials, username=username, password=password, api_key=api_key
        )
        return self

    # Device
    def lock(
        self,
        *,
        name: Optional[str] = None,
        force: bool = False,
        key: Optional[str] = None,
        strict_unlock: bool = False,
    ) -> Lock:
        """Lock the Kodiak.

        Actions that could cause conflict between multiple users (such as starting or
        stopping a capture) require that the Kodiak's lock be held. When a lock is
        taken using this function, the Kodiak will use the lock for those operations
        until the lock is released or forcefully taken by something else.

        The simplest way to use a lock is as a context::

            with kodiak.lock():
                # perform actions with the lock...
            # unlock() is called automatically when exiting the block.

        If you want to manage unlocking the lock manually::

            lock = kodiak.lock()
            # perform actions with the lock...
            lock.unlock()

        The :py:class:`~serialtek.lock.Lock` object that is returned provides information
        about the lock, and can be accessed when using the lock as a context as well::

            with kodiak.lock() as lock:
                print(lock.id)
                assert lock.held() is True, "Someone took the lock from us"

        :param name: Give a name to the lock. If not specified, the username of the
            request will be used.
        :param force: Take the lock even if it's already held by someone else.
        :param key: If the key for an already taken lock is known, it can be passed here
            to make this :py:class:`.Kodiak` use the existing lock rather than attempt
            to take a new one.
        :param strict_unlock: If unlocking the lock fails (because it is already
            unlocked or someone else has taken it), a
            :py:exc:`~serialtek.errors.LockError` will be raised if this is True.
        """
        self._lock = Lock.lock(
            "/kodiak/v1/device",
            self.session,
            name=name,
            force=force,
            key=key,
            strict_unlock=strict_unlock,
        )

        return self._lock

    def lock_status(self) -> LockStatus:
        """Get the current lock status."""
        resp = self.session.get("/kodiak/v1/device/lock").validate().json()
        return LockStatus(resp)

    def capture_status(self) -> CaptureStatus:
        """Get the status of capture on this Kodiak.

        :return: A list of the status of all available capture channels.
        """
        resp = self.session.get("/kodiak/v1/device/capture/status").validate().json()
        return CaptureStatus(resp)

    def start_capture(
        self,
        settings: Union[str, Path, Dict[str, Any], None] = None,
        *,
        strict_locking: bool = True,
        lock: Optional[Lock] = None,
    ) -> LiveCapture:
        """Start capture on the Kodiak.

        :param settings: The settings to use for this capture. This can be a path to a
            json file, or a dictionary representing the already-parsed file. Capture
            settings can be configured in the web UI and downloaded for use here. If
            ``None``, whatever the current live settings are on the Kodiak will be
            used.
        :param strict_locking: If True, make sure the lock is still held when performing
            operations on the capture. If the lock is released or forcefully taken
            further operations may be compromised, setting this to False is not
            recommended unless you have some other way to ensure exclusive access to the
            Kodiak.
        :param lock: Specify a lock to use for this operation, if ``None`` then the lock
            created when :py:meth:`.Kodiak.lock` was last called is used.
        """
        if isinstance(settings, str):
            settings_path = Path(settings)
            settings = json.loads(settings_path.read_text())
        elif isinstance(settings, Path):
            settings = json.loads(settings.read_text())
        elif settings is None:
            settings_resp = self.session.get("/kodiak/v1/device/capture/settings/live")
            validate_response(settings_resp)
            settings = settings_resp.json()
        assert isinstance(settings, dict)

        if lock:
            key = lock.key
        elif self._lock:
            lock = self._lock
            key = lock.key
        else:
            # If we don't have a key this is going to fail, but we'll let it do so
            # anyway because doing so also gives us information on who has the lock.
            key = ""

        settings["lock_key"] = key

        resp = self.session.post("/kodiak/v1/device/capture/start", json=settings)
        validate_response(resp, permission="ConfigureCapture")
        log.info("Started capture")
        # If we got here, either lock or self._lock was valid.
        assert lock is not None

        cap = LiveCapture(
            _lock=lock,
            _kodiak=self,
            _uri="/kodiak/v1/device/capture",
            strict_locking=strict_locking,
        )
        self._capture = cap
        return cap

    def stop_capture(self, lock: Optional[Lock] = None) -> None:
        """Stop capture on the Kodiak if it is running.

        This will stop any capture that may be running on the Kodiak. This is intended
        as a recovery operation or for when you need to stop a capture that was started
        by someone else: to stop a capture that was started with
        :py:meth:`start_capture`, it is recommended to use the
        :py:meth:`~.LiveCapture.stop` method on the returned :py:class:`.LiveCapture`
        object.

        :param lock: Specify a lock to use for this operation, if ``None`` then the lock
            created when :py:meth:`.Kodiak.lock` was last called is used.
        """
        cap = self.take_over_capture(lock=lock)
        if cap:
            cap.stop()

    def take_over_capture(
        self, *, strict_locking: bool = True, lock: Optional[Lock] = None
    ) -> Optional[LiveCapture]:
        """Take control of an existing capture.

        This will create a :py:class:`LiveCapture` object as though
        :py:meth:`start_capture` had been called, but based on the existing running
        capture instead of starting one.

        :param lock: Specify a lock to use for this operation, if ``None`` then the lock
            created when :py:meth:`.Kodiak.lock` was last called is used.
        :param strict_locking: If True, make sure the lock is still held when performing
            operations on the capture. If the lock is released or forcefully taken
            further operations may be compromised, setting this to False is not
            recommended unless you have some other way to ensure exclusive access to the
            Kodiak.

        :return: A handle for the running capture, or ``None`` if there isn't one
            running.
        """
        status = self.session.get("/kodiak/v1/status").validate().json()
        if not status["recording"]:
            return None

        if lock is None:
            if self._lock:
                lock = self._lock
            else:
                msg = "We don't hold the lock, so we can't take over the capture."
                raise ValueError(msg)

        cap = LiveCapture(
            _lock=lock,
            _kodiak=self,
            _uri="/kodiak/v1/device/capture",
            strict_locking=strict_locking,
        )
        self._capture = cap
        return cap

    @overload
    def firmware_activate(
        self,
        *,
        force: bool = ...,
        wait: Union[WaitParams, bool] = ...,
    ) -> Union[None, FirmwareProcessTask]:
        ...

    @overload
    def firmware_activate(
        self,
        *,
        file: DevicePath,
        force: bool = ...,
        wait: Union[WaitParams, bool] = ...,
    ) -> Union[None, FirmwareProcessTask]:
        ...

    @overload
    def firmware_activate(
        self,
        *,
        id: str,
        force: bool = ...,
        wait: Union[WaitParams, bool] = ...,
    ) -> Union[None, FirmwareProcessTask]:
        ...

    @overload
    def firmware_activate(
        self,
        *,
        version  : str,
        force: bool = ...,
        wait: Union[WaitParams, bool] = ...,
    ) -> Union[None, FirmwareProcessTask]:
        ...

    def firmware_activate(
        self,
        *,
        version: Optional[str] = None,
        file: Optional[DevicePath] = None,
        id: Optional[str] = None,
        force: bool = False,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[None, FirmwareProcessTask]:
        """Activate a firmware image.

        By default, this will activate the latest release. Specify one of ``file``,
        ``id``, or ``version`` to activate a specific firmware image.

        - Use ``version`` to activate a specific firmware version by looking up its ID
          in the firmware history::

            kodiak.firmware_activate(version="v3.55.3")

        - Use ``file`` to activate a firmware image file already present on the
          analyzer::

            kodiak.firmware_activate(file="/media/SATADrive0/my_firmware.tar.gz")

        - Use ``id`` to activate a specific firmware version by its unique ID::

            kodiak.firmware_activate(id="08e61e7e-75dc-40fb-888c-4170a87b01d9")

        :param version: The version string of a firmware version to activate.
        :param file: The path to a firmware image file on the analyzer to activate.
        :param id: The ID of a firmware version to activate.
        :param force: Whether to force the activation.
        :param wait: Whether to wait for the activation to complete before returning.
        """
        if sum(arg is not None for arg in (file, id, version)) > 1:
            msg = "Specify at most one of `file`, `id`, or `version`"
            raise TypeError(msg)

        if version is not None:
            history = self.session.get("/kodiak/v1/firmware/history").validate().json()
            entry = next((e for e in history if e.get("version") == version), None)
            if entry is None:
                msg = f"No firmware history entry found for version {version!r}"
                raise ValueError(msg)
            id = entry["id"]

        if file is not None:
            action, json = "activate_file", {"path": file}
            invalid_msg = "Invalid firmware file"
        elif id is not None:
            action, json = "activate_version", {"id": id}
            invalid_msg = "Invalid firmware version"
        else:
            action, json = "activate", None
            invalid_msg = "Invalid firmware image"

        start_update = self.session.post(
            f"/kodiak/v1/firmware/action/{action}?force={'true' if force else 'false'}",
            json=json,
        )
        if start_update.status_code == 400:
            raise err.RequestFailedError(invalid_msg, start_update)

        task = FirmwareProcessTask(self.session, "/kodiak/v1/firmware/status")

        return task.maybe_wait(wait)

    def firmware_upload(
        self,
        path: Path,
        *,
        force: bool = False,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[None, FirmwareProcessTask]:
        """Upload a firmware image.

        This will upload an image to the analyzer and activate it.

        :param upload: The firmware image to upload.
        :param callback: A callback function to track upload progress.
        """
        with open(path, "rb") as f:
            encoder = MultipartEncoder({"file": f})

            encoder_len: int = encoder.len

            def _callback(monitor: MultipartEncoderMonitor):
                progress = monitor.bytes_read / encoder_len
                if progress * 100 % 1 == 0:
                    log.info("Upload progress: %.2f%%", progress * 100)

            monitor = MultipartEncoderMonitor(encoder, _callback)
            resp = self.session.post(
                f"/kodiak/v1/firmware/action/upload?force={'true' if force else 'false'}",
                data=monitor,  # type: ignore
                headers={"Content-Type": "multipart/form-data"},
            ).validate(success_code=[200, 202])

        if resp.status_code == 400:
            msg = "Invalid firmware image"
            raise err.RequestFailedError(msg, resp)

        task = FirmwareProcessTask(self.session, "/kodiak/v1/firmware/status")

        return task.maybe_wait(wait)

    # Status
    def check(self) -> bool:
        """Check whether anything exists at this Kodiak's address."""
        try:
            resp = self.session.request("GET", "/kodiak/v1/", use_auth=False)
        except (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
        ):
            return False
        return resp.status_code == 200

    def check_credentials(self, *, retry_login: bool = True) -> bool:
        """Return whether this session is successfully authenticated or not."""
        # /users/self would probably make the most sense here, but it returns
        # 404 if you're using an API key. /keys returns 200 even if you're using
        # an API key with no permissions.
        resp = self.session.request("get", "/kodiak/v1/keys", retry_login=retry_login)
        if resp.status_code == 200:
            return True
        elif resp.status_code == 401:
            return False
        else:
            msg = "Failed to check credentials"
            raise err.RequestFailedError(msg, resp)

    # System/License
    def license(self) -> License:
        """Retrieve information on the system's current license."""
        resp = self.session.get("/kodiak/v1/system/license").validate().json()
        return License(resp)

    def add_license(
        self, path: Optional[Union[str, Path]] = None, key: Optional[str] = None
    ) -> None:
        """Add a license to this Kodiak.

        A license can come in one of two formats: A binary ``*.stlic`` file, or a
        base64-encoded key.

        To add a license from a file, pass the path to the file::

            kodiak.add_license("mylicense.stlic")

        To add a license key, pass the encoded key as the key argument::

            kodiak.add_license(key="U1RMSQAIAAABA...")
        """
        if (path is not None) == (key is not None):
            msg = "Specify either `path` or `key`, but not both"
            raise TypeError(msg)

        if path is not None:
            with open(path, "rb") as f:
                resp = self.session.post(
                    "/kodiak/v1/system/license/files", files={"file": f}
                )
        else:
            resp = self.session.post("/kodiak/v1/system/license/key", json={"key": key})

        if resp.status_code == 400:
            msg = "Invalid license"
            raise err.RequestFailedError(msg, resp)

        validate_response(resp, permission="ConfigureSystem")

    # System/Action
    def reboot(
        self,
        password: Optional[str] = None,
        getpass: Optional[GetpassCallback] = None,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[None, RebootTask]:
        """Reboot the system.

        :param password: The password to use. If no password is given, the credentials
            store will be checked for a password.
        :param getpass: If provided, this function will be called to get the password if
            no password is available.
        :param wait: Whether to wait for the reboot to complete before returning.
        """
        if password is None:
            password = self.session.credentials_store.get_password(
                getpass, host=self.session.host
            )

        resp = self.session.post(
            "/kodiak/v1/system/action",
            json={"password": password, "action": "SystemReboot"},
        )
        try:
            validate_response(resp, permission="ConfigureSystem")
        except err.InvalidParameterError as e:
            if e.parameter == "password":
                msg = "Invalid password"
                raise err.InvalidParameterError(msg, e.response, e.parameter) from e

        log.info("Successfully requested reboot.")

        task = RebootTask(self)
        return task.maybe_wait(wait)

    def get_open_traces(self) -> List[Trace]:
        """Get a list of all traces currently opened on the Kodiak.

        :return: A :py:class:`~serialtek.trace.Trace` for every open trace.
        """
        all_traces = self.session.get("/kodiak/v1/traces/open").validate().json()

        return [Trace(self.session, t["uri"], TraceInfo(t), None) for t in all_traces]

    def open_trace(
        self,
        path: DevicePath,
        *,
        wait_until_ready: Union[bool, WaitParams] = True,
        close_options: Optional[TraceCloseOptions] = None,
    ) -> Trace:
        """Open a trace.

        A trace can be used as a context to automatically handle opening and closing::

            with kodiak.open_trace("/media/NVMeDrive0/my_trace.sttrace") as trace:
                # Do something with trace...
            # trace is closed at the end of the block.

        Or to manually handle closing::

            trace = kodiak.open_trace("/media/NVMeDrive0/my_trace.sttrace")
            # Do something with trace...
            trace.close()

        :param path: The path to the trace to open.
        :param wait_until_ready: Whether to wait for the trace to be ready to use before
            returning, or a :py:class:`~serialtek.util.WaitParams` object to specify the
            wait parameters.
        :param close_options: If this trace is being used as a context manager, this
            argument can be used to specify the options used when closing the trace.

        :return: the requested :py:class:`~.trace.Trace`
        """
        path = str(path)

        resp = (
            self.session.post("/kodiak/v1/traces/open", json={"path": path})
            .validate()
            .json()
        )
        trace_info = TraceInfo(resp)
        trace_uri = trace_info.uri

        trace = Trace(self.session, trace_uri, trace_info, close_options)
        log.info("Opened trace %s", path)

        match wait_until_ready:
            case True:
                trace.wait_until_ready()
            case WaitParams() as wp:
                trace.wait_until_ready(wp)
            case False:
                pass

        return trace



class TraceService:
    """
    Class for opening traces through a direct connection to a trace service, instead of
    through a Kodiak.

    :meta private:
    """

    session: ApiSession

    def __init__(self):
        self.session = ApiSession("http://localhost:50000")

    def open_trace(
        self, path: DevicePath, *, wait_until_ready: Union[bool, WaitParams] = True
    ) -> Trace:
        """Open a trace.

        See :py:class:`.Kodiak.open_trace`
        """
        return Kodiak.open_trace(
            cast(Kodiak, self), path, wait_until_ready=wait_until_ready
        )


class RebootTask(PolledTask[None]):
    """A handle for an in progress reboot.

    :meta private:
    """

    #: How long to wait before checking whether the Kodiak has come back online, to
    #: give it a chance to actually go down first. Otherwise we might see it still up
    #: and think the reboot is already done.
    _settle_time: float = 15

    def __init__(self, kodiak: Kodiak):
        super().__init__("Wait for reboot to complete")

        self.kodiak: Kodiak = kodiak
        self._start_time = time.monotonic()

    def _poll(self) -> PollProgress:
        if time.monotonic() - self._start_time < self._settle_time:
            return False

        return self.kodiak.check()

    def _get_result(self) -> None:
        return None


class FirmwareProcessTask(PolledTask[None]):
    """A handle for an in progress Firmware task.

    :meta private:
    """

    def __init__(self, session: ApiSession, uri: str):
        super().__init__("Wait for Firmware processing to finish")

        self.session: ApiSession = session
        self.uri: str = uri
        self.stage: Literal["poll", "reboot", "post-reboot"] = "poll"
        self.saved_progress = 0

    def _poll(self) -> float:
        try:
            task = (
                self.session.get(self.uri)
                .validate().json()
            )
        except (
            err.RequestFailedError,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError
        ):
            task = None

        match self.stage:
            case "poll":
                if task is None:
                    self.stage = "reboot"
                    self.desc = "Wait for Firmware processing to finish (rebooting)"
                    return self.saved_progress

                if task["update"]["progress"] is None:
                    return 0
                elif task["update"]["running"] is False and task["update"]["success"] is False:
                    msg = "Firmware processing task failed"
                    raise RuntimeError(msg)
                else:
                    self.saved_progress = min(task["update"]["progress"], 99)
                    return self.saved_progress

            case "reboot":
                if task is None:
                    return self.saved_progress
                else:
                    self.stage = "post-reboot"
                    self.desc = "Wait for Firmware processing to finish (post boot)"
                    return self.saved_progress
            case "post-reboot":
                if task is None:
                    msg = "Firmware processing task failed"
                    raise RuntimeError(msg)

                if task["update"]["progress"] is None:
                    return 0
                elif task["update"]["running"] is False and task["update"]["success"] is False:
                    msg = "Firmware processing task failed"
                    raise RuntimeError(msg)
                elif task["update"]["running"] is False and task["update"]["success"] is True:
                    return 100
                else:
                    self.saved_progress = min(task["update"]["progress"], 100)
                    return self.saved_progress

    def _get_result(self):
        return None
