"""Encrypted local history storage."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Self

from cryptography.exceptions import InvalidTag

from .crypto import CryptoBox
from .models import CommunicationSnapshot, DeviceSnapshot, LocationSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_key TEXT PRIMARY KEY,
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL,
    is_available INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_key TEXT NOT NULL,
    source_at_ms INTEGER NOT NULL,
    fetched_at_ms INTEGER NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS points_device_time
    ON points(device_key, source_at_ms);
CREATE TABLE IF NOT EXISTS poll_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_ms INTEGER NOT NULL,
    finished_at_ms INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL,
    device_count INTEGER NOT NULL,
    selected_count INTEGER NOT NULL,
    new_points INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS poll_runs_started
    ON poll_runs(started_at_ms);
CREATE TABLE IF NOT EXISTS movement_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_ms INTEGER NOT NULL,
    finished_at_ms INTEGER
);
CREATE TABLE IF NOT EXISTS communications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    record_key TEXT NOT NULL UNIQUE,
    occurred_at_ms INTEGER NOT NULL,
    archived_at_ms INTEGER NOT NULL,
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS communications_kind_time
    ON communications(kind, occurred_at_ms);
CREATE TABLE IF NOT EXISTS communication_state (
    source TEXT PRIMARY KEY,
    last_row_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS communication_status (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    scanned_at_ms INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL,
    new_records INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS collector_status (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    next_poll_ms INTEGER,
    updated_at_ms INTEGER NOT NULL
);
"""


class HistoryDatabase:
    def __init__(self, database_path: Path, crypto: CryptoBox):
        database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = database_path
        self.crypto = crypto
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate_schema()
        # DELETE mode lets the signed GUI open a truly read-only connection without
        # needing write access to a shared-memory sidecar. There is only one writer.
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA secure_delete=ON")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.commit()
        database_path.chmod(0o600)

    def _migrate_schema(self) -> None:
        device_columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(devices)")
        }
        if "is_available" not in device_columns:
            self.connection.execute(
                "ALTER TABLE devices ADD COLUMN is_available INTEGER NOT NULL DEFAULT 1"
            )
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_backup(
        self, backup_directory: Path, reason: str, keep: int = 20
    ) -> Path:
        if not reason or any(character not in "abcdefghijklmnopqrstuvwxyz-" for character in reason):
            raise ValueError("Invalid backup reason")
        backup_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_directory.chmod(0o700)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = backup_directory / f"{timestamp}-{reason}.sqlite3"
        with sqlite3.connect(destination) as backup_connection:
            self.connection.backup(backup_connection)
        destination.chmod(0o600)
        backups = sorted(
            backup_directory.glob("*.sqlite3"),
            key=lambda candidate: candidate.stat().st_mtime_ns,
            reverse=True,
        )
        for expired in backups[max(1, keep) :]:
            expired.unlink()
        return destination

    def restore_backup(self, backup_path: Path) -> None:
        if not backup_path.is_file():
            raise ValueError("Backup file does not exist")
        with sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True) as source:
            integrity = source.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise ValueError("Backup integrity check failed")
            source.backup(self.connection)
        self.connection.executescript(SCHEMA)
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA secure_delete=ON")
        self.connection.commit()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def device_key(self, device_id: str) -> str:
        return self.crypto.keyed_id("device", device_id)

    def upsert_device(self, device: DeviceSnapshot, seen_at_ms: int) -> str:
        device_key = self.device_key(device.device_id)
        payload = {
            "device_id": device.device_id,
            "name": device.name,
            "device_type": device.device_type,
            "battery_level": device.battery_level,
        }
        aad = f"device:{device_key}".encode("ascii")
        nonce, ciphertext = self.crypto.encrypt_json(payload, aad)
        self.connection.execute(
            """
            INSERT INTO devices(
                device_key, nonce, ciphertext, first_seen_ms, last_seen_ms, is_available
            )
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(device_key) DO UPDATE SET
                nonce=excluded.nonce,
                ciphertext=excluded.ciphertext,
                last_seen_ms=excluded.last_seen_ms,
                is_available=1
            """,
            (device_key, nonce, ciphertext, seen_at_ms, seen_at_ms),
        )
        return device_key

    def sync_devices(
        self, devices: Iterable[DeviceSnapshot], seen_at_ms: int
    ) -> list[str]:
        """Synchronize the current Find My list without deleting archived history."""
        self.connection.execute("UPDATE devices SET is_available=0")
        available_keys = [self.upsert_device(device, seen_at_ms) for device in devices]
        self.connection.commit()
        return available_keys

    def insert_point(self, snapshot: LocationSnapshot) -> bool:
        self._validate_location(snapshot)
        device_key = self.device_key(snapshot.device_id)
        fingerprint_input = json.dumps(
            {
                "device_id": snapshot.device_id,
                "source_at_ms": snapshot.source_at_ms,
                "latitude": snapshot.latitude,
                "longitude": snapshot.longitude,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        fingerprint = self.crypto.keyed_id("point", fingerprint_input, length=64)
        payload = {
            "latitude": snapshot.latitude,
            "longitude": snapshot.longitude,
            "horizontal_accuracy": snapshot.horizontal_accuracy,
            "is_old": snapshot.is_old,
            "position_type": snapshot.position_type,
            "battery_level": snapshot.battery_level,
            "raw": snapshot.raw,
        }
        aad = f"point:{device_key}:{snapshot.source_at_ms}".encode("ascii")
        nonce, ciphertext = self.crypto.encrypt_json(payload, aad)
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO points(
                device_key, source_at_ms, fetched_at_ms, fingerprint, nonce, ciphertext
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                device_key,
                snapshot.source_at_ms,
                snapshot.fetched_at_ms,
                fingerprint,
                nonce,
                ciphertext,
            ),
        )
        return cursor.rowcount == 1

    def insert_communication(self, snapshot: CommunicationSnapshot) -> bool:
        if snapshot.kind not in {"message", "call"}:
            raise ValueError("Invalid communication kind")
        if snapshot.direction not in {"incoming", "outgoing"}:
            raise ValueError("Invalid communication direction")
        if snapshot.occurred_at_ms <= 0 or snapshot.archived_at_ms <= 0:
            raise ValueError("Invalid communication timestamp")
        record_key = self.crypto.keyed_id(
            "communication", f"{snapshot.kind}:{snapshot.source_id}", length=64
        )
        payload = {
            "source_id": snapshot.source_id,
            "source_row_id": snapshot.source_row_id,
            "direction": snapshot.direction,
            "participant": snapshot.participant,
            "participant_name": snapshot.participant_name,
            "body": snapshot.body,
            "service": snapshot.service,
            "duration_seconds": snapshot.duration_seconds,
            "answered": snapshot.answered,
            "has_attachments": snapshot.has_attachments,
        }
        aad = f"communication:{record_key}:{snapshot.occurred_at_ms}".encode("ascii")
        nonce, ciphertext = self.crypto.encrypt_json(payload, aad)
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO communications(
                kind, record_key, occurred_at_ms, archived_at_ms, nonce, ciphertext
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.kind,
                record_key,
                snapshot.occurred_at_ms,
                snapshot.archived_at_ms,
                nonce,
                ciphertext,
            ),
        )
        return cursor.rowcount == 1

    def communication_cursor(self, source: str) -> int | None:
        row = self.connection.execute(
            "SELECT last_row_id FROM communication_state WHERE source=?", (source,)
        ).fetchone()
        return int(row["last_row_id"]) if row else None

    def set_communication_cursor(self, source: str, last_row_id: int) -> None:
        if source not in {"messages", "calls"} or last_row_id < 0:
            raise ValueError("Invalid communication cursor")
        self.connection.execute(
            """
            INSERT INTO communication_state(source, last_row_id) VALUES (?, ?)
            ON CONFLICT(source) DO UPDATE SET last_row_id=excluded.last_row_id
            """,
            (source, last_row_id),
        )

    def record_communication_scan(
        self, outcome: str, detail: str, new_records: int, scanned_at_ms: int | None = None
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO communication_status(id, scanned_at_ms, outcome, detail, new_records)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                scanned_at_ms=excluded.scanned_at_ms,
                outcome=excluded.outcome,
                detail=excluded.detail,
                new_records=excluded.new_records
            """,
            (scanned_at_ms or int(time.time() * 1000), outcome, detail[:120], new_records),
        )
        self.connection.commit()

    def clear_communications(self, kind: str | None = None) -> int:
        if kind is not None and kind not in {"message", "call"}:
            raise ValueError("Invalid communication kind")
        if kind is None:
            count = int(
                self.connection.execute("SELECT COUNT(*) FROM communications").fetchone()[0]
            )
            with self.connection:
                self.connection.execute("DELETE FROM communications")
                self.connection.execute(
                    "DELETE FROM sqlite_sequence WHERE name='communications'"
                )
        else:
            count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM communications WHERE kind=?", (kind,)
                ).fetchone()[0]
            )
            with self.connection:
                self.connection.execute("DELETE FROM communications WHERE kind=?", (kind,))
        if count:
            self.connection.execute("VACUUM")
        return count

    @staticmethod
    def _validate_location(snapshot: LocationSnapshot) -> None:
        if not math.isfinite(snapshot.latitude) or not -90 <= snapshot.latitude <= 90:
            raise ValueError("Invalid latitude")
        if (
            not math.isfinite(snapshot.longitude)
            or not -180 <= snapshot.longitude <= 180
        ):
            raise ValueError("Invalid longitude")
        if snapshot.source_at_ms <= 0 or snapshot.fetched_at_ms <= 0:
            raise ValueError("Invalid timestamp")

    def record_poll(
        self,
        started_at_ms: int,
        outcome: str,
        detail: str,
        device_count: int,
        selected_count: int,
        new_points: int,
        finished_at_ms: int | None = None,
    ) -> None:
        safe_detail = detail[:120]
        self.connection.execute(
            """
            INSERT INTO poll_runs(
                started_at_ms, finished_at_ms, outcome, detail,
                device_count, selected_count, new_points
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at_ms,
                finished_at_ms or int(time.time() * 1000),
                outcome,
                safe_detail,
                device_count,
                selected_count,
                new_points,
            ),
        )
        self.connection.commit()

    def set_next_poll(self, next_poll_ms: int | None) -> None:
        self.connection.execute(
            """
            INSERT INTO collector_status(id, next_poll_ms, updated_at_ms)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                next_poll_ms=excluded.next_poll_ms,
                updated_at_ms=excluded.updated_at_ms
            """,
            (next_poll_ms, int(time.time() * 1000)),
        )
        self.connection.commit()

    def list_devices(self) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute(
            """
            SELECT device_key, nonce, ciphertext, last_seen_ms, is_available
            FROM devices ORDER BY device_key
            """
        ):
            aad = f"device:{row['device_key']}".encode("ascii")
            payload = self.crypto.decrypt_json(row["nonce"], row["ciphertext"], aad)
            payload.update(
                device_key=row["device_key"],
                last_seen_ms=row["last_seen_ms"],
                is_available=bool(row["is_available"]),
            )
            result.append(payload)
        return result

    def readable_device_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for row in self.connection.execute(
            "SELECT device_key, nonce, ciphertext FROM devices"
        ):
            try:
                payload = self.crypto.decrypt_json(
                    row["nonce"],
                    row["ciphertext"],
                    f"device:{row['device_key']}".encode("ascii"),
                )
            except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError, TypeError):
                continue
            name = payload.get("name")
            if isinstance(name, str) and name:
                names[str(row["device_key"])] = name
        return names

    def clear_history(
        self,
        device_key: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict[str, int]:
        """Delete matching positions while preserving devices and configuration."""
        if start_ms is not None and end_ms is not None and start_ms > end_ms:
            raise ValueError("Start time cannot be later than end time")
        clauses: list[str] = []
        values: list[str | int] = []
        if device_key is not None:
            clauses.append("device_key = ?")
            values.append(device_key)
        if start_ms is not None:
            clauses.append("source_at_ms >= ?")
            values.append(start_ms)
        if end_ms is not None:
            clauses.append("source_at_ms <= ?")
            values.append(end_ms)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        point_count = int(
            self.connection.execute(
                f"SELECT COUNT(*) FROM points{where}",
                values,
            ).fetchone()[0]
        )
        poll_count = int(
            self.connection.execute("SELECT COUNT(*) FROM poll_runs").fetchone()[0]
        )
        movement_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM movement_sessions"
            ).fetchone()[0]
        )
        with self.connection:
            self.connection.execute(f"DELETE FROM points{where}", values)
            if not clauses:
                self.connection.execute("DELETE FROM poll_runs")
                self.connection.execute("DELETE FROM movement_sessions")
                self.connection.execute(
                    "DELETE FROM sqlite_sequence "
                    "WHERE name IN ('points', 'poll_runs', 'movement_sessions')"
                )
        if point_count or (not clauses and (poll_count or movement_count)):
            self.connection.execute("VACUUM")
        return {
            "points": point_count,
            "poll_runs": poll_count if not clauses else 0,
            "movement_sessions": movement_count if not clauses else 0,
        }

    def apply_retention(self, retention_days: int, now_ms: int | None = None) -> int:
        if retention_days < 1:
            raise ValueError("Retention days must be positive")
        cutoff = (now_ms or int(time.time() * 1000)) - retention_days * 86_400_000
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM points WHERE source_at_ms < ?", (cutoff,)
            )
            self.connection.execute(
                "DELETE FROM poll_runs WHERE started_at_ms < ?", (cutoff,)
            )
            self.connection.execute(
                "DELETE FROM movement_sessions "
                "WHERE COALESCE(finished_at_ms, started_at_ms) < ?",
                (cutoff,),
            )
        return cursor.rowcount

    def dashboard(self) -> dict[str, Any]:
        point_row = self.connection.execute(
            """
            SELECT COUNT(*) AS total, MIN(source_at_ms) AS first_ms,
                   MAX(source_at_ms) AS last_ms
            FROM points
            """
        ).fetchone()
        last_poll = self.connection.execute(
            """
            SELECT started_at_ms, finished_at_ms, outcome, detail
            FROM poll_runs ORDER BY started_at_ms DESC LIMIT 1
            """
        ).fetchone()
        last_success = self.connection.execute(
            """
            SELECT finished_at_ms FROM poll_runs
            WHERE outcome = 'success' ORDER BY started_at_ms DESC LIMIT 1
            """
        ).fetchone()
        last_error = self.connection.execute(
            """
            SELECT finished_at_ms, outcome, detail
            FROM poll_runs
            WHERE outcome NOT IN ('success', 'no_selection')
            ORDER BY started_at_ms DESC LIMIT 1
            """
        ).fetchone()
        latest_point = self.connection.execute(
            """
            SELECT source_at_ms, fetched_at_ms
            FROM points ORDER BY source_at_ms DESC, id DESC LIMIT 1
            """
        ).fetchone()
        collector_status = self.connection.execute(
            "SELECT next_poll_ms FROM collector_status WHERE id=1"
        ).fetchone()
        device_statuses: list[dict[str, Any]] = []
        seen_device_keys: set[str] = set()
        for row in self.connection.execute(
            """
            SELECT device_key, source_at_ms, fetched_at_ms
            FROM points ORDER BY device_key, source_at_ms DESC, id DESC
            """
        ):
            device_key = str(row["device_key"])
            if device_key in seen_device_keys:
                continue
            seen_device_keys.add(device_key)
            device_statuses.append(
                {
                    "device_key": device_key,
                    "last_location_ms": row["source_at_ms"],
                    "last_fetched_ms": row["fetched_at_ms"],
                    "location_lag_seconds": max(
                        0, (row["fetched_at_ms"] - row["source_at_ms"]) // 1000
                    ),
                }
            )
        device_names = self.readable_device_names()
        for status in device_statuses:
            status["device_name"] = device_names.get(status["device_key"])
        communication_row = self.connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN kind='message' THEN 1 ELSE 0 END) AS messages,
                   SUM(CASE WHEN kind='call' THEN 1 ELSE 0 END) AS calls,
                   MAX(archived_at_ms) AS last_archived_ms
            FROM communications
            """
        ).fetchone()
        last_communication_scan = self.connection.execute(
            """
            SELECT scanned_at_ms, outcome, detail FROM communication_status WHERE id=1
            """
        ).fetchone()
        return {
            "total_points": int(point_row["total"]),
            "history_start_ms": point_row["first_ms"],
            "history_end_ms": point_row["last_ms"],
            "last_poll_started_ms": last_poll["started_at_ms"] if last_poll else None,
            "last_poll_finished_ms": last_poll["finished_at_ms"] if last_poll else None,
            "last_poll_outcome": last_poll["outcome"] if last_poll else None,
            "last_poll_detail": last_poll["detail"] if last_poll else None,
            "last_success_ms": last_success["finished_at_ms"] if last_success else None,
            "last_error_ms": last_error["finished_at_ms"] if last_error else None,
            "last_error_outcome": last_error["outcome"] if last_error else None,
            "last_error_detail": last_error["detail"] if last_error else None,
            "next_expected_poll_ms": (
                collector_status["next_poll_ms"] if collector_status else None
            ),
            "latest_location_lag_seconds": (
                max(0, (latest_point["fetched_at_ms"] - latest_point["source_at_ms"]) // 1000)
                if latest_point
                else None
            ),
            "device_statuses": device_statuses,
            "total_communications": int(communication_row["total"]),
            "message_count": int(communication_row["messages"] or 0),
            "call_count": int(communication_row["calls"] or 0),
            "last_communication_archived_ms": communication_row["last_archived_ms"],
            "last_communication_scan_ms": (
                last_communication_scan["scanned_at_ms"]
                if last_communication_scan
                else None
            ),
            "last_communication_outcome": (
                last_communication_scan["outcome"] if last_communication_scan else None
            ),
        }

    def start_movement(self, started_at_ms: int | None = None) -> int:
        if self.connection.execute(
            "SELECT 1 FROM movement_sessions WHERE finished_at_ms IS NULL"
        ).fetchone():
            raise ValueError("A movement session is already active")
        cursor = self.connection.execute(
            "INSERT INTO movement_sessions(started_at_ms) VALUES (?)",
            (started_at_ms or int(time.time() * 1000),),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def stop_movement(self, finished_at_ms: int | None = None) -> int:
        row = self.connection.execute(
            "SELECT id FROM movement_sessions WHERE finished_at_ms IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No movement session is active")
        self.connection.execute(
            "UPDATE movement_sessions SET finished_at_ms=? WHERE id=?",
            (finished_at_ms or int(time.time() * 1000), row["id"]),
        )
        self.connection.commit()
        return int(row["id"])

    def status(self, since_ms: int, expected_interval_seconds: int) -> dict[str, Any]:
        poll_rows = list(
            self.connection.execute(
                "SELECT * FROM poll_runs WHERE started_at_ms >= ? ORDER BY started_at_ms",
                (since_ms,),
            )
        )
        point_rows = list(
            self.connection.execute(
                "SELECT source_at_ms, fetched_at_ms FROM points WHERE fetched_at_ms >= ?",
                (since_ms,),
            )
        )
        outcomes: dict[str, int] = {}
        for row in poll_rows:
            outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
        success_count = outcomes.get("success", 0)
        gaps = [
            (right["started_at_ms"] - left["started_at_ms"]) / 1000
            for left, right in pairwise(poll_rows)
        ]
        lags = sorted(
            max(0, row["fetched_at_ms"] - row["source_at_ms"]) / 1000
            for row in point_rows
        )
        sessions = self._movement_metrics(expected_interval_seconds)
        return {
            "polls": len(poll_rows),
            "successful_polls": success_count,
            "success_rate": success_count / len(poll_rows) if poll_rows else None,
            "outcomes": outcomes,
            "new_points": len(point_rows),
            "maximum_poll_gap_seconds": max(gaps) if gaps else None,
            "p95_location_lag_seconds": _percentile(lags, 0.95),
            "movement_sessions": sessions,
        }

    def _movement_metrics(self, expected_interval_seconds: int) -> list[dict[str, Any]]:
        sessions = list(
            self.connection.execute(
                """
                SELECT id, started_at_ms, finished_at_ms
                FROM movement_sessions
                WHERE finished_at_ms IS NOT NULL ORDER BY id
                """
            )
        )
        metrics = []
        bin_ms = expected_interval_seconds * 1000
        for session in sessions:
            start = session["started_at_ms"]
            finish = session["finished_at_ms"]
            points = list(
                self.connection.execute(
                    """
                    SELECT device_key, source_at_ms, fetched_at_ms FROM points
                    WHERE fetched_at_ms BETWEEN ? AND ? ORDER BY fetched_at_ms
                    """,
                    (start, finish),
                )
            )
            total_bins = max(1, math.ceil((finish - start) / bin_ms))
            device_keys = sorted({row["device_key"] for row in points})
            if not device_keys:
                metrics.append(
                    {
                        "id": session["id"],
                        "device_key": None,
                        "duration_minutes": round((finish - start) / 60000, 1),
                        "points": 0,
                        "covered_bin_rate": 0.0,
                        "p95_location_lag_seconds": None,
                    }
                )
                continue
            for device_key in device_keys:
                device_points = [
                    row for row in points if row["device_key"] == device_key
                ]
                occupied = {
                    min(
                        total_bins - 1, max(0, (row["fetched_at_ms"] - start) // bin_ms)
                    )
                    for row in device_points
                }
                lags = sorted(
                    max(0, row["fetched_at_ms"] - row["source_at_ms"]) / 1000
                    for row in device_points
                )
                metrics.append(
                    {
                        "id": session["id"],
                        "device_key": device_key,
                        "duration_minutes": round((finish - start) / 60000, 1),
                        "points": len(device_points),
                        "covered_bin_rate": len(occupied) / total_bins,
                        "p95_location_lag_seconds": _percentile(lags, 0.95),
                    }
                )
        return metrics


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    items = list(values)
    if not items:
        return None
    index = max(0, math.ceil(len(items) * percentile) - 1)
    return items[index]
