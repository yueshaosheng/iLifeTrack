"""Command-line interface for setup and the 48-hour proof of concept."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path

from .accounts import (
    activate_account,
    active_account_is_authenticated,
    claim_legacy_database,
    configured_accounts,
    mark_account_verified,
    remove_account,
    remove_session_files,
    update_active_selection,
)
from .collector import Collector, run_forever
from .communications import CommunicationCollector, MacCommunicationSource
from .config import Config, load_config, save_config
from .crypto import CryptoBox
from .database import HistoryDatabase
from .errors import AuthenticationRequired, ConfigurationError, ILifeTrackError
from .gui_bridge import run_auth_bridge
from .paths import AppPaths
from .provider import ICloudProvider
from .service import install as install_agent
from .service import launch_agent_path
from .service import uninstall as uninstall_agent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ilifetrack")
    parser.add_argument("--master-key-stdin", action="store_true", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser(
        "auth", help="Create or refresh the local iCloud session"
    )
    auth.add_argument("--apple-id", help="Apple account; password is prompted securely")
    subparsers.add_parser("logout", help=argparse.SUPPRESS)
    switch_account = subparsers.add_parser("switch-account", help=argparse.SUPPRESS)
    switch_account.add_argument("apple_id")
    remove_saved_account = subparsers.add_parser(
        "remove-account", help=argparse.SUPPRESS
    )
    remove_saved_account.add_argument("apple_id")

    subparsers.add_parser("devices", help="Refresh and list discoverable devices")

    select = subparsers.add_parser("select", help="Choose devices to record")
    select.add_argument(
        "device_keys", nargs="*", help="Short identifiers printed by devices"
    )
    select.add_argument(
        "--all", action="store_true", help="Record every currently visible device"
    )

    subparsers.add_parser("once", help="Run one location poll")
    run = subparsers.add_parser("run", help="Run the long-lived collector")
    run.add_argument(
        "--interval", type=int, help="Override the configured interval in seconds"
    )

    status = subparsers.add_parser("status", help="Show privacy-safe PoC statistics")
    status.add_argument("--hours", type=float, default=48.0)

    subparsers.add_parser(
        "movement-start", help="Start a controlled movement test window"
    )
    subparsers.add_parser(
        "movement-stop", help="Finish the current movement test window"
    )
    subparsers.add_parser(
        "install-agent", help="Install and start the per-user LaunchAgent"
    )
    subparsers.add_parser(
        "uninstall-agent", help="Stop and remove the per-user LaunchAgent"
    )
    subparsers.add_parser("viewer", help="Open the local MapKit trajectory viewer")
    subparsers.add_parser("start", help="Start continuous background recording")
    subparsers.add_parser(
        "stop", help="Stop background recording without deleting history"
    )
    interval = subparsers.add_parser(
        "interval", help="Set the background polling interval"
    )
    interval.add_argument(
        "seconds", type=int, help="Polling interval in seconds (minimum 60)"
    )
    retention = subparsers.add_parser("retention", help=argparse.SUPPRESS)
    retention.add_argument("days", type=int, help="0 keeps history forever")
    clear_history = subparsers.add_parser("clear-history", help=argparse.SUPPRESS)
    clear_history.add_argument("--device-key")
    clear_history.add_argument("--start-ms", type=int)
    clear_history.add_argument("--end-ms", type=int)
    communication = subparsers.add_parser("communications", help=argparse.SUPPRESS)
    communication.add_argument(
        "action", choices=("enable", "disable", "check", "scan", "import")
    )
    clear_communications = subparsers.add_parser(
        "clear-communications", help=argparse.SUPPRESS
    )
    clear_communications.add_argument("--kind", choices=("message", "call"))
    subparsers.add_parser("restore-latest-backup", help=argparse.SUPPRESS)
    subparsers.add_parser("gui-status", help=argparse.SUPPRESS)
    subparsers.add_parser("gui-auth-bridge", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = AppPaths.default()
    try:
        if args.command == "gui-auth-bridge":
            return run_auth_bridge(paths=paths)
        paths.ensure()
        if args.command == "auth":
            return _auth(paths, args.apple_id)
        if args.command == "logout":
            return _logout(paths)
        if args.command == "remove-account":
            return _remove_account(paths, args.apple_id)
        if args.command in {"install-agent", "start"}:
            config = load_config(paths.config)
            if not config.selected_device_keys and not config.communications_enabled:
                raise ConfigurationError(
                    "Select at least one device or enable communications archiving"
                )
            destination = install_agent(paths)
            print(f"LaunchAgent 已启动：{destination}")
            return 0
        if args.command in {"uninstall-agent", "stop"}:
            print("LaunchAgent 已移除" if uninstall_agent() else "LaunchAgent 尚未安装")
            return 0
        if args.command == "viewer":
            return _open_viewer()
        if args.command == "interval":
            config = load_config(paths.config)
            config.interval_seconds = args.seconds
            save_config(paths.config, config)
            restarted = False
            if launch_agent_path().exists():
                install_agent(paths)
                restarted = True
            suffix = "，后台服务已重启" if restarted else ""
            print(f"采集间隔已设为 {args.seconds} 秒{suffix}")
            return 0
        if args.command == "retention":
            if args.days < 0:
                raise ConfigurationError("Retention days cannot be negative")
            config = load_config(paths.config)
            config.retention_days = args.days or None
            save_config(paths.config, config)
            restarted = False
            if launch_agent_path().exists():
                install_agent(paths)
                restarted = True
            suffix = "，后台服务已重启" if restarted else ""
            value = f"{args.days} 天" if args.days else "永久保留"
            print(f"自动保留期限已设为 {value}{suffix}")
            return 0

        config = load_config(paths.config)
        if claim_legacy_database(config, paths.database):
            save_config(paths.config, config)
        crypto = _load_crypto(args.master_key_stdin)
        if args.command == "switch-account":
            return _switch_account(paths, config, crypto, args.apple_id)
        if args.command == "restore-latest-backup":
            if not config.apple_id:
                raise ConfigurationError("请先选择 Apple 账户")
            database_path = paths.location_database(
                config.apple_id, config.legacy_database_account_id
            )
            backup_directory = paths.location_backups(
                config.apple_id, config.legacy_database_account_id
            )
            backup = _latest_backup(backup_directory)
            if backup is None:
                raise ConfigurationError("没有可恢复的备份")
            agent_was_running = launch_agent_path().exists()
            if agent_was_running:
                uninstall_agent()
            try:
                with HistoryDatabase(database_path, crypto) as database:
                    database.create_backup(backup_directory, "before-restore")
                    database.restore_backup(backup)
            finally:
                if agent_was_running:
                    install_agent(paths)
            print(f"已恢复备份：{backup.name}")
            return 0
        location_path = (
            paths.location_database(config.apple_id, config.legacy_database_account_id)
            if config.apple_id
            else None
        )
        communication_path = paths.communications_database(
            config.legacy_database_account_id
        )
        with ExitStack() as databases:
            communication_database = databases.enter_context(
                HistoryDatabase(communication_path, crypto)
            )
            if location_path == communication_path:
                location_database = communication_database
            elif location_path is not None:
                location_database = databases.enter_context(
                    HistoryDatabase(location_path, crypto)
                )
            else:
                location_database = None
            if args.command == "communications":
                source = MacCommunicationSource()
                if args.action == "check":
                    source.check_access()
                    print('{"readable":true}')
                    return 0
                communication_collector = CommunicationCollector(
                    source, communication_database
                )
                if args.action == "enable":
                    imported = communication_collector.import_existing()
                    config.communications_enabled = True
                    save_config(paths.config, config)
                    if launch_agent_path().exists():
                        install_agent(paths)
                    print(f"通讯归档已启用；已导入 {imported} 条现有记录")
                    return 0
                if args.action == "disable":
                    config.communications_enabled = False
                    save_config(paths.config, config)
                    if launch_agent_path().exists():
                        install_agent(paths)
                    print("通讯归档已停止；已有本地归档仍然保留")
                    return 0
                if args.action == "import":
                    imported = communication_collector.import_existing()
                    print(f"已导入 {imported} 条此前未归档的现有记录")
                    return 0
                communication_collector.collect_once()
                print("通讯归档扫描完成")
                return 0
            if args.command == "clear-communications":
                backup = communication_database.create_backup(
                    paths.communications_backups(config.legacy_database_account_id),
                    "before-clear-communications",
                )
                deleted = communication_database.clear_communications(kind=args.kind)
                print(f"已清除 {deleted} 条本地通讯归档；备份：{backup.name}")
                return 0
            if args.command == "clear-history":
                database = _require_location_database(location_database)
                backup = database.create_backup(
                    paths.location_backups(
                        config.apple_id, config.legacy_database_account_id
                    ),
                    "before-clear-history",
                )
                deleted = database.clear_history(
                    device_key=args.device_key,
                    start_ms=args.start_ms,
                    end_ms=args.end_ms,
                )
                print(f"已清除 {deleted['points']} 个轨迹点；备份：{backup.name}")
                return 0
            if args.command == "gui-status":
                communication_report = communication_database.dashboard()
                report = (
                    location_database.dashboard()
                    if location_database is not None
                    else _empty_location_report()
                )
                _merge_communication_status(report, communication_report)
                report["active_account_authenticated"] = (
                    active_account_is_authenticated(config, report)
                )
                report["communications_enabled"] = config.communications_enabled
                report["full_disk_access_granted"] = (
                    MacCommunicationSource().has_access()
                )
                report["database_bytes"] = sum(
                    _database_size(path)
                    for path in {location_path, communication_path}
                    if path is not None
                )
                backups = (
                    _list_backups(
                        paths.location_backups(
                            config.apple_id, config.legacy_database_account_id
                        )
                    )
                    if config.apple_id
                    else []
                )
                report["backup_count"] = len(backups)
                report["latest_backup"] = backups[0] if backups else None
                print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
                return 0
            if args.command == "status":
                return _status(
                    _require_location_database(location_database), config, args.hours
                )
            if args.command == "movement-start":
                session_id = _require_location_database(
                    location_database
                ).start_movement()
                print(f"移动测试 #{session_id} 已开始")
                return 0
            if args.command == "movement-stop":
                session_id = _require_location_database(
                    location_database
                ).stop_movement()
                print(f"移动测试 #{session_id} 已结束")
                return 0

            communication_collector = (
                CommunicationCollector(MacCommunicationSource(), communication_database)
                if config.communications_enabled
                else None
            )
            try:
                provider = ICloudProvider.from_saved_session(
                    config.apple_id, paths.sessions
                )
            except AuthenticationRequired:
                if args.command == "run" and communication_collector is not None:
                    provider = None
                elif args.command == "run":
                    print(
                        "iCloud 会话已失效，请重新运行 ilifetrack auth",
                        file=sys.stderr,
                    )
                    # A clean exit prevents launchd from repeatedly attempting a
                    # non-interactive login with an invalid session.
                    return 0
                raise
            if args.command == "devices":
                assert provider is not None
                return _devices(
                    provider,
                    _require_location_database(location_database),
                    paths,
                    config,
                )
            if args.command == "select":
                assert provider is not None
                return _select(
                    provider,
                    _require_location_database(location_database),
                    paths,
                    config,
                    args.device_keys,
                    args.all,
                )
            collector = (
                Collector(
                    provider,
                    _require_location_database(location_database),
                    config.selected_device_keys,
                    retention_days=config.retention_days,
                    reconcile_selection=lambda available: _reconciled_selection(
                        config, available, paths
                    ),
                )
                if provider is not None
                else None
            )
            if args.command == "once":
                assert collector is not None
                result = collector.collect_once()
                print(
                    f"采集完成：发现 {result.device_count} 台，目标 {result.selected_count} 台，"
                    f"新增 {result.new_points} 个位置点"
                )
                return 0
            if args.command == "run":
                interval = args.interval or config.interval_seconds
                if interval < 60:
                    raise ConfigurationError(
                        "The polling interval must be at least 60 seconds"
                    )
                reason = run_forever(
                    collector,
                    interval,
                    communication_collector=communication_collector,
                )
                if reason == "auth_required":
                    print(
                        "iCloud 会话已失效，请重新运行 ilifetrack auth",
                        file=sys.stderr,
                    )
                return 0
    except AuthenticationRequired:
        print("iCloud 认证无效，请在本机重新运行 ilifetrack auth", file=sys.stderr)
        return 2
    except (ConfigurationError, ILifeTrackError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 1


def _load_crypto(from_stdin: bool) -> CryptoBox:
    if not from_stdin:
        return CryptoBox.load_or_create()
    encoded = sys.stdin.readline().strip()
    try:
        master_key = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ConfigurationError("Invalid session key") from exc
    if len(master_key) != 32:
        raise ConfigurationError("Invalid session key")
    return CryptoBox.from_master_key(master_key)


def _auth(paths: AppPaths, apple_id_argument: str | None) -> int:
    existing: Config | None = None
    try:
        existing = load_config(paths.config)
    except ConfigurationError:
        pass
    apple_id = (
        apple_id_argument
        or (existing.apple_id if existing else "")
        or input("Apple 账户: ")
    ).strip()
    if not apple_id:
        raise ConfigurationError("Apple account is required")
    provider = ICloudProvider.interactive_login(apple_id, paths.sessions)
    crypto = CryptoBox.load_or_create()
    config = existing or Config()
    if claim_legacy_database(config, paths.database):
        save_config(paths.config, config)
    database_path = paths.location_database(
        apple_id, config.legacy_database_account_id
    )
    with HistoryDatabase(database_path, crypto) as database:
        print("认证成功。当前可见设备：")
        available = _refresh_and_print_devices(provider, database, config)
        active_account = activate_account(config, apple_id, available)
        mark_account_verified(config, active_account, int(time.time() * 1000))
        save_config(paths.config, config)
        _reload_agent_for_config(paths, config)
    print("下一步运行：ilifetrack select --all（或指定设备短标识）")
    return 0


def _logout(paths: AppPaths) -> int:
    """Remove the active Apple session without deleting the user's archive."""
    try:
        config = load_config(paths.config)
    except ConfigurationError:
        config = Config()

    if not config.apple_id:
        print("当前没有已认证的 Apple 账户")
        return 0
    return _remove_account(paths, config.apple_id)


def _remove_account(paths: AppPaths, apple_id: str) -> int:
    """Remove one saved Apple session while preserving every local archive."""
    try:
        config = load_config(paths.config)
    except ConfigurationError:
        config = Config()
    active_account = config.apple_id
    if not remove_account(config, apple_id):
        raise ConfigurationError("找不到要移除的 Apple 账户")
    remove_session_files(paths.sessions, apple_id)
    save_config(paths.config, config)

    if active_account.casefold() == apple_id.strip().casefold():
        _reload_agent_for_config(paths, config)

    print("Apple 账户认证已取消；轨迹、通讯归档和加密密钥均已保留")
    return 0


def _switch_account(
    paths: AppPaths,
    config: Config,
    crypto: CryptoBox,
    apple_id: str,
) -> int:
    """Validate and activate one of the locally saved Apple sessions."""
    requested = apple_id.strip()
    account = next(
        (
            item
            for item in configured_accounts(config)
            if item.casefold() == requested.casefold()
        ),
        None,
    )
    if account is None:
        raise ConfigurationError("找不到要切换的 Apple 账户")

    provider = ICloudProvider.from_saved_session(account, paths.sessions)
    now_ms = int(time.time() * 1000)
    devices = provider.fetch_devices(now_ms)
    database_path = paths.location_database(
        account, config.legacy_database_account_id
    )
    with HistoryDatabase(database_path, crypto) as database:
        available = database.sync_devices(devices, now_ms)
    activate_account(config, account, available)
    mark_account_verified(config, account, now_ms)
    save_config(paths.config, config)
    _reload_agent_for_config(paths, config)
    print(f"已切换 Apple 账户：{account}；发现 {len(devices)} 台设备")
    return 0


def _reload_agent_for_config(paths: AppPaths, config: Config) -> None:
    if not launch_agent_path().exists():
        return
    if config.selected_device_keys or config.communications_enabled:
        install_agent(paths)
    else:
        uninstall_agent()


def _require_location_database(
    database: HistoryDatabase | None,
) -> HistoryDatabase:
    if database is None:
        raise ConfigurationError("请先在设置中选择 Apple 账户")
    return database


def _empty_location_report() -> dict[str, object]:
    return {
        "total_points": 0,
        "history_start_ms": None,
        "history_end_ms": None,
        "last_poll_started_ms": None,
        "last_poll_finished_ms": None,
        "last_poll_outcome": None,
        "last_poll_detail": None,
        "last_success_ms": None,
        "last_error_ms": None,
        "last_error_outcome": None,
        "last_error_detail": None,
        "next_expected_poll_ms": None,
        "latest_location_lag_seconds": None,
        "device_statuses": [],
    }


def _merge_communication_status(
    report: dict[str, object], communication_report: dict[str, object]
) -> None:
    for key in (
        "total_communications",
        "message_count",
        "call_count",
        "last_communication_archived_ms",
        "last_communication_scan_ms",
        "last_communication_outcome",
    ):
        report[key] = communication_report[key]


def _devices(
    provider: ICloudProvider,
    database: HistoryDatabase,
    paths: AppPaths,
    config: Config,
) -> int:
    available = _refresh_and_print_devices(provider, database, config)
    removed = _reconcile_selected_devices(config, set(available), paths)
    if removed:
        print(f"已停止记录 {removed} 台不再出现在“查找”中的设备")
    return 0


def _refresh_and_print_devices(
    provider: ICloudProvider, database: HistoryDatabase, config: Config
) -> list[str]:
    now_ms = int(time.time() * 1000)
    devices = provider.fetch_devices(now_ms)
    keys = database.sync_devices(devices, now_ms)
    for device, device_key in zip(devices, keys, strict=True):
        marker = "*" if device_key in config.selected_device_keys else " "
        location_state = "有位置" if device.location else "无位置"
        print(
            f"{marker} {device_key}  {device.device_type}  {device.name}  {location_state}"
        )
    if not devices:
        print("没有发现可查询的设备")
    return keys


def _reconcile_selected_devices(
    config: Config, available_keys: set[str], paths: AppPaths
) -> int:
    previous = config.selected_device_keys
    selected = [key for key in previous if key in available_keys]
    removed = len(previous) - len(selected)
    if removed:
        update_active_selection(config, selected)
        save_config(paths.config, config)
    return removed


def _reconciled_selection(
    config: Config, available_keys: set[str], paths: AppPaths
) -> list[str]:
    _reconcile_selected_devices(config, available_keys, paths)
    return config.selected_device_keys


def _select(
    provider: ICloudProvider,
    database: HistoryDatabase,
    paths: AppPaths,
    config: Config,
    requested_keys: Sequence[str],
    select_all: bool,
) -> int:
    available = _refresh_and_print_devices(provider, database, config)
    if select_all:
        selected = available
    else:
        selected = list(dict.fromkeys(requested_keys))
        unknown = sorted(set(selected) - set(available))
        if unknown:
            raise ConfigurationError(f"Unknown device key: {', '.join(unknown)}")
    update_active_selection(config, selected)
    save_config(paths.config, config)
    print(f"已选择 {len(selected)} 台设备")
    if launch_agent_path().exists():
        if selected or config.communications_enabled:
            install_agent(paths)
            print("后台服务已重启，新设备选择已生效")
        else:
            uninstall_agent()
            print("没有启用中的记录项目，后台服务已停止")
    return 0


def _status(database: HistoryDatabase, config: Config, hours: float) -> int:
    if hours <= 0:
        raise ConfigurationError("Hours must be positive")
    since_ms = int((time.time() - hours * 3600) * 1000)
    report = database.status(since_ms, config.interval_seconds)
    report["window_hours"] = hours
    report["acceptance"] = {
        "poll_success_rate_at_least_95_percent": (
            report["success_rate"] is not None and report["success_rate"] >= 0.95
        ),
        "movement_bins_at_least_80_percent": all(
            item["covered_bin_rate"] >= 0.80 for item in report["movement_sessions"]
        )
        if report["movement_sessions"]
        else None,
        "movement_p95_lag_at_most_10_minutes": all(
            item["p95_location_lag_seconds"] is not None
            and item["p95_location_lag_seconds"] <= 600
            for item in report["movement_sessions"]
        )
        if report["movement_sessions"]
        else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _open_viewer() -> int:
    project_root = Path(__file__).resolve().parents[2]
    app_bundle = project_root / "build" / "iLifeTrack.app"
    if not app_bundle.exists():
        raise ConfigurationError("Run ./viewer/build-app.sh before opening the viewer")
    subprocess.run(["open", str(app_bundle)], check=True)
    print("iLifeTrack 已打开")
    return 0


def _database_size(database_path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in database_path.parent.glob(f"{database_path.name}*")
        if candidate.is_file()
    )


def _list_backups(backup_directory: Path) -> list[dict[str, int | str]]:
    if not backup_directory.exists():
        return []
    result = []
    for backup in sorted(
        backup_directory.glob("*.sqlite3"),
        key=lambda candidate: candidate.stat().st_mtime_ns,
        reverse=True,
    ):
        stat = backup.stat()
        result.append(
            {
                "name": backup.name,
                "created_at_ms": stat.st_mtime_ns // 1_000_000,
                "size_bytes": stat.st_size,
            }
        )
    return result


def _latest_backup(backup_directory: Path) -> Path | None:
    backups = _list_backups(backup_directory)
    return backup_directory / str(backups[0]["name"]) if backups else None


if __name__ == "__main__":
    raise SystemExit(main())
