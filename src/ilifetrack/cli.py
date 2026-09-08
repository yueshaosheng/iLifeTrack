"""Command-line interface for setup and the 48-hour proof of concept."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

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
        crypto = _load_crypto(args.master_key_stdin)
        if args.command == "restore-latest-backup":
            backup = _latest_backup(paths.backups)
            if backup is None:
                raise ConfigurationError("没有可恢复的备份")
            agent_was_running = launch_agent_path().exists()
            if agent_was_running:
                uninstall_agent()
            try:
                with HistoryDatabase(paths.database, crypto) as database:
                    database.create_backup(paths.backups, "before-restore")
                    database.restore_backup(backup)
            finally:
                if agent_was_running:
                    install_agent(paths)
            print(f"已恢复备份：{backup.name}")
            return 0
        with HistoryDatabase(paths.database, crypto) as database:
            if args.command == "communications":
                source = MacCommunicationSource()
                if args.action == "check":
                    source.check_access()
                    print('{"readable":true}')
                    return 0
                communication_collector = CommunicationCollector(source, database)
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
                backup = database.create_backup(
                    paths.backups, "before-clear-communications"
                )
                deleted = database.clear_communications(kind=args.kind)
                print(f"已清除 {deleted} 条本地通讯归档；备份：{backup.name}")
                return 0
            if args.command == "clear-history":
                backup = database.create_backup(paths.backups, "before-clear-history")
                deleted = database.clear_history(
                    device_key=args.device_key,
                    start_ms=args.start_ms,
                    end_ms=args.end_ms,
                )
                print(f"已清除 {deleted['points']} 个轨迹点；备份：{backup.name}")
                return 0
            if args.command == "gui-status":
                report = database.dashboard()
                report["communications_enabled"] = config.communications_enabled
                report["full_disk_access_granted"] = (
                    MacCommunicationSource().has_access()
                )
                report["database_bytes"] = _database_size(paths.database)
                backups = _list_backups(paths.backups)
                report["backup_count"] = len(backups)
                report["latest_backup"] = backups[0] if backups else None
                print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
                return 0
            if args.command == "status":
                return _status(database, config, args.hours)
            if args.command == "movement-start":
                session_id = database.start_movement()
                print(f"移动测试 #{session_id} 已开始")
                return 0
            if args.command == "movement-stop":
                session_id = database.stop_movement()
                print(f"移动测试 #{session_id} 已结束")
                return 0

            communication_collector = (
                CommunicationCollector(MacCommunicationSource(), database)
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
                return _devices(provider, database, paths, config)
            if args.command == "select":
                assert provider is not None
                return _select(
                    provider, database, paths, config, args.device_keys, args.all
                )
            collector = (
                Collector(
                    provider,
                    database,
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
    config.apple_id = apple_id
    save_config(paths.config, config)
    with HistoryDatabase(paths.database, crypto) as database:
        print("认证成功。当前可见设备：")
        available = _refresh_and_print_devices(provider, database, config)
        _reconcile_selected_devices(config, set(available), paths)
    print("下一步运行：ilifetrack select --all（或指定设备短标识）")
    return 0


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
        config.selected_device_keys = selected
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
    config.selected_device_keys = selected
    save_config(paths.config, config)
    print(f"已选择 {len(selected)} 台设备")
    if launch_agent_path().exists():
        install_agent(paths)
        print("后台服务已重启，新设备选择已生效")
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
