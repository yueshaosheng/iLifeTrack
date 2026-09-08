"""Read-only adapter for iCloudPy's Find My iPhone web service."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Mapping
from getpass import getpass
from pathlib import Path
from typing import Any

from .errors import AuthenticationRequired, ProviderNetworkError, ProviderResponseError
from .models import DeviceSnapshot, LocationSnapshot

CHINA_HOME_ENDPOINT = "https://www.icloud.com.cn"
CHINA_SETUP_ENDPOINT = "https://setup.icloud.com.cn/setup/ws/1"
APPLE_AUTH_ENDPOINT = "https://idmsa.apple.com/appleauth/auth"


class ICloudProvider:
    def __init__(self, api: Any):
        self.api = api

    @classmethod
    def interactive_login(
        cls,
        apple_id: str,
        cookie_directory: Path,
        password_reader: Callable[[str], str] = getpass,
        code_reader: Callable[[str], str] = input,
    ) -> ICloudProvider:
        password = password_reader("Apple 账户密码（不会保存）: ")
        api = _new_api(apple_id, password, cookie_directory)
        try:
            if getattr(api, "requires_2fa", False):
                trigger = getattr(api, "trigger_2fa_push_notification", None)
                if not callable(trigger) or not trigger():
                    print(
                        "未能主动推送验证码；请检查受信任设备联网状态，稍后重新认证。"
                    )
                code = code_reader("Apple 账户双重认证码: ").strip()
                if not api.validate_2fa_code(code):
                    raise AuthenticationRequired("2FA validation failed")
                if (
                    not getattr(api, "is_trusted_session", False)
                    and not api.trust_session()
                ):
                    raise AuthenticationRequired("The session could not be trusted")
            elif getattr(api, "requires_2sa", False):
                devices = list(api.trusted_devices)
                if not devices:
                    raise AuthenticationRequired(
                        "No trusted device is available for 2SA"
                    )
                if not api.send_verification_code(devices[0]):
                    raise AuthenticationRequired("Could not request a 2SA code")
                code = code_reader("Apple 账户双重认证码: ").strip()
                if not api.validate_verification_code(devices[0], code):
                    raise AuthenticationRequired("2SA validation failed")
            _protect_session_files(cookie_directory)
            return cls(api)
        finally:
            password = ""  # Best-effort removal of the local reference.

    @classmethod
    def from_saved_session(
        cls, apple_id: str, cookie_directory: Path
    ) -> ICloudProvider:
        try:
            # A valid saved token is checked before this deliberately invalid,
            # non-secret sentinel is ever used.
            provider = cls(
                _new_api(apple_id, "__LIFETRACK_SESSION_ONLY__", cookie_directory)
            )
            _protect_session_files(cookie_directory)
            return provider
        except Exception as exc:  # library exceptions have changed between releases
            if _looks_like_network_error(exc):
                raise ProviderNetworkError("network") from exc
            raise AuthenticationRequired("saved_session_invalid") from exc

    def fetch_devices(self, fetched_at_ms: int | None = None) -> list[DeviceSnapshot]:
        observed_ms = fetched_at_ms or int(time.time() * 1000)
        try:
            manager = self.api.devices
            raw_devices: Iterable[Any] = manager.values()
            return [
                _parse_device(_mapping(device), observed_ms) for device in raw_devices
            ]
        except (AuthenticationRequired, ProviderResponseError):
            raise
        except Exception as exc:
            if _looks_like_network_error(exc):
                raise ProviderNetworkError("network") from exc
            if _looks_like_auth_error(exc):
                raise AuthenticationRequired("saved_session_invalid") from exc
            raise ProviderResponseError(type(exc).__name__) from exc


def _new_api(apple_id: str, password: str, cookie_directory: Path) -> Any:
    try:
        from icloudpy import ICloudPyService
        from icloudpy.base import ICloudPySession

        _install_srp_header_refresh(ICloudPySession)

        return ICloudPyService(
            apple_id,
            password,
            cookie_directory=str(cookie_directory),
            with_family=True,
            auth_endpoint=APPLE_AUTH_ENDPOINT,
            home_endpoint=CHINA_HOME_ENDPOINT,
            setup_endpoint=CHINA_SETUP_ENDPOINT,
        )
    except Exception as exc:
        if _looks_like_network_error(exc):
            raise ProviderNetworkError("network") from exc
        if _looks_like_auth_error(exc):
            raise AuthenticationRequired("login_failed") from exc
        raise ProviderResponseError(type(exc).__name__) from exc


def discard_stale_auth_handshake(api: Any) -> None:
    """Drop host-specific one-time headers before starting a new SRP login."""
    session_data = getattr(api, "session_data", None)
    if isinstance(session_data, dict):
        session_data.pop("scnt", None)
        session_data.pop("session_id", None)


def _install_srp_header_refresh(session_class: type) -> None:
    """Carry Apple's fresh signin/init state into the signin/complete request."""
    if getattr(session_class, "_ilifetrack_srp_header_refresh", False):
        return
    original_request = session_class.request

    def request_with_refreshed_headers(self, method, url, **kwargs):
        response = original_request(self, method, url, **kwargs)
        if url.endswith("/signin/init"):
            headers = kwargs.get("headers")
            session_data = getattr(self.service, "session_data", {})
            if isinstance(headers, dict) and isinstance(session_data, dict):
                if session_data.get("scnt"):
                    headers["scnt"] = session_data["scnt"]
                if session_data.get("session_id"):
                    headers["X-Apple-ID-Session-Id"] = session_data["session_id"]
        return response

    session_class.request = request_with_refreshed_headers
    session_class._ilifetrack_srp_header_refresh = True


def refresh_api_credentials(api: Any) -> None:
    """Force credential authentication while retaining trusted-session context."""
    try:
        api.authenticate(force_refresh=True)
    except Exception as exc:
        if _looks_like_network_error(exc):
            raise ProviderNetworkError("network") from exc
        if _looks_like_auth_error(exc):
            raise AuthenticationRequired("login_rejected") from exc
        raise ProviderResponseError(type(exc).__name__) from exc


def _mapping(device: Any) -> Mapping[str, Any]:
    if isinstance(device, Mapping):
        return device
    content = getattr(device, "content", None)
    if isinstance(content, Mapping):
        return content
    data = getattr(device, "data", None)
    if isinstance(data, Mapping):
        return data
    raise ProviderResponseError("device_shape")


def _parse_device(raw: Mapping[str, Any], fetched_at_ms: int) -> DeviceSnapshot:
    device_id = str(raw.get("id") or "")
    if not device_id:
        raise ProviderResponseError("missing_device_id")
    name = str(raw.get("name") or "Unnamed device")
    device_type = str(
        raw.get("deviceDisplayName")
        or raw.get("deviceClass")
        or raw.get("rawDeviceModel")
        or "Unknown"
    )
    battery = _optional_float(raw.get("batteryLevel"))
    location_raw = raw.get("location")
    location = None
    if isinstance(location_raw, Mapping):
        try:
            latitude = float(location_raw["latitude"])
            longitude = float(location_raw["longitude"])
            source_at_ms = int(location_raw["timeStamp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderResponseError("invalid_location") from exc
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ProviderResponseError("invalid_location")
        location = LocationSnapshot(
            device_id=device_id,
            name=name,
            device_type=device_type,
            source_at_ms=source_at_ms,
            fetched_at_ms=fetched_at_ms,
            latitude=latitude,
            longitude=longitude,
            horizontal_accuracy=_optional_float(location_raw.get("horizontalAccuracy")),
            is_old=_optional_bool(location_raw.get("isOld")),
            position_type=_optional_string(location_raw.get("positionType")),
            battery_level=battery,
            raw=dict(location_raw),
        )
    return DeviceSnapshot(device_id, name, device_type, battery, location)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _looks_like_network_error(exc: Exception) -> bool:
    names = {type(exc).__name__.lower()}
    current = exc.__cause__
    while current is not None:
        names.add(type(current).__name__.lower())
        current = current.__cause__
    return any(
        token in name
        for name in names
        for token in ("connection", "timeout", "network", "dns", "ssl")
    )


def _looks_like_auth_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        name = type(current).__name__.lower()
        reason = str(getattr(current, "reason", "")).lower()
        code = getattr(current, "code", None)
        if code in {421, 450}:
            return True
        if any(token in name or token in reason for token in ("login", "auth", "2fa", "2sa")):
            return True
        current = current.__cause__
    return False


def _protect_session_files(cookie_directory: Path) -> None:
    for session_file in cookie_directory.iterdir():
        if session_file.is_file():
            session_file.chmod(0o600)
