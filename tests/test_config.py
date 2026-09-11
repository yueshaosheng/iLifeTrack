import json
import stat

import pytest

from ilifetrack.config import Config, load_config, save_config
from ilifetrack.errors import ConfigurationError


def test_config_round_trip_and_private_permissions(tmp_path):
    target = tmp_path / "state" / "config.json"
    expected = Config(
        apple_id="user@example.com",
        apple_accounts=["user@example.com"],
        account_device_selections={"user@example.com": ["abc"]},
        account_auth_verified_ms={"user@example.com": 1_700_000_000_000},
        selected_device_keys=["abc"],
    )
    save_config(target, expected)

    assert load_config(target) == expected
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_config_rejects_too_frequent_polling(tmp_path):
    target = tmp_path / "config.json"
    with pytest.raises(ConfigurationError):
        save_config(target, Config(apple_id="user@example.com", interval_seconds=30))


def test_old_config_without_retention_remains_compatible(tmp_path):
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps(
            {
                "version": 1,
                "apple_id": "user@example.com",
                "selected_device_keys": ["abc"],
                "interval_seconds": 300,
            }
        )
    )

    loaded = load_config(target)
    assert loaded.retention_days is None
    assert loaded.communications_enabled is False
    assert loaded.apple_accounts == []
    assert loaded.account_device_selections == {}
    assert loaded.account_auth_verified_ms == {}


def test_config_rejects_invalid_retention(tmp_path):
    with pytest.raises(ConfigurationError):
        save_config(tmp_path / "config.json", Config(retention_days=0))
