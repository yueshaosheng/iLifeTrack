"""Helpers for switching local Apple sessions without mixing device choices."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from re import match

from .config import Config


def configured_accounts(config: Config) -> list[str]:
    """Return saved accounts once each, including a legacy active account."""
    result: list[str] = []
    for value in [*config.apple_accounts, config.apple_id]:
        account = value.strip()
        if account and not any(item.casefold() == account.casefold() for item in result):
            result.append(account)
    return result


def activate_account(
    config: Config,
    apple_id: str,
    available_device_keys: Iterable[str],
) -> str:
    """Make an account active and restore only that account's device choices."""
    remember_active_selection(config)
    requested = apple_id.strip()
    if not requested:
        raise ValueError("Apple account is required")
    accounts = configured_accounts(config)
    canonical = next(
        (item for item in accounts if item.casefold() == requested.casefold()), requested
    )
    if not any(item.casefold() == canonical.casefold() for item in accounts):
        accounts.append(canonical)

    available = set(available_device_keys)
    if config.apple_id.casefold() == canonical.casefold():
        previous = config.selected_device_keys
    else:
        previous = _selection_for(config, canonical)
    selected = [key for key in previous if key in available]

    config.apple_accounts = accounts
    config.apple_id = canonical
    config.selected_device_keys = selected
    config.account_device_selections[canonical] = selected.copy()
    return canonical


def remember_active_selection(config: Config) -> None:
    active = config.apple_id.strip()
    if not active:
        return
    canonical = next(
        (
            item
            for item in configured_accounts(config)
            if item.casefold() == active.casefold()
        ),
        active,
    )
    config.account_device_selections[canonical] = config.selected_device_keys.copy()


def remove_account(config: Config, apple_id: str) -> bool:
    """Forget one account while leaving all archives and other accounts intact."""
    remember_active_selection(config)
    target = apple_id.strip()
    matched = next(
        (
            item
            for item in configured_accounts(config)
            if item.casefold() == target.casefold()
        ),
        None,
    )
    if matched is None:
        return False

    config.apple_accounts = [
        item for item in configured_accounts(config) if item.casefold() != matched.casefold()
    ]
    config.account_device_selections = {
        account: keys
        for account, keys in config.account_device_selections.items()
        if account.casefold() != matched.casefold()
    }
    config.account_auth_verified_ms = {
        account: timestamp
        for account, timestamp in config.account_auth_verified_ms.items()
        if account.casefold() != matched.casefold()
    }
    if config.apple_id.casefold() == matched.casefold():
        config.apple_id = ""
        config.selected_device_keys = []
    return True


def update_active_selection(config: Config, selected: Iterable[str]) -> None:
    config.selected_device_keys = list(dict.fromkeys(selected))
    remember_active_selection(config)


def mark_account_verified(config: Config, apple_id: str, timestamp_ms: int) -> None:
    account = next(
        (
            item
            for item in configured_accounts(config)
            if item.casefold() == apple_id.strip().casefold()
        ),
        apple_id.strip(),
    )
    if account:
        config.account_auth_verified_ms[account] = timestamp_ms


def active_account_is_authenticated(config: Config, report: dict[str, object]) -> bool:
    """Prefer a newer successful login over an older background auth error."""
    if not config.apple_id:
        return False
    if report.get("last_poll_outcome") != "auth_required":
        return True
    verified_at = next(
        (
            timestamp
            for account, timestamp in config.account_auth_verified_ms.items()
            if account.casefold() == config.apple_id.casefold()
        ),
        0,
    )
    failed_at = report.get("last_poll_finished_ms")
    return isinstance(failed_at, int) and verified_at >= failed_at


def remove_session_files(session_directory: Path, apple_id: str) -> None:
    """Delete only icloudpy's cookie and session files for one account."""
    session_name = "".join(character for character in apple_id if match(r"\w", character))
    if not session_name:
        return
    for name in (session_name, f"{session_name}.session"):
        candidate = session_directory / name
        if candidate.is_file():
            candidate.unlink(missing_ok=True)


def _selection_for(config: Config, apple_id: str) -> list[str]:
    return next(
        (
            keys
            for account, keys in config.account_device_selections.items()
            if account.casefold() == apple_id.casefold()
        ),
        [],
    )
