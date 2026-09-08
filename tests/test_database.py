from ilifetrack.crypto import CryptoBox
from ilifetrack.database import HistoryDatabase
from ilifetrack.models import DeviceSnapshot, LocationSnapshot


def make_location(source_at_ms=1_700_000_000_000, fetched_at_ms=1_700_000_001_000):
    return LocationSnapshot(
        device_id="secret-device-id",
        name="Private Phone",
        device_type="iPhone",
        source_at_ms=source_at_ms,
        fetched_at_ms=fetched_at_ms,
        latitude=31.2304,
        longitude=121.4737,
        horizontal_accuracy=5.0,
        is_old=False,
        position_type="GPS",
        battery_level=0.5,
        raw={"latitude": 31.2304, "longitude": 121.4737},
    )


def test_database_encrypts_and_deduplicates(tmp_path):
    target = tmp_path / "history.sqlite3"
    box = CryptoBox.from_master_key(b"d" * 32)
    location = make_location()
    device = DeviceSnapshot(
        location.device_id,
        location.name,
        location.device_type,
        location.battery_level,
        location,
    )

    with HistoryDatabase(target, box) as database:
        device_key = database.upsert_device(device, location.fetched_at_ms)
        assert database.insert_point(location) is True
        assert database.insert_point(location) is False
        database.connection.commit()
        listed = database.list_devices()
        assert listed[0]["name"] == "Private Phone"
        assert listed[0]["device_key"] == device_key
        assert listed[0]["is_available"] is True
        assert database.dashboard()["device_statuses"][0]["device_name"] == (
            "Private Phone"
        )

    raw_file = target.read_bytes()
    assert b"secret-device-id" not in raw_file
    assert b"Private Phone" not in raw_file
    assert b"31.2304" not in raw_file
    assert b"121.4737" not in raw_file


def test_device_sync_marks_removed_devices_unavailable_without_deleting_history(
    tmp_path,
):
    target = tmp_path / "history.sqlite3"
    box = CryptoBox.from_master_key(b"a" * 32)
    first = DeviceSnapshot("first", "First", "iPhone", 0.5, None)
    second = DeviceSnapshot("second", "Second", "Mac", 0.5, None)

    with HistoryDatabase(target, box) as database:
        database.sync_devices([first, second], 1_000)
        database.sync_devices([second], 2_000)
        devices = {item["name"]: item for item in database.list_devices()}

    assert devices["First"]["is_available"] is False
    assert devices["Second"]["is_available"] is True


def test_dashboard_tolerates_rows_encrypted_with_an_unavailable_old_key(tmp_path):
    target = tmp_path / "history.sqlite3"
    location = make_location()
    with HistoryDatabase(target, CryptoBox.from_master_key(b"o" * 32)) as database:
        database.upsert_device(
            DeviceSnapshot(
                location.device_id,
                location.name,
                location.device_type,
                location.battery_level,
                location,
            ),
            location.fetched_at_ms,
        )
        database.insert_point(location)
        database.connection.commit()

    with HistoryDatabase(target, CryptoBox.from_master_key(b"n" * 32)) as database:
        status = database.dashboard()["device_statuses"][0]

    assert status["device_name"] is None


def test_status_and_movement_coverage(tmp_path):
    target = tmp_path / "history.sqlite3"
    box = CryptoBox.from_master_key(b"s" * 32)
    start = 1_700_000_000_000

    with HistoryDatabase(target, box) as database:
        database.start_movement(start)
        for offset_minutes in (1, 6, 11, 16):
            fetched = start + offset_minutes * 60_000
            location = make_location(fetched - 30_000, fetched)
            assert database.insert_point(location)
            database.record_poll(fetched, "success", "ok", 1, 1, 1, fetched + 10)
        database.stop_movement(start + 20 * 60_000)
        report = database.status(start, expected_interval_seconds=300)

    assert report["polls"] == 4
    assert report["success_rate"] == 1.0
    assert report["movement_sessions"][0]["covered_bin_rate"] == 1.0
    assert report["movement_sessions"][0]["p95_location_lag_seconds"] == 30.0


def test_clear_history_preserves_devices_and_removes_records(tmp_path):
    target = tmp_path / "history.sqlite3"
    box = CryptoBox.from_master_key(b"c" * 32)
    start = 1_700_000_000_000
    location = make_location(start, start + 1_000)
    device = DeviceSnapshot(
        location.device_id,
        location.name,
        location.device_type,
        location.battery_level,
        location,
    )

    with HistoryDatabase(target, box) as database:
        database.upsert_device(device, start)
        assert database.insert_point(location)
        database.record_poll(start, "success", "ok", 1, 1, 1, start + 1_000)
        database.start_movement(start)

        deleted = database.clear_history()

        assert deleted == {"points": 1, "poll_runs": 1, "movement_sessions": 1}
        assert len(database.list_devices()) == 1
        assert (
            database.connection.execute("SELECT COUNT(*) FROM points").fetchone()[0]
            == 0
        )
        assert (
            database.connection.execute("SELECT COUNT(*) FROM poll_runs").fetchone()[0]
            == 0
        )
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM movement_sessions"
            ).fetchone()[0]
            == 0
        )


def test_filtered_clear_dashboard_and_retention(tmp_path):
    target = tmp_path / "history.sqlite3"
    box = CryptoBox.from_master_key(b"f" * 32)
    day_ms = 86_400_000
    now = 1_700_000_000_000

    with HistoryDatabase(target, box) as database:
        old = make_location(now - 40 * day_ms, now - 40 * day_ms)
        recent = make_location(now - day_ms, now - day_ms)
        assert database.insert_point(old)
        assert database.insert_point(recent)
        database.record_poll(now - day_ms, "success", "ok", 1, 1, 1, now)

        dashboard = database.dashboard()
        assert dashboard["total_points"] == 2
        assert dashboard["history_start_ms"] == old.source_at_ms
        assert dashboard["history_end_ms"] == recent.source_at_ms
        assert dashboard["last_success_ms"] == now
        assert dashboard["latest_location_lag_seconds"] == 0
        assert dashboard["device_statuses"][0]["last_location_ms"] == recent.source_at_ms

        database.set_next_poll(now + 300_000)
        assert database.dashboard()["next_expected_poll_ms"] == now + 300_000

        assert database.apply_retention(30, now) == 1
        assert database.dashboard()["total_points"] == 1

        deleted = database.clear_history(
            device_key=database.device_key("secret-device-id"),
            start_ms=recent.source_at_ms,
            end_ms=recent.source_at_ms,
        )
        assert deleted["points"] == 1
        assert deleted["poll_runs"] == 0
        assert database.dashboard()["total_points"] == 0


def test_encrypted_backup_can_restore_cleared_history(tmp_path):
    target = tmp_path / "history.sqlite3"
    backups = tmp_path / "backups"
    box = CryptoBox.from_master_key(b"b" * 32)
    location = make_location()

    with HistoryDatabase(target, box) as database:
        assert database.insert_point(location)
        database.connection.commit()
        backup = database.create_backup(backups, "before-clear-history")
        assert backup.stat().st_mode & 0o777 == 0o600
        assert database.clear_history()["points"] == 1
        assert database.dashboard()["total_points"] == 0

        database.restore_backup(backup)

        assert database.dashboard()["total_points"] == 1
        assert b"31.2304" not in backup.read_bytes()
