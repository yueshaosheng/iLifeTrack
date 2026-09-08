"""Small non-secret configuration file."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import ConfigurationError


@dataclass
class Config:
    version: int = 1
    apple_id: str = ""
    selected_device_keys: list[str] = field(default_factory=list)
    interval_seconds: int = 300
    retention_days: int | None = None
    communications_enabled: bool = False

    def validate(self) -> None:
        if self.version != 1:
            raise ConfigurationError(
                f"Unsupported configuration version: {self.version}"
            )
        if self.interval_seconds < 60:
            raise ConfigurationError("The polling interval must be at least 60 seconds")
        if self.retention_days is not None and self.retention_days < 1:
            raise ConfigurationError("Retention days must be positive or null")


def load_config(config_path: Path) -> Config:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError("Run `ilifetrack auth` first") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("The local configuration cannot be read") from exc
    try:
        config = Config(**payload)
    except TypeError as exc:
        raise ConfigurationError(
            "The local configuration has an invalid shape"
        ) from exc
    config.validate()
    return config


def save_config(config_path: Path, config: Config) -> None:
    config.validate()
    config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".config-", suffix=".json", dir=config_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(asdict(config), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary_path.chmod(0o600)
        os.replace(temporary_path, config_path)
        config_path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)
