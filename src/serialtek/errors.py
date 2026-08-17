from typing import Any

import requests


class RequestFailedError(Exception):
    """Generic error for when a request to the Kodiak fails."""

    def __init__(
        self, message: str, response: requests.Response, *args: object
    ) -> None:
        super().__init__(message, response.request.url, response, response.text, *args)
        self.message = message
        self.response = response


class InsufficientCredentialsError(ValueError):
    """Raised when authentication is attempted without the necessary credentials."""


class KodiakVersionError(Exception):
    """Raised when an action cannot be completed due to the version of the connected Kodiak."""


class InsufficientPermissionsError(RequestFailedError):
    """Raised when an action cannot be completed due to not having the right privileges."""


class InvalidParameterError(RequestFailedError):
    """Raised when a response indicates an invalid parameter."""

    def __init__(
        self, message: str, response: requests.Response, parameter: str, *args: object
    ) -> None:
        super().__init__(message, response, *args)
        self.parameter = parameter


class LockError(RequestFailedError):
    """Raised when an action cannot be taken because the lock isn't held."""

    def __init__(self, response: requests.Response):
        super().__init__(
            (
                "This action cannot be taken without the lock. Current lock owner:"
                f" {response.json()['error']['data']}"
            ),
            response,
        )
        self.data: Any = response.json()["error"]["data"]


class TaskFailedError(Exception):
    """Raised when a background task on the Kodiak fails."""


class TaskCancelledError(Exception):
    """Raised when a Kodiak task is cancelled while waiting for it to complete."""
