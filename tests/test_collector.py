from ilifetrack.collector import Collector
from ilifetrack.crypto import CryptoBox
from ilifetrack.database import HistoryDatabase
from ilifetrack.models import DeviceSnapshot, LocationSnapshot


class FakeProvider:
    def __init__(self, devices):
        self.devices = devices

    def fetch_devices(self, fetched_at_ms=None):
        return self.devices


def test_collector_only_records_selected_device(tmp_path):
    box = CryptoBox.from_master_key(b"c" * 32)
    with HistoryDatabase(tmp_path / "history.sqlite3", box) as database:
        selected_location = LocationSnapshot(
            "selected-id",
            "Selected",
            "iPhone",
            1000,
            2000,
            1.0,
            2.0,
            5.0,
            False,
            "GPS",
            0.8,
            {},
        )
        other_location = LocationSnapshot(
            "other-id",
            "Other",
            "iPad",
            1000,
            2000,
            3.0,
            4.0,
            5.0,
            False,
            "GPS",
            0.8,
            {},
        )
        provider = FakeProvider(
            [
                DeviceSnapshot(
                    "selected-id", "Selected", "iPhone", 0.8, selected_location
                ),
                DeviceSnapshot("other-id", "Other", "iPad", 0.8, other_location),
            ]
        )
        collector = Collector(provider, database, [database.device_key("selected-id")])
        result = collector.collect_once()
        count = database.connection.execute("SELECT COUNT(*) FROM points").fetchone()[0]

    assert result.outcome == "success"
    assert result.device_count == 2
    assert result.selected_count == 1
    assert result.new_points == 1
    assert count == 1


def test_collector_reconciles_selection_with_current_find_my_devices(tmp_path):
    box = CryptoBox.from_master_key(b"r" * 32)
    observed = []
    with HistoryDatabase(tmp_path / "history.sqlite3", box) as database:
        current = DeviceSnapshot("current", "Current", "Mac", 0.7, None)
        current_key = database.device_key("current")
        removed_key = database.device_key("removed")

        def reconcile(available):
            observed.append(available)
            return [key for key in (current_key, removed_key) if key in available]

        collector = Collector(
            FakeProvider([current]),
            database,
            [current_key, removed_key],
            reconcile_selection=reconcile,
        )
        result = collector.collect_once()

    assert observed == [{current_key}]
    assert result.selected_count == 1
