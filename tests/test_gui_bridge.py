import io
import json

from ilifetrack.crypto import CryptoBox
from ilifetrack.errors import AuthenticationRequired, ProviderNetworkError
from ilifetrack.gui_bridge import (
    _failure_reason,
    _safe_diagnostic_code,
    run_auth_bridge,
)
from ilifetrack.paths import AppPaths


class FakeAPI:
    requires_2fa = True
    requires_2sa = False
    is_trusted_session = True

    def __init__(self):
        self.devices = {
            "device": {
                "id": "device-id",
                "name": "Phone",
                "deviceDisplayName": "iPhone",
                "location": None,
            }
        }

    def trigger_2fa_push_notification(self):
        return True

    def validate_2fa_code(self, code):
        return code == "123456"


def test_gui_auth_bridge_uses_json_lines_and_never_echoes_password(
    monkeypatch, tmp_path
):
    app_paths = AppPaths(tmp_path / "state")
    monkeypatch.setattr("ilifetrack.gui_bridge._new_api", lambda *_args: FakeAPI())
    monkeypatch.setattr(
        "ilifetrack.gui_bridge.CryptoBox.load_or_create",
        lambda: CryptoBox.from_master_key(b"g" * 32),
    )
    input_stream = io.StringIO(
        json.dumps(
            {
                "action": "begin",
                "apple_id": "user@example.com",
                "password": "very-secret",
            }
        )
        + "\n"
        + json.dumps({"action": "submit_code", "code": "123456"})
        + "\n"
    )
    output_stream = io.StringIO()

    assert run_auth_bridge(input_stream, output_stream, app_paths) == 0
    output = output_stream.getvalue()
    events = [json.loads(line) for line in output.splitlines()]

    assert events == [
        {"event": "2fa_required", "push_sent": True},
        {"event": "authenticated", "device_count": 1},
    ]
    assert "very-secret" not in output
    assert "123456" not in output


def test_gui_auth_bridge_uses_fresh_session_and_replaces_it_only_after_success(
    monkeypatch, tmp_path
):
    app_paths = AppPaths(tmp_path / "state")
    app_paths.ensure()
    existing = app_paths.sessions / "userexamplecom.session"
    existing.write_text("old-session", encoding="utf-8")
    observed_directories = []

    def new_api(_apple_id, _password, cookie_directory):
        observed_directories.append(cookie_directory)
        assert (cookie_directory / existing.name).read_text(encoding="utf-8") == (
            "old-session"
        )
        (cookie_directory / existing.name).write_text(
            "fresh-session", encoding="utf-8"
        )
        api = FakeAPI()
        api.requires_2fa = False
        return api

    monkeypatch.setattr("ilifetrack.gui_bridge._new_api", new_api)
    monkeypatch.setattr(
        "ilifetrack.gui_bridge.CryptoBox.load_or_create",
        lambda: CryptoBox.from_master_key(b"f" * 32),
    )
    input_stream = io.StringIO(
        json.dumps(
            {
                "action": "begin",
                "apple_id": "user@example.com",
                "password": "new-password",
            }
        )
        + "\n"
    )

    assert run_auth_bridge(input_stream, io.StringIO(), app_paths) == 0
    assert observed_directories[0] != app_paths.sessions
    assert observed_directories[0].parent == app_paths.sessions
    assert existing.read_text(encoding="utf-8") == "fresh-session"
    assert existing.stat().st_mode & 0o777 == 0o600


def test_gui_auth_bridge_does_not_fail_when_2fa_push_cannot_be_sent(
    monkeypatch, tmp_path
):
    class PushFailureAPI(FakeAPI):
        def trigger_2fa_push_notification(self):
            raise RuntimeError("temporary push failure")

    app_paths = AppPaths(tmp_path / "state")
    monkeypatch.setattr(
        "ilifetrack.gui_bridge._new_api", lambda *_args: PushFailureAPI()
    )
    monkeypatch.setattr(
        "ilifetrack.gui_bridge.CryptoBox.load_or_create",
        lambda: CryptoBox.from_master_key(b"p" * 32),
    )
    input_stream = io.StringIO(
        json.dumps(
            {
                "action": "begin",
                "apple_id": "user@example.com",
                "password": "secret",
            }
        )
        + "\n"
        + json.dumps({"action": "submit_code", "code": "123456"})
        + "\n"
    )
    output_stream = io.StringIO()

    assert run_auth_bridge(input_stream, output_stream, app_paths) == 0
    events = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert events[0] == {"event": "2fa_required", "push_sent": False}
    assert events[-1] == {"event": "authenticated", "device_count": 1}


def test_gui_auth_bridge_forces_password_refresh_with_copied_trusted_session(
    monkeypatch, tmp_path
):
    app_paths = AppPaths(tmp_path / "state")
    app_paths.ensure()
    session_name = "userexamplecom.session"
    (app_paths.sessions / session_name).write_text(
        json.dumps({"session_token": "trusted-old-token"}), encoding="utf-8"
    )
    refresh_calls = []

    class RefreshAPI(FakeAPI):
        requires_2fa = False

        def __init__(self, cookie_directory):
            super().__init__()
            self.cookie_directory = cookie_directory
            self.session_data = {
                "session_token": "trusted-old-token",
                "scnt": "stale-scnt",
                "session_id": "stale-session-id",
            }

        def authenticate(self, force_refresh=False):
            assert "scnt" not in self.session_data
            assert "session_id" not in self.session_data
            refresh_calls.append(force_refresh)
            self.session_data["session_token"] = "new-token"
            (self.cookie_directory / session_name).write_text(
                json.dumps(self.session_data), encoding="utf-8"
            )

    monkeypatch.setattr(
        "ilifetrack.gui_bridge._new_api",
        lambda _apple_id, _password, directory: RefreshAPI(directory),
    )
    monkeypatch.setattr(
        "ilifetrack.gui_bridge.CryptoBox.load_or_create",
        lambda: CryptoBox.from_master_key(b"r" * 32),
    )
    input_stream = io.StringIO(
        json.dumps(
            {
                "action": "begin",
                "apple_id": "user@example.com",
                "password": "correct-password",
            }
        )
        + "\n"
    )

    assert run_auth_bridge(input_stream, io.StringIO(), app_paths) == 0
    assert refresh_calls == [True]
    installed = json.loads(
        (app_paths.sessions / session_name).read_text(encoding="utf-8")
    )
    assert installed["session_token"] == "new-token"


def test_auth_failure_reasons_are_stage_specific():
    assert (
        _failure_reason(AuthenticationRequired("login_failed"), "credentials")
        == "credentials_rejected"
    )
    assert (
        _failure_reason(AuthenticationRequired("saved_session_invalid"), "find_my")
        == "find_my_session_rejected"
    )
    assert _failure_reason(ProviderNetworkError("network"), "find_my") == "network_error"


def test_safe_diagnostic_code_exposes_code_but_not_provider_message():
    class AppleError(Exception):
        code = -22406

    error = AuthenticationRequired("wrapper")
    error.__cause__ = AppleError("private provider response")

    diagnostic = _safe_diagnostic_code(error)

    assert diagnostic == "Apple--22406"
    assert "private provider response" not in diagnostic
