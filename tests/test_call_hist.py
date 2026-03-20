"""
Tests for src/call_hist.py — call history discovery, parsing, and CSV output.
"""

import csv
import plistlib
import sqlite3

import pytest

import src.backup as backup
import src.call_hist as call_hist
from src.backup import CORE_DATA_EPOCH_OFFSET


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Core Data timestamps for 3 test calls (stored as Unix - CORE_DATA_EPOCH_OFFSET)
_CALL_DATES_UNIX = [
    1710498120.0,  # 2024-03-15 10:22:00 UTC
    1710498300.0,  # 2024-03-15 10:25:00 UTC
    1710498600.0,  # 2024-03-15 10:30:00 UTC
]
_CALL_DATES_CD = [ts - CORE_DATA_EPOCH_OFFSET for ts in _CALL_DATES_UNIX]

# File ID prefix "dd" — won't collide with mock_backup fixtures
_CH_FILE_ID = "dd" + "a" * 38


@pytest.fixture
def mock_call_history_backup(tmp_dir):
    """Mock backup with a CallHistory.storedata entry."""
    backup_dir = tmp_dir / "CALLHIST_BACKUP"
    backup_dir.mkdir()

    # Manifest.plist
    manifest_data = {"IsEncrypted": False, "Version": "10.0"}
    with open(backup_dir / "Manifest.plist", "wb") as f:
        plistlib.dump(manifest_data, f)

    # Manifest.db
    manifest_db_path = backup_dir / "Manifest.db"
    conn = sqlite3.connect(str(manifest_db_path))
    conn.execute(
        """CREATE TABLE Files (
            fileID TEXT PRIMARY KEY,
            domain TEXT,
            relativePath TEXT,
            flags INTEGER,
            file BLOB
        )"""
    )
    conn.execute(
        "INSERT INTO Files VALUES (?,?,?,?,?)",
        (
            _CH_FILE_ID,
            "HomeDomain",
            "Library/CallHistoryDB/CallHistory.storedata",
            1,
            None,
        ),
    )
    conn.commit()
    conn.close()

    # CallHistory.storedata — a real SQLite with ZCALLRECORD
    bucket = backup_dir / _CH_FILE_ID[:2]
    bucket.mkdir(exist_ok=True)
    ch_db_path = bucket / _CH_FILE_ID
    ch_conn = sqlite3.connect(str(ch_db_path))
    ch_conn.execute(
        """CREATE TABLE ZCALLRECORD (
            Z_PK INTEGER PRIMARY KEY,
            ZDATE REAL,
            ZDURATION REAL,
            ZADDRESS TEXT,
            ZNAME TEXT,
            ZLOCATION TEXT,
            ZORIGINATED INTEGER,
            ZCALLTYPE INTEGER,
            ZANSWERED INTEGER,
            ZREAD INTEGER,
            ZJUNKCONFIDENCE REAL,
            ZWASEMERGENCYCALL INTEGER,
            ZSERVICE_PROVIDER TEXT,
            ZUNIQUE_ID TEXT
        )"""
    )
    # Row 1: outgoing phone call, answered, has name
    ch_conn.execute(
        "INSERT INTO ZCALLRECORD VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            1,
            _CALL_DATES_CD[0],
            45.0,
            "+15551234567",
            "Alice",
            "New York",
            1,
            1,
            1,
            1,
            0.0,
            0,
            "carrier_a",
            "uuid-001",
        ),
    )
    # Row 2: incoming FaceTime Audio, missed (answered=0), NULL name
    ch_conn.execute(
        "INSERT INTO ZCALLRECORD VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            2,
            _CALL_DATES_CD[1],
            0.0,
            "+15559876543",
            None,
            "Los Angeles",
            0,
            8,
            0,
            0,
            0.0,
            0,
            "carrier_b",
            "uuid-002",
        ),
    )
    # Row 3: outgoing FaceTime Video, NULL location
    ch_conn.execute(
        "INSERT INTO ZCALLRECORD VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            3,
            _CALL_DATES_CD[2],
            120.0,
            "+15550001111",
            "Bob",
            None,
            1,
            16,
            1,
            1,
            0.0,
            0,
            None,
            "uuid-003",
        ),
    )
    ch_conn.commit()
    ch_conn.close()

    return backup_dir


# ---------------------------------------------------------------------------
# Test: call history
# ---------------------------------------------------------------------------


class TestCallHistory:
    def test_find_call_history_db(self, mock_call_history_backup):
        conn, _, _ = backup.open_manifest_db(mock_call_history_backup)
        file_id, rel_path = call_hist.find_call_history_db(conn)
        conn.close()
        assert file_id == _CH_FILE_ID
        assert rel_path == "Library/CallHistoryDB/CallHistory.storedata"

    def test_find_call_history_db_absent(self, tmp_dir):
        empty_db = tmp_dir / "empty_manifest.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute(
            """CREATE TABLE Files (
                fileID TEXT, domain TEXT, relativePath TEXT,
                flags INTEGER, file BLOB
            )"""
        )
        conn.commit()
        file_id, rel_path = call_hist.find_call_history_db(conn)
        conn.close()
        assert file_id is None
        assert rel_path is None

    def test_parse_call_history(self, mock_call_history_backup):
        ch_db_path = mock_call_history_backup / _CH_FILE_ID[:2] / _CH_FILE_ID
        calls = call_hist.parse_call_history(ch_db_path)
        assert len(calls) == 3

        # Row 1: outgoing phone, answered
        c1 = next(c for c in calls if c["rowid"] == 1)
        assert c1["call_type"] == "phone"
        assert c1["direction"] == "outgoing"
        assert c1["answered"] == "yes"
        assert c1["name"] == "Alice"
        assert "2024-03-15" in c1["date_str"]

        # Row 2: incoming FaceTime Audio, missed, NULL name → ""
        c2 = next(c for c in calls if c["rowid"] == 2)
        assert c2["call_type"] == "facetime_audio"
        assert c2["direction"] == "incoming"
        assert c2["answered"] == "no"
        assert c2["name"] == ""

        # Row 3: outgoing FaceTime Video, NULL location → ""
        c3 = next(c for c in calls if c["rowid"] == 3)
        assert c3["call_type"] == "facetime_video"
        assert c3["location"] == ""

    def test_parse_call_history_missing_columns(self, tmp_dir):
        """Minimal schema (just Z_PK, ZDATE, ZADDRESS) — no KeyError, absent cols → ""."""
        minimal_db = tmp_dir / "minimal_ch.db"
        conn = sqlite3.connect(str(minimal_db))
        conn.execute(
            "CREATE TABLE ZCALLRECORD (Z_PK INTEGER PRIMARY KEY, ZDATE REAL, ZADDRESS TEXT)"
        )
        conn.execute(
            "INSERT INTO ZCALLRECORD VALUES (?,?,?)",
            (1, _CALL_DATES_CD[0], "+15550000000"),
        )
        conn.commit()
        conn.close()

        calls = call_hist.parse_call_history(minimal_db)
        assert len(calls) == 1
        c = calls[0]
        assert c["address"] == "+15550000000"
        assert c["name"] == ""
        assert c["call_type"] == ""
        assert c["direction"] == ""
        assert c["answered"] == ""

    def test_parse_call_history_no_table(self, tmp_dir):
        """No ZCALLRECORD table → returns []."""
        empty_db = tmp_dir / "empty_ch.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("CREATE TABLE SOMETHING_ELSE (id INTEGER)")
        conn.commit()
        conn.close()

        calls = call_hist.parse_call_history(empty_db)
        assert calls == []

    def test_write_calls_csv(self, tmp_dir):
        """Verify file created, all 14 columns present, index sequential, spot-check values."""
        calls = [
            {
                "rowid": 1,
                "date_str": "2024-03-15 10:22:00 UTC",
                "duration": 45.0,
                "call_type": "phone",
                "direction": "outgoing",
                "answered": "yes",
                "address": "+15551234567",
                "name": "Alice",
                "location": "New York",
                "service_provider": "carrier_a",
                "spam_score": 0.0,
                "was_emergency": 0,
                "read": 1,
            },
            {
                "rowid": 2,
                "date_str": "2024-03-15 10:25:00 UTC",
                "duration": 0.0,
                "call_type": "facetime_audio",
                "direction": "incoming",
                "answered": "no",
                "address": "+15559876543",
                "name": "",
                "location": "Los Angeles",
                "service_provider": "carrier_b",
                "spam_score": 0.0,
                "was_emergency": 0,
                "read": 0,
            },
        ]
        output_dir = tmp_dir / "calls_out"
        output_dir.mkdir()
        csv_path = call_hist.write_calls_csv(calls, output_dir)

        assert csv_path.exists()
        assert csv_path.name == "calls.csv"

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        expected_cols = {
            "index",
            "date",
            "duration",
            "call_type",
            "direction",
            "answered",
            "address",
            "name",
            "location",
            "service_provider",
            "spam_score",
            "was_emergency",
            "read",
            "rowid",
        }
        assert expected_cols == set(rows[0].keys())

        # Sequential index
        assert rows[0]["index"] == "1"
        assert rows[1]["index"] == "2"

        # Spot-check
        assert rows[0]["call_type"] == "phone"
        assert rows[0]["name"] == "Alice"
        assert rows[1]["answered"] == "no"
