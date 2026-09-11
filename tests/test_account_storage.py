from ilifetrack.accounts import account_storage_id, claim_legacy_database
from ilifetrack.config import Config
from ilifetrack.paths import AppPaths


def test_each_account_uses_a_distinct_location_database(tmp_path):
    paths = AppPaths(tmp_path / "state")

    first = paths.location_database("first@example.com")
    second = paths.location_database("second@example.com")

    assert first != second
    assert first.name == "history.sqlite3"
    assert second.name == "history.sqlite3"
    assert first.parent.parent == paths.accounts
    assert second.parent.parent == paths.accounts
    assert account_storage_id("FIRST@example.com") == account_storage_id(
        "first@example.com"
    )


def test_existing_database_is_claimed_by_the_original_account(tmp_path):
    paths = AppPaths(tmp_path / "state")
    paths.ensure()
    paths.database.write_bytes(b"legacy database")
    config = Config(apple_id="original@example.com")

    assert claim_legacy_database(config, paths.database) is True
    assert config.legacy_database_account_id == account_storage_id(
        "original@example.com"
    )
    assert (
        paths.location_database(
            "original@example.com", config.legacy_database_account_id
        )
        == paths.database
    )
    assert (
        paths.location_database(
            "another@example.com", config.legacy_database_account_id
        )
        != paths.database
    )
    assert (
        paths.communications_database(config.legacy_database_account_id)
        == paths.database
    )
    assert paths.communications_backups(config.legacy_database_account_id) == (
        paths.backups / "communications"
    )


def test_fresh_install_keeps_communications_outside_account_databases(tmp_path):
    paths = AppPaths(tmp_path / "state")

    assert paths.communications_database() == paths.root / "communications.sqlite3"
    assert paths.communications_database() != paths.location_database(
        "person@example.com"
    )
