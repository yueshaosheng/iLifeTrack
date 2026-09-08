"""JSON-lines authentication bridge used only by the native local GUI."""

from __future__ import annotations

import base64
import json
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from re import match
from typing import IO, Any

from .config import Config, load_config, save_config
from .crypto import CryptoBox
from .database import HistoryDatabase
from .errors import (
    AuthenticationRequired,
    ConfigurationError,
    ProviderNetworkError,
    ProviderResponseError,
)
from .paths import AppPaths
from .provider import (
    ICloudProvider,
    _new_api,
    _protect_session_files,
    discard_stale_auth_handshake,
    refresh_api_credentials,
)


def run_auth_bridge(
    input_stream: IO[str] = sys.stdin,
    output_stream: IO[str] = sys.stdout,
    paths: AppPaths | None = None,
) -> int:
    selected_paths = paths or AppPaths.default()
    selected_paths.ensure()
    password = ""
    stage = "request"
    try:
        request = _read_message(input_stream)
        if request.get("action") != "begin":
            return _fail(output_stream, "invalid_request")
        apple_id = str(request.get("apple_id") or "").strip()
        password = str(request.get("password") or "")
        if not apple_id or not password:
            return _fail(output_stream, "missing_credentials")
        crypto = _crypto_from_request(request.get("master_key"))

        # Work in an isolated copy so a failed refresh cannot damage the current
        # session. Retaining the trusted-browser cookies/token avoids making every
        # refresh look like an unknown new browser to Apple.
        with _staged_session_directory(selected_paths.sessions) as login_sessions:
            stage = "credentials"
            previous_token = _saved_session_token(login_sessions, apple_id)
            api = _new_api(apple_id, password, login_sessions)
            if previous_token is not None and (
                getattr(api, "session_data", {}).get("session_token")
                == previous_token
            ):
                # icloudpy accepted the setup token and therefore skipped the
                # password supplied above. Explicitly force credential refresh.
                discard_stale_auth_handshake(api)
                refresh_api_credentials(api)
            if getattr(api, "requires_2fa", False):
                trigger = getattr(api, "trigger_2fa_push_notification", None)
                push_sent = False
                if callable(trigger):
                    try:
                        push_sent = bool(trigger())
                    except Exception:  # noqa: BLE001 - push failure is non-fatal
                        push_sent = False
                _emit(
                    output_stream,
                    {"event": "2fa_required", "push_sent": push_sent},
                )
                stage = "verification"
                for _attempt in range(3):
                    code_request = _read_message(input_stream)
                    if code_request.get("action") == "cancel":
                        return _fail(output_stream, "cancelled")
                    code = str(code_request.get("code") or "").strip()
                    if (
                        len(code) == 6
                        and code.isdigit()
                        and api.validate_2fa_code(code)
                    ):
                        if (
                            not getattr(api, "is_trusted_session", False)
                            and not api.trust_session()
                        ):
                            return _fail(output_stream, "trust_failed")
                        break
                    _emit(output_stream, {"event": "invalid_code"})
                else:
                    return _fail(output_stream, "too_many_invalid_codes")
            elif getattr(api, "requires_2sa", False):
                return _fail(output_stream, "legacy_2sa_not_supported")

            stage = "find_my"
            provider = ICloudProvider(api)
            devices = provider.fetch_devices(int(time.time() * 1000))
            _protect_session_files(login_sessions)
            _install_session_files(login_sessions, selected_paths.sessions)

        try:
            config = load_config(selected_paths.config)
        except ConfigurationError:
            config = Config()
        config.apple_id = apple_id
        save_config(selected_paths.config, config)

        with HistoryDatabase(selected_paths.database, crypto) as database:
            now_ms = int(time.time() * 1000)
            for device in devices:
                database.upsert_device(device, now_ms)
            database.connection.commit()
        _emit(output_stream, {"event": "authenticated", "device_count": len(devices)})
        return 0
    except (EOFError, json.JSONDecodeError):
        return _fail(output_stream, "invalid_request")
    except Exception as exc:  # noqa: BLE001 - never expose provider details
        return _fail(
            output_stream,
            _failure_reason(exc, stage),
            diagnostic_code=_safe_diagnostic_code(exc),
        )
    finally:
        password = ""


def _crypto_from_request(value: Any) -> CryptoBox:
    if value is None:
        # Kept for command-line compatibility. The native app always supplies
        # the in-memory key and is therefore the sole Keychain reader.
        return CryptoBox.load_or_create()
    try:
        decoded = base64.urlsafe_b64decode(str(value).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ConfigurationError("Invalid session key") from exc
    if len(decoded) != 32:
        raise ConfigurationError("Invalid session key")
    return CryptoBox.from_master_key(decoded)


def _read_message(stream: IO[str]) -> dict[str, Any]:
    line = stream.readline()
    if not line:
        raise EOFError
    value = json.loads(line)
    if not isinstance(value, dict):
        raise json.JSONDecodeError("Expected object", line, 0)
    return value


def _emit(stream: IO[str], payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    stream.flush()


def _fail(
    stream: IO[str], reason: str, diagnostic_code: str | None = None
) -> int:
    payload = {"event": "error", "reason": reason}
    if diagnostic_code:
        payload["diagnostic_code"] = diagnostic_code
    _emit(stream, payload)
    return 2


@contextmanager
def _staged_session_directory(session_directory: Path):
    with tempfile.TemporaryDirectory(
        prefix=".reauth-", dir=session_directory
    ) as temporary:
        staged = Path(temporary)
        staged.chmod(0o700)
        for source in session_directory.iterdir():
            if source.is_file() and not source.name.startswith("."):
                destination = staged / source.name
                shutil.copy2(source, destination)
                destination.chmod(0o600)
        yield staged


def _saved_session_token(session_directory: Path, apple_id: str) -> str | None:
    session_name = "".join(character for character in apple_id if match(r"\w", character))
    session_path = session_directory / f"{session_name}.session"
    try:
        value = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = value.get("session_token") if isinstance(value, dict) else None
    return str(token) if token else None


def _install_session_files(source_directory: Path, destination_directory: Path) -> None:
    for source in source_directory.iterdir():
        if not source.is_file():
            continue
        staged = destination_directory / f".{source.name}.new"
        shutil.copy2(source, staged)
        staged.chmod(0o600)
        staged.replace(destination_directory / source.name)
    _protect_session_files(destination_directory)


def _failure_reason(exc: Exception, stage: str) -> str:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None:
        chain.append(current)
        current = current.__cause__

    if any(isinstance(item, ProviderNetworkError) for item in chain):
        return "network_error"
    if stage == "find_my" and any(
        isinstance(item, AuthenticationRequired) for item in chain
    ):
        return "find_my_session_rejected"
    if stage == "credentials" and any(
        isinstance(item, AuthenticationRequired) for item in chain
    ):
        return "credentials_rejected"
    if stage == "verification":
        return "verification_failed"
    if any(isinstance(item, ProviderResponseError) for item in chain):
        return "apple_service_error"
    return "authentication_failed"


def _safe_diagnostic_code(exc: Exception) -> str:
    current: BaseException | None = exc
    exception_names: list[str] = []
    while current is not None:
        exception_names.append(type(current).__name__)
        code = getattr(current, "code", None)
        if code is not None:
            safe_code = "".join(
                character
                for character in str(code)
                if character.isalnum() or character in "-_."
            )
            if safe_code:
                return f"Apple-{safe_code}"
        current = current.__cause__
    return exception_names[-1][:48] if exception_names else "Unknown"
