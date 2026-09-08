"""Polling orchestration with conservative retry behavior."""

from __future__ import annotations

import signal
import time
from collections.abc import Sequence
from typing import Protocol

from .database import HistoryDatabase
from .errors import AuthenticationRequired, ProviderNetworkError, ProviderResponseError
from .models import DeviceSnapshot, PollResult


class DeviceProvider(Protocol):
    def fetch_devices(
        self, fetched_at_ms: int | None = None
    ) -> list[DeviceSnapshot]: ...


class LocalCommunicationCollector(Protocol):
    def collect_once(self) -> int: ...


class Collector:
    def __init__(
        self,
        provider: DeviceProvider,
        database: HistoryDatabase,
        selected_device_keys: Sequence[str],
        retention_days: int | None = None,
    ) -> None:
        self.provider = provider
        self.database = database
        self.selected = set(selected_device_keys)
        self.retention_days = retention_days

    def collect_once(self) -> PollResult:
        started_at_ms = int(time.time() * 1000)
        try:
            if self.retention_days is not None:
                self.database.apply_retention(self.retention_days, started_at_ms)
            devices = self.provider.fetch_devices(fetched_at_ms=started_at_ms)
            new_points = 0
            selected_count = 0
            for device in devices:
                device_key = self.database.upsert_device(device, started_at_ms)
                if device_key not in self.selected:
                    continue
                selected_count += 1
                if device.location is not None and self.database.insert_point(
                    device.location
                ):
                    new_points += 1
            outcome = "success" if self.selected else "no_selection"
            result = PollResult(outcome, len(devices), selected_count, new_points)
            self.database.record_poll(
                started_at_ms,
                outcome,
                "ok" if self.selected else "select_devices_first",
                len(devices),
                selected_count,
                new_points,
            )
            return result
        except AuthenticationRequired:
            self.database.record_poll(
                started_at_ms, "auth_required", "reauthenticate", 0, 0, 0
            )
            raise
        except ProviderNetworkError:
            self.database.record_poll(
                started_at_ms, "network_error", "network", 0, 0, 0
            )
            raise
        except ProviderResponseError as exc:
            self.database.record_poll(
                started_at_ms, "provider_error", type(exc).__name__, 0, 0, 0
            )
            raise
        except Exception as exc:
            self.database.record_poll(
                started_at_ms, "internal_error", type(exc).__name__, 0, 0, 0
            )
            raise


def run_forever(
    collector: Collector | None,
    interval_seconds: int,
    communication_collector: LocalCommunicationCollector | None = None,
    communication_interval_seconds: float = 2.0,
) -> str:
    """Run until SIGTERM/SIGINT or until authentication needs user action."""
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    retry_seconds = interval_seconds
    location_active = collector is not None
    next_location = time.monotonic()
    next_communication = time.monotonic()
    if collector is not None:
        collector.database.set_next_poll(int(time.time() * 1000))
    while not stop:
        now = time.monotonic()
        if location_active and collector is not None and now >= next_location:
            try:
                collector.collect_once()
                retry_seconds = interval_seconds
            except AuthenticationRequired:
                if communication_collector is None:
                    collector.database.set_next_poll(None)
                    return "auth_required"
                location_active = False
            except (ProviderNetworkError, ProviderResponseError):
                retry_seconds = min(max(interval_seconds, retry_seconds * 2), 3600)
            except Exception:  # noqa: BLE001 - keep daemon alive without sensitive logs
                retry_seconds = min(max(interval_seconds, retry_seconds * 2), 3600)
            if location_active:
                next_location = time.monotonic() + retry_seconds
                collector.database.set_next_poll(
                    int(time.time() * 1000 + retry_seconds * 1000)
                )
            else:
                collector.database.set_next_poll(None)

        now = time.monotonic()
        if communication_collector is not None and now >= next_communication:
            try:
                communication_collector.collect_once()
            except Exception:  # noqa: BLE001 - permission status is stored safely
                next_communication = (
                    time.monotonic() + communication_interval_seconds
                )
            else:
                next_communication = (
                    time.monotonic() + communication_interval_seconds
                )

        if not location_active and communication_collector is None:
            break
        deadlines = []
        if location_active:
            deadlines.append(next_location)
        if communication_collector is not None:
            deadlines.append(next_communication)
        if deadlines:
            time.sleep(min(1.0, max(0.05, min(deadlines) - time.monotonic())))
    if collector is not None:
        collector.database.set_next_poll(None)
    return "stopped"
