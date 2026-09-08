"""Read new communications already synchronized to this Mac."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from typedstream import unarchive_from_data
from typedstream.archiving import GenericArchivedObject, TypedGroup
from typedstream.types.foundation import NSString

from .database import HistoryDatabase
from .errors import CommunicationAccessError
from .models import CommunicationSnapshot

APPLE_EPOCH_UNIX_SECONDS = 978_307_200
MAX_BODY_CHARACTERS = 200_000


class MacCommunicationSource:
    def __init__(
        self,
        messages_path: Path | None = None,
        calls_path: Path | None = None,
    ) -> None:
        home = Path.home()
        self.messages_path = messages_path or home / "Library" / "Messages" / "chat.db"
        self.calls_path = (
            calls_path
            or home
            / "Library"
            / "Application Support"
            / "CallHistoryDB"
            / "CallHistory.storedata"
        )

    def check_access(self) -> None:
        for source, path in (
            ("messages", self.messages_path),
            ("calls", self.calls_path),
        ):
            try:
                with self._connect(path) as connection:
                    connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            except (OSError, sqlite3.Error) as exc:
                raise CommunicationAccessError(
                    f"无法读取{_source_title(source)}数据库。请为 LifeTrack 开启完全磁盘访问权限。"
                ) from exc

    def has_access(self) -> bool:
        try:
            self.check_access()
        except CommunicationAccessError:
            return False
        return True

    def current_cursors(self) -> dict[str, int]:
        self.check_access()
        return {
            "messages": self._maximum_row_id(self.messages_path, "message", "ROWID"),
            "calls": self._maximum_row_id(self.calls_path, "ZCALLRECORD", "Z_PK"),
        }

    def read_messages_after(
        self, cursor: int, archived_at_ms: int
    ) -> tuple[list[CommunicationSnapshot], int]:
        sql = """
        SELECT
            m.ROWID AS source_row_id,
            m.guid,
            m.text,
            m.attributedBody,
            m.subject,
            m.date,
            m.is_from_me,
            m.service,
            m.cache_has_attachments,
            h.id AS sender,
            (
                SELECT COALESCE(c.display_name, c.chat_identifier)
                FROM chat_message_join cmj
                JOIN chat c ON c.ROWID = cmj.chat_id
                WHERE cmj.message_id = m.ROWID
                ORDER BY cmj.chat_id LIMIT 1
            ) AS conversation
        FROM message m
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        WHERE m.ROWID > ?
        ORDER BY m.ROWID
        """
        try:
            with self._connect(self.messages_path) as connection:
                rows = list(connection.execute(sql, (cursor,)))
        except (OSError, sqlite3.Error) as exc:
            raise CommunicationAccessError(
                "无法读取信息数据库。请确认 LifeTrack 已获得完全磁盘访问权限。"
            ) from exc

        records: list[CommunicationSnapshot] = []
        maximum = cursor
        for row in rows:
            row_id = int(row["source_row_id"])
            maximum = max(maximum, row_id)
            source_id = str(row["guid"] or f"message-row-{row_id}")
            plain_text = _clean_text(row["text"])
            body = plain_text or _decode_attributed_body(row["attributedBody"])
            subject = _clean_text(row["subject"])
            if subject and body:
                body = f"{subject}\n{body}"
            elif subject:
                body = subject
            from_me = bool(row["is_from_me"])
            participant = row["conversation"] if from_me else row["sender"]
            records.append(
                CommunicationSnapshot(
                    kind="message",
                    source_id=source_id,
                    source_row_id=row_id,
                    occurred_at_ms=_message_time_ms(row["date"], archived_at_ms),
                    archived_at_ms=archived_at_ms,
                    direction="outgoing" if from_me else "incoming",
                    participant=_clean_text(participant),
                    participant_name=None,
                    body=body,
                    service=_clean_text(row["service"]),
                    duration_seconds=None,
                    answered=None,
                    has_attachments=bool(row["cache_has_attachments"]),
                )
            )
        return records, maximum

    def read_calls_after(
        self, cursor: int, archived_at_ms: int
    ) -> tuple[list[CommunicationSnapshot], int]:
        sql = """
        SELECT
            Z_PK AS source_row_id,
            ZUNIQUE_ID AS unique_id,
            ZDATE AS call_date,
            ZDURATION AS duration,
            ZORIGINATED AS originated,
            ZANSWERED AS answered,
            ZADDRESS AS address,
            ZNAME AS participant_name,
            ZSERVICE_PROVIDER AS service,
            ZCALLTYPE AS call_type
        FROM ZCALLRECORD
        WHERE Z_PK > ?
        ORDER BY Z_PK
        """
        try:
            with self._connect(self.calls_path) as connection:
                rows = list(connection.execute(sql, (cursor,)))
        except (OSError, sqlite3.Error) as exc:
            raise CommunicationAccessError(
                "无法读取通话历史数据库。请确认 LifeTrack 已获得完全磁盘访问权限。"
            ) from exc

        records: list[CommunicationSnapshot] = []
        maximum = cursor
        for row in rows:
            row_id = int(row["source_row_id"])
            maximum = max(maximum, row_id)
            source_id = str(row["unique_id"] or f"call-row-{row_id}")
            records.append(
                CommunicationSnapshot(
                    kind="call",
                    source_id=source_id,
                    source_row_id=row_id,
                    occurred_at_ms=_call_time_ms(row["call_date"], archived_at_ms),
                    archived_at_ms=archived_at_ms,
                    direction="outgoing" if bool(row["originated"]) else "incoming",
                    participant=_clean_text(row["address"]),
                    participant_name=_clean_text(row["participant_name"]),
                    body=None,
                    service=_clean_text(row["service"]),
                    duration_seconds=_optional_nonnegative_float(row["duration"]),
                    answered=bool(row["answered"]) if row["answered"] is not None else None,
                    has_attachments=False,
                )
            )
        return records, maximum

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=2000")
        return connection

    def _maximum_row_id(self, path: Path, table: str, column: str) -> int:
        try:
            with self._connect(path) as connection:
                row = connection.execute(
                    f"SELECT COALESCE(MAX({column}), 0) FROM {table}"
                ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise CommunicationAccessError(
                f"无法读取{_source_title(table)}数据库。请为 LifeTrack 开启完全磁盘访问权限。"
            ) from exc
        return int(row[0])


class CommunicationCollector:
    def __init__(self, source: MacCommunicationSource, database: HistoryDatabase) -> None:
        self.source = source
        self.database = database

    def initialize_from_now(self) -> dict[str, int]:
        cursors = self.source.current_cursors()
        for source, cursor in cursors.items():
            self.database.set_communication_cursor(source, cursor)
        self.database.connection.commit()
        return cursors

    def import_existing(self) -> int:
        archived_at_ms = int(time.time() * 1000)
        imported = 0
        try:
            for source_name, reader in (
                ("messages", self.source.read_messages_after),
                ("calls", self.source.read_calls_after),
            ):
                records, maximum = reader(0, archived_at_ms)
                with self.database.connection:
                    for record in records:
                        if self.database.insert_communication(record):
                            imported += 1
                    self.database.set_communication_cursor(source_name, maximum)
            self.database.record_communication_scan("success", "import", imported)
            return imported
        except CommunicationAccessError:
            self.database.record_communication_scan("permission_required", "access", 0)
            raise
        except Exception:
            self.database.record_communication_scan("internal_error", "internal", 0)
            raise

    def collect_once(self) -> int:
        archived_at_ms = int(time.time() * 1000)
        new_records = 0
        try:
            for source_name, reader in (
                ("messages", self.source.read_messages_after),
                ("calls", self.source.read_calls_after),
            ):
                cursor = self.database.communication_cursor(source_name)
                if cursor is None:
                    cursor = self.source.current_cursors()[source_name]
                    self.database.set_communication_cursor(source_name, cursor)
                    self.database.connection.commit()
                    continue
                records, maximum = reader(cursor, archived_at_ms)
                with self.database.connection:
                    for record in records:
                        if self.database.insert_communication(record):
                            new_records += 1
                    self.database.set_communication_cursor(source_name, maximum)
            self.database.record_communication_scan("success", "ok", new_records)
            return new_records
        except CommunicationAccessError:
            self.database.record_communication_scan("permission_required", "access", 0)
            raise
        except Exception:
            self.database.record_communication_scan("internal_error", "internal", 0)
            raise


def _message_time_ms(value: Any, fallback_ms: int) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback_ms
    seconds = numeric / 1_000_000_000 if abs(numeric) > 10_000_000_000 else numeric
    timestamp_ms = int((APPLE_EPOCH_UNIX_SECONDS + seconds) * 1000)
    return timestamp_ms if timestamp_ms > 0 else fallback_ms


def _call_time_ms(value: Any, fallback_ms: int) -> int:
    try:
        timestamp_ms = int((APPLE_EPOCH_UNIX_SECONDS + float(value)) * 1000)
    except (TypeError, ValueError):
        return fallback_ms
    return timestamp_ms if timestamp_ms > 0 else fallback_ms


def _decode_attributed_body(value: Any) -> str | None:
    if not isinstance(value, bytes) or not value:
        return None
    try:
        root = unarchive_from_data(value)
        candidates = _collect_strings(root, set())
    except Exception:  # noqa: BLE001 - private Apple archive formats vary by OS release
        return None
    meaningful = [text for text in candidates if _clean_text(text)]
    if not meaningful:
        return None
    return _clean_text(max(meaningful, key=len))


def _collect_strings(value: Any, seen: set[int]) -> list[str]:
    if value is None or isinstance(value, (bool, int, float, bytes)):
        return []
    if isinstance(value, str):
        return [value]
    identifier = id(value)
    if identifier in seen:
        return []
    seen.add(identifier)
    if isinstance(value, NSString):
        return [value.value]
    if isinstance(value, TypedGroup):
        result: list[str] = []
        for item in value.values:
            result.extend(_collect_strings(item, seen))
        return result
    if isinstance(value, GenericArchivedObject):
        result = _collect_strings(value.super_object, seen)
        for item in value.contents:
            result.extend(_collect_strings(item, seen))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_collect_strings(item, seen))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_collect_strings(item, seen))
        return result
    if hasattr(value, "value"):
        return _collect_strings(value.value, seen)
    if hasattr(value, "elements"):
        return _collect_strings(value.elements, seen)
    return []


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.replace("\x00", "").strip()
    return text[:MAX_BODY_CHARACTERS] if text else None


def _optional_nonnegative_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, number)


def _source_title(source: str) -> str:
    return "信息" if source in {"messages", "message"} else "通话历史"
