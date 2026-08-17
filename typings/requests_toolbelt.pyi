from typing import Any

class MultipartEncoder:
    def __init__(
        self, fields: Any, boundary: Any = None, encoding: str = "utf-8"
    ) -> None: ...
    @property
    def len(self) -> int: ...

class MultipartEncoderMonitor:
    bytes_read: int

    def __init__(self, encoder: MultipartEncoder, callback: Any = None) -> None: ...
