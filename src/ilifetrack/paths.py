"""Filesystem locations for local state."""

from dataclasses import dataclass
from pathlib import Path

from .accounts import account_storage_id


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
        """Legacy pre-multi-account database path."""
        return self.root / "history.sqlite3"

    def location_database(self, apple_id: str, legacy_account_id: str = "") -> Path:
        if legacy_account_id and account_storage_id(apple_id) == legacy_account_id:
            return self.database
        return self.accounts / account_storage_id(apple_id) / "history.sqlite3"

    def location_backups(self, apple_id: str, legacy_account_id: str = "") -> Path:
        if legacy_account_id and account_storage_id(apple_id) == legacy_account_id:
            return self.backups
        return self.backups / "accounts" / account_storage_id(apple_id)

    def communications_database(self, legacy_account_id: str = "") -> Path:
        return self.database if legacy_account_id else self.root / "communications.sqlite3"

    def communications_backups(self, legacy_account_id: str = "") -> Path:
        return self.backups / "communications"

    @property
    def accounts(self) -> Path:
        return self.root / "accounts"

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
        self.accounts.mkdir(exist_ok=True, mode=0o700)
        self.accounts.chmod(0o700)
