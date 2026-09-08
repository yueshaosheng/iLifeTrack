"""Filesystem locations for local state."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    """All mutable state lives outside the source checkout."""

    root: Path

    @classmethod
    def default(cls) -> "AppPaths":
        return cls(Path.home() / "Library" / "Application Support" / "iLifeTrack")

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def database(self) -> Path:
        return self.root / "history.sqlite3"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.sessions.mkdir(exist_ok=True, mode=0o700)
        self.sessions.chmod(0o700)
        self.logs.mkdir(exist_ok=True, mode=0o700)
        self.logs.chmod(0o700)
        self.backups.mkdir(exist_ok=True, mode=0o700)
        self.backups.chmod(0o700)
