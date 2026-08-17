import logging
import os
from typing import Literal, Optional, Union

import requests

import rich
import rich.traceback
from rich.console import Console
from rich.logging import RichHandler

stderr_consle: Console = Console(stderr=True)


#: Root logger for most logging by the serialtek library
log: logging.Logger = logging.getLogger("serialtek")
#: Root logger for request URLs: All requests/responses (URL+status) will be logged to
#: this logger at the DEBUG level
url_log: logging.Logger = logging.getLogger("urllib3.connectionpool")
#: Root logger for request bodies. If enabled, the full body of all requests and
#: responses will be logged to this logger.
requests_log: logging.Logger = logging.getLogger("serialtek_api_full")
warnings_log: logging.Logger = logging.getLogger("py.warnings")


def configure_logging(
    level: Union[int, str],
    *,
    log_requests: Literal["url", "body", None] = None,
    handler: Optional[logging.Handler] = None,
    formatter: Optional[logging.Formatter] = None,
    capture_warnings: bool = True,
    use_rich: bool = True,
    rich_tracebacks: bool = True
) -> logging.Handler:
    """Convenience function to set up logging for this module at the given level.

    If `Rich <https://github.com/Textualize/rich>`_ is installed, it will be used for
    logging by default and Rich's traceback handler will also be enabled.

    At the ``DEBUG`` log level, the ``log_requests`` parameter can be used to log the
    URL or the full body of all requests made.

    :param level: The log level to use, eg. ``logging.INFO``. A string with the name of
        the level may also be used, ``"INFO"``.
    :param log_requests: If ``"url"``, the url and response code of all requests will be
        logged (at the DEBUG level). If ``"body"`` the full body and all headers for all
        requests to the Kodiak will be logged.

        .. warning::

            When using ``log_requests="body"``, *everything* sent to the Kodiak will
            be logged. This may include private information such as login passwords,
            session tokens, api keys, etc. Use with caution.
    :param handler: Specify a log handler to use.
    :param formatter: Specify a formatter to use (only used if ``handler`` isn't
        specified).
    :param capture_warnings: Whether to redirect python warnings to be logged as
        warnings.
    :param use_rich: Set to ``False`` to disable automatic Rich integration.
    :param rich_tracebacks: If ``use_rich`` is ``True``, set this to ``False`` to
        disable only the exception handling.

    :return: the handler used to configure logging.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper())
        assert isinstance(level, int)

    if use_rich:
        tb_suppress = [requests, rich]

        if handler is None:
            handler = RichHandler(
                show_time=level <= logging.DEBUG,
                show_path=level <= logging.INFO,
                console=stderr_consle,
                rich_tracebacks=True,
                tracebacks_show_locals=(
                    log_requests == "body" or os.environ.get("_STCLI_DEV") is not None
                ),
                tracebacks_suppress=tb_suppress,
            )

        if rich_tracebacks:
            rich.traceback.install(
                suppress=tb_suppress,
                show_locals=(
                    log_requests == "body" or os.environ.get("_STCLI_DEV") is not None
                ),
            )

        if formatter is None:
            formatter = logging.Formatter(fmt="%(message)s")

    else:
        if handler is None:
            handler = logging.StreamHandler()

        if formatter is None:
            formatter = logging.Formatter(
                "%(asctime)s|%(name)s[%(levelname)s]: %(message)s"
            )

    handler.setFormatter(formatter)
    handler.setLevel(level)

    log.addHandler(handler)
    log.setLevel(level)

    if capture_warnings:
        logging.captureWarnings(True)
        warnings_log.addHandler(handler)
        warnings_log.setLevel(level)

    if log_requests == "url":
        url_log.addHandler(handler)
        url_log.setLevel(level)

    elif log_requests == "body":
        enable_request_body_logging()
        requests_log.addHandler(handler)
        requests_log.setLevel(level)

    return handler


def enable_request_body_logging(enable: bool = True) -> None:
    """Enable logging of full request bodies.

    When this is enabled, the full body of all requests will be logged to the
    ``serialtek_api_full`` logger.

    .. warning::

        This will log `everything` sent over the connection, which may include secret
        information such as login passwords or API keys. Use with caution.
    """
    from . import session

    session._log_body = enable  # pyright: ignore[reportPrivateUsage]
    if enable:
        log.warning(
            "At this log level, the full contents of all communication with the"
            " Kodiak is logged. This may include information such as passwords and"
            " authentication keys."
        )
