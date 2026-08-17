from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import cached_property

from serialtek.util.json import JsonBacked


class License(JsonBacked, init=False):
    issue_date: datetime
    last_updated: datetime | None
    expiry: datetime | None
    serial_number: str
    name: str | None

    @cached_property
    def features(self) -> list[LicenseFeature]:
        names = self.raw_data.get("feature_names", {})
        return [
            LicenseFeature(
                name=names.get(key, key),
                key=key,
                value=val,
            )
            for key, val in self.raw_data.get("features", {}).items()
        ]


@dataclass
class LicenseFeature:
    name: str
    key: str
    value: int
