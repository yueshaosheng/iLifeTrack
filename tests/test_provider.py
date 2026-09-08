import sys
from types import ModuleType

import pytest

from ilifetrack.errors import ProviderResponseError
from ilifetrack.provider import (
    APPLE_AUTH_ENDPOINT,
    CHINA_HOME_ENDPOINT,
    CHINA_SETUP_ENDPOINT,
    ICloudProvider,
    _install_srp_header_refresh,
    _looks_like_auth_error,
    _new_api,
    _parse_device,
)


class FakeTwoFactorAPI:
    requires_2fa = True
    requires_2sa = False
    is_trusted_session = True

    def __init__(self):
        self.events = []

    def trigger_2fa_push_notification(self):
        self.events.append("push")
        return True

    def validate_2fa_code(self, code):
        self.events.append(("validate", code))
        return True


def test_interactive_login_triggers_push_before_reading_code(monkeypatch, tmp_path):
    api = FakeTwoFactorAPI()
    events = api.events

    def read_code(_prompt):
        events.append("read")
        return "123456"

    monkeypatch.setattr("ilifetrack.provider._new_api", lambda *_args: api)
    provider = ICloudProvider.interactive_login(
        "user@example.com",
        tmp_path,
        password_reader=lambda _prompt: "not-persisted",
        code_reader=read_code,
    )

    assert provider.api is api
    assert events == ["push", "read", ("validate", "123456")]


def test_interactive_login_protects_session_files(monkeypatch, tmp_path):
    api = FakeTwoFactorAPI()
    session_file = tmp_path / "account.session"
    session_file.write_text("secret", encoding="utf-8")
    session_file.chmod(0o644)
    monkeypatch.setattr("ilifetrack.provider._new_api", lambda *_args: api)

    ICloudProvider.interactive_login(
        "user@example.com",
        tmp_path,
        password_reader=lambda _prompt: "not-persisted",
        code_reader=lambda _prompt: "123456",
    )

    assert session_file.stat().st_mode & 0o777 == 0o600


def test_parse_device_with_location():
    device = _parse_device(
        {
            "id": "private-device-id",
            "name": "My iPhone",
            "deviceDisplayName": "iPhone 17 Pro",
            "batteryLevel": 0.7,
            "location": {
                "timeStamp": 1_700_000_000_000,
                "latitude": 31.2304,
                "longitude": 121.4737,
                "horizontalAccuracy": 12.0,
                "isOld": False,
                "positionType": "GPS",
            },
        },
        fetched_at_ms=1_700_000_001_000,
    )

    assert device.name == "My iPhone"
    assert device.location is not None
    assert device.location.latitude == 31.2304
    assert device.location.source_at_ms == 1_700_000_000_000


def test_parse_device_allows_no_location():
    device = _parse_device(
        {
            "id": "offline",
            "name": "Mac",
            "deviceDisplayName": "MacBook Pro",
            "location": None,
        },
        fetched_at_ms=1_700_000_001_000,
    )
    assert device.location is None


def test_parse_device_rejects_missing_id():
    with pytest.raises(ProviderResponseError):
        _parse_device({"name": "Unknown"}, fetched_at_ms=1_700_000_001_000)


def test_icloud_response_code_450_is_authentication_failure():
    class APIResponseError(Exception):
        code = 450
        reason = "Authentication required for Account."

    assert _looks_like_auth_error(APIResponseError()) is True


def test_new_api_uses_global_auth_with_china_mainland_service_endpoints(
    monkeypatch, tmp_path
):
    observed = {}

    class FakeService:
        def __init__(self, apple_id, password, **options):
            observed.update(
                {"apple_id": apple_id, "password": password, **options}
            )

    module = ModuleType("icloudpy")
    module.ICloudPyService = FakeService
    base_module = ModuleType("icloudpy.base")

    class FakeSession:
        def request(self, _method, _url, **_kwargs):
            return object()

    base_module.ICloudPySession = FakeSession
    monkeypatch.setitem(sys.modules, "icloudpy", module)
    monkeypatch.setitem(sys.modules, "icloudpy.base", base_module)

    _new_api("user@example.com", "secret", tmp_path)

    assert observed["auth_endpoint"] == APPLE_AUTH_ENDPOINT
    assert observed["home_endpoint"] == CHINA_HOME_ENDPOINT
    assert observed["setup_endpoint"] == CHINA_SETUP_ENDPOINT


def test_srp_init_response_headers_are_used_for_complete_request():
    class Service:
        def __init__(self):
            self.session_data = {}

    class Session:
        _ilifetrack_srp_header_refresh = False

        def __init__(self):
            self.service = Service()

        def request(self, _method, _url, **_kwargs):
            self.service.session_data.update(
                {"scnt": "fresh-scnt", "session_id": "fresh-session-id"}
            )
            return object()

    _install_srp_header_refresh(Session)
    headers = {"scnt": "stale", "X-Apple-ID-Session-Id": "stale"}

    Session().request("POST", "https://example.test/signin/init", headers=headers)

    assert headers["scnt"] == "fresh-scnt"
    assert headers["X-Apple-ID-Session-Id"] == "fresh-session-id"
