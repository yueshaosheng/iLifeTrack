from ilifetrack import cli
from ilifetrack.accounts import activate_account, configured_accounts
from ilifetrack.config import Config, load_config, save_config
from ilifetrack.models import DeviceSnapshot
from ilifetrack.paths import AppPaths


def test_logout_removes_account_session_and_preserves_local_archive(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path / "state")
    paths.ensure()
    save_config(
        paths.config,
        Config(
            apple_id="person@example.com",
            apple_accounts=["person@example.com", "other@example.com"],
            selected_device_keys=["device-a"],
            account_device_selections={
                "person@example.com": ["device-a"],
                "other@example.com": ["device-b"],
            },
            communications_enabled=True,
        ),
    )
    paths.database.write_bytes(b"local archive")
    (paths.sessions / "personexamplecom").write_text("cookie", encoding="utf-8")
    (paths.sessions / "personexamplecom.session").write_text(
        "session", encoding="utf-8"
    )
    (paths.sessions / "otherexamplecom.session").write_text(
        "other session", encoding="utf-8"
    )
    missing_agent = tmp_path / "LaunchAgents" / "com.ilifetrack.app.plist"
    monkeypatch.setattr(cli, "launch_agent_path", lambda: missing_agent)

    assert cli._logout(paths) == 0

    config = load_config(paths.config)
    assert config.apple_id == ""
    assert config.selected_device_keys == []
    assert config.communications_enabled is True
    assert configured_accounts(config) == ["other@example.com"]
    assert sorted(entry.name for entry in paths.sessions.iterdir()) == [
        "otherexamplecom.session"
    ]
    assert paths.database.read_bytes() == b"local archive"


def test_logout_stops_location_only_background_service(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path / "state")
    paths.ensure()
    save_config(
        paths.config,
        Config(apple_id="person@example.com", selected_device_keys=["device-a"]),
    )
    agent = tmp_path / "com.ilifetrack.app.plist"
    agent.touch()
    stopped = []
    monkeypatch.setattr(cli, "launch_agent_path", lambda: agent)
    monkeypatch.setattr(cli, "uninstall_agent", lambda: stopped.append(True) or True)

    assert cli._logout(paths) == 0
    assert stopped == [True]


def test_account_switch_restores_only_the_target_account_selection(
    tmp_path, monkeypatch
):
    paths = AppPaths(tmp_path / "state")
    paths.ensure()
    config = Config(
        apple_id="first@example.com",
        apple_accounts=["first@example.com", "second@example.com"],
        selected_device_keys=["first-device"],
        account_device_selections={
            "first@example.com": ["first-device"],
            "second@example.com": ["second-device", "missing-device"],
        },
    )

    class Provider:
        def fetch_devices(self, _timestamp):
            return [
                DeviceSnapshot(
                    device_id="second-id",
                    name="Second Phone",
                    device_type="iPhone",
                    battery_level=None,
                    location=None,
                )
            ]

    class Database:
        def sync_devices(self, _devices, _timestamp):
            return ["second-device"]

    monkeypatch.setattr(
        cli.ICloudProvider,
        "from_saved_session",
        lambda account, _sessions: Provider()
        if account == "second@example.com"
        else None,
    )
    monkeypatch.setattr(
        cli, "launch_agent_path", lambda: tmp_path / "missing-launch-agent"
    )

    assert (
        cli._switch_account(
            paths, config, Database(), "SECOND@example.com"
        )
        == 0
    )
    loaded = load_config(paths.config)
    assert loaded.apple_id == "second@example.com"
    assert loaded.selected_device_keys == ["second-device"]
    assert loaded.account_device_selections["first@example.com"] == ["first-device"]
    assert loaded.account_device_selections["second@example.com"] == ["second-device"]


def test_registering_a_new_account_does_not_reuse_the_previous_devices():
    config = Config(
        apple_id="first@example.com",
        selected_device_keys=["shared-looking-key"],
    )

    activate_account(config, "new@example.com", ["shared-looking-key"])

    assert config.apple_id == "new@example.com"
    assert config.selected_device_keys == []
    assert config.account_device_selections["first@example.com"] == [
        "shared-looking-key"
    ]
