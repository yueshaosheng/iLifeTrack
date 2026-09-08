import sqlite3

from lifetrack.communications import CommunicationCollector, MacCommunicationSource
from lifetrack.crypto import CryptoBox
from lifetrack.database import HistoryDatabase


def create_messages_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
                subject TEXT, date INTEGER, is_from_me INTEGER, service TEXT,
                cache_has_attachments INTEGER, handle_id INTEGER
            );
            CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
            CREATE TABLE chat (
                ROWID INTEGER PRIMARY KEY, display_name TEXT, chat_identifier TEXT
            );
            CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
            INSERT INTO handle VALUES (1, 'baseline@example.test');
            INSERT INTO message VALUES (
                1, 'baseline-message', 'old', NULL, NULL, 700000000000000000,
                0, 'iMessage', 0, 1
            );
            """
        )


def create_calls_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE ZCALLRECORD (
                Z_PK INTEGER PRIMARY KEY, ZUNIQUE_ID TEXT, ZDATE REAL,
                ZDURATION REAL, ZORIGINATED INTEGER, ZANSWERED INTEGER,
                ZADDRESS TEXT, ZNAME TEXT, ZSERVICE_PROVIDER TEXT, ZCALLTYPE INTEGER
            );
            INSERT INTO ZCALLRECORD VALUES (
                1, 'baseline-call', 700000000, 20, 0, 1,
                'baseline-number', 'Baseline', 'Phone', 1
            );
            """
        )


def test_collector_only_archives_records_seen_after_enable_and_encrypts_payload(tmp_path):
    messages = tmp_path / "chat.db"
    calls = tmp_path / "CallHistory.storedata"
    create_messages_database(messages)
    create_calls_database(calls)
    source = MacCommunicationSource(messages, calls)
    box = CryptoBox.from_master_key(b"m" * 32)
    archive_path = tmp_path / "history.sqlite3"

    with HistoryDatabase(archive_path, box) as database:
        collector = CommunicationCollector(source, database)
        assert collector.initialize_from_now() == {"messages": 1, "calls": 1}

        with sqlite3.connect(messages) as connection:
            connection.execute("INSERT INTO handle VALUES (2, ?)", ("new@example.test",))
            connection.execute(
                "INSERT INTO message VALUES (?, ?, ?, NULL, NULL, ?, 0, ?, 0, 2)",
                (2, "new-message", "private message body", 700000001000000000, "SMS"),
            )
        with sqlite3.connect(calls) as connection:
            connection.execute(
                "INSERT INTO ZCALLRECORD VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?, 1)",
                (
                    2,
                    "new-call",
                    700000001,
                    65,
                    "private-number",
                    "Private Name",
                    "Phone",
                ),
            )

        assert collector.collect_once() == 2
        assert collector.collect_once() == 0
        dashboard = database.dashboard()
        assert dashboard["total_communications"] == 2
        assert dashboard["message_count"] == 1
        assert dashboard["call_count"] == 1
        assert dashboard["last_communication_outcome"] == "success"

    raw_archive = archive_path.read_bytes()
    assert b"private message body" not in raw_archive
    assert b"private-number" not in raw_archive
    assert b"Private Name" not in raw_archive
    assert b"new-message" not in raw_archive


def test_clear_communications_does_not_change_source_cursors(tmp_path):
    messages = tmp_path / "chat.db"
    calls = tmp_path / "CallHistory.storedata"
    create_messages_database(messages)
    create_calls_database(calls)
    source = MacCommunicationSource(messages, calls)
    box = CryptoBox.from_master_key(b"z" * 32)

    with HistoryDatabase(tmp_path / "history.sqlite3", box) as database:
        collector = CommunicationCollector(source, database)
        collector.initialize_from_now()
        assert database.clear_communications() == 0
        assert database.communication_cursor("messages") == 1
        assert database.communication_cursor("calls") == 1


def test_has_access_reflects_whether_both_system_databases_are_readable(tmp_path):
    messages = tmp_path / "chat.db"
    calls = tmp_path / "CallHistory.storedata"
    create_messages_database(messages)
    create_calls_database(calls)

    assert MacCommunicationSource(messages, calls).has_access() is True
    assert MacCommunicationSource(messages, tmp_path / "missing.db").has_access() is False


def test_import_existing_archives_all_available_records_and_deduplicates(tmp_path):
    messages = tmp_path / "chat.db"
    calls = tmp_path / "CallHistory.storedata"
    create_messages_database(messages)
    create_calls_database(calls)
    source = MacCommunicationSource(messages, calls)
    box = CryptoBox.from_master_key(b"i" * 32)

    with HistoryDatabase(tmp_path / "history.sqlite3", box) as database:
        collector = CommunicationCollector(source, database)
        assert collector.import_existing() == 2
        assert collector.import_existing() == 0
        dashboard = database.dashboard()

    assert dashboard["message_count"] == 1
    assert dashboard["call_count"] == 1
