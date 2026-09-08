from lifetrack.collector import Collector
from lifetrack.crypto import CryptoBox
from lifetrack.database import HistoryDatabase
from lifetrack.models import DeviceSnapshot, LocationSnapshot


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
