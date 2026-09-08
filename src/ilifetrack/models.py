"""Provider-neutral data models."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LocationSnapshot:
    device_id: str
    name: str
    device_type: str
    source_at_ms: int
    fetched_at_ms: int
    latitude: float
    longitude: float
    horizontal_accuracy: float | None
    is_old: bool | None
    position_type: str | None
    battery_level: float | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class DeviceSnapshot:
    device_id: str
    name: str
    device_type: str
    battery_level: float | None
    location: LocationSnapshot | None


@dataclass(frozen=True)
class PollResult:
    outcome: str
    device_count: int
    selected_count: int
    new_points: int


@dataclass(frozen=True)
class CommunicationSnapshot:
    kind: str
    source_id: str
    source_row_id: int
    occurred_at_ms: int
    archived_at_ms: int
    direction: str
    participant: str | None
    participant_name: str | None
    body: str | None
    service: str | None
    duration_seconds: float | None
    answered: bool | None
    has_attachments: bool
