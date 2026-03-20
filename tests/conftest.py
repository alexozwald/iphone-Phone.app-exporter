"""
Shared pytest fixtures for iPhone backup test suite.
"""

import plistlib
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.backup import CORE_DATA_EPOCH_OFFSET


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="vm_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_backup(tmp_dir):
    """Create a minimal unencrypted mock backup structure."""
    backup_dir = tmp_dir / "AABBCCDD1122"
    backup_dir.mkdir()

    # --- Manifest.plist (unencrypted) ---
    manifest_data = {
        "IsEncrypted": False,
        "BackupKeyBag": b"",
        "Version": "10.0",
    }
    with open(backup_dir / "Manifest.plist", "wb") as f:
        plistlib.dump(manifest_data, f)

    # --- Info.plist ---
    info_data = {
        "Device Name": "Test iPhone",
        "Product Type": "iPhone14,2",
        "Unique Identifier": "AABBCCDD1122",
        "Last Backup Date": datetime(2024, 3, 15, 10, 22, 0, tzinfo=timezone.utc),
    }
    with open(backup_dir / "Info.plist", "wb") as f:
        plistlib.dump(info_data, f)

    # --- Manifest.db ---
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
    # Two voicemail audio files
    conn.execute(
        "INSERT INTO Files VALUES (?,?,?,?,?)",
        (
            "aabbccdd1111111111111111111111111111111111",
            "HomeDomain",
            "Library/Voicemail/1.amr",
            1,
            None,
        ),
    )
    conn.execute(
        "INSERT INTO Files VALUES (?,?,?,?,?)",
        (
            "bbccddee2222222222222222222222222222222222",
            "HomeDomain",
            "Library/Voicemail/2.amr",
            1,
            None,
        ),
    )
    # voicemail.db entry
    conn.execute(
        "INSERT INTO Files VALUES (?,?,?,?,?)",
        (
            "ccddee003333333333333333333333333333333333",
            "HomeDomain",
            "Library/Voicemail/voicemail.db",
            1,
            None,
        ),
    )
    conn.commit()
    conn.close()

    # --- Actual audio stub files in backup structure ---
    for file_id, filename in [
        ("aabbccdd1111111111111111111111111111111111", "1.amr"),
        ("bbccddee2222222222222222222222222222222222", "2.amr"),
    ]:
        bucket = backup_dir / file_id[:2]
        bucket.mkdir(exist_ok=True)
        (bucket / file_id).write_bytes(b"#!AMR\x00" * 10)  # fake AMR data

    # --- voicemail.db ---
    vm_db_bucket = backup_dir / "cc"
    vm_db_bucket.mkdir(exist_ok=True)
    vm_db_path = vm_db_bucket / "ccddee003333333333333333333333333333333333"
    vm_conn = sqlite3.connect(str(vm_db_path))
    vm_conn.execute(
        """CREATE TABLE voicemail (
            ROWID INTEGER PRIMARY KEY,
            sender TEXT,
            callback_num TEXT,
            date REAL,
            duration REAL,
            flags INTEGER,
            label TEXT
        )"""
    )
    # Unix timestamp: 2024-03-15 10:22:00 UTC = 1710498120
    vm_conn.execute(
        "INSERT INTO voicemail VALUES (?,?,?,?,?,?,?)",
        (1, "+15551234567", "+15551234567", 1710498120.0, 30.5, 0, None),
    )
    # Core Data timestamp: seconds since 2001-01-01
    core_data_ts = 1710498120.0 - CORE_DATA_EPOCH_OFFSET
    vm_conn.execute(
        "INSERT INTO voicemail VALUES (?,?,?,?,?,?,?)",
        (2, "+15559876543", "+15559876543", core_data_ts, 60.0, 0, "Saved"),
    )
    vm_conn.commit()
    vm_conn.close()

    return backup_dir
