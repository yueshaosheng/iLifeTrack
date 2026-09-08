from ilifetrack import cli
from ilifetrack.config import Config, load_config, save_config
from ilifetrack.paths import AppPaths


def test_logout_removes_account_session_and_preserves_local_archive(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path / "state")
    paths.ensure()
    save_config(
        paths.config,
        Config(
            apple_id="person@example.com",
            selected_device_keys=["device-a"],
            communications_enabled=True,
        ),
    )
    paths.database.write_bytes(b"local archive")
    (paths.sessions / "session.json").write_text("secret", encoding="utf-8")
    nested = paths.sessions / "person"
    nested.mkdir()
    (nested / "cookies").write_text("secret", encoding="utf-8")
    missing_agent = tmp_path / "LaunchAgents" / "com.ilifetrack.app.plist"
    monkeypatch.setattr(cli, "launch_agent_path", lambda: missing_agent)

    assert cli._logout(paths) == 0

    config = load_config(paths.config)
    assert config.apple_id == ""
    assert config.selected_device_keys == []
    assert config.communications_enabled is True
    assert list(paths.sessions.iterdir()) == []
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
