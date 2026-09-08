"""Install or remove the per-user launchd job."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .paths import AppPaths

LABEL = "com.lifetrack.app"


def current_executable() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.executable).parent / "lifetrack"


def service_program_arguments() -> list[str]:
    executable = current_executable()
    if getattr(sys, "frozen", False):
        for parent in executable.parents:
            if parent.suffix == ".app":
                app_executable = parent / "Contents" / "MacOS" / "LifeTrack"
                if app_executable.exists():
                    return [str(app_executable), "--background-service"]
    return [str(executable), "run"]


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install(paths: AppPaths) -> Path:
    paths.ensure()
    for log_name in ("collector.log", "collector-error.log"):
        log_path = paths.logs / log_name
        log_path.touch(mode=0o600, exist_ok=True)
        log_path.chmod(0o600)
    executable = current_executable()
    if not executable.exists():
        raise RuntimeError("Install the project into its virtual environment first")
    destination = launch_agent_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LABEL,
        "ProgramArguments": service_program_arguments(),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 300,
        "ProcessType": "Background",
        "StandardOutPath": str(paths.logs / "collector.log"),
        "StandardErrorPath": str(paths.logs / "collector-error.log"),
    }
    temporary = destination.with_suffix(".plist.tmp")
    with temporary.open("wb") as stream:
        plistlib.dump(payload, stream, sort_keys=True)
    temporary.chmod(0o600)
    temporary.replace(destination)
    destination.chmod(0o600)

    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(destination)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
    return destination


def uninstall() -> bool:
    destination = launch_agent_path()
    if not destination.exists():
        return False
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(destination)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    destination.unlink()
    return True
