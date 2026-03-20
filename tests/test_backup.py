"""
Tests for src/backup.py — backup discovery, info parsing, encryption detection,
timestamp conversion, and file extraction.
"""

import plistlib

import pytest

import src.backup as backup


# ---------------------------------------------------------------------------
# Test: backup discovery
# ---------------------------------------------------------------------------


class TestFindBackups:
    def test_finds_backup_by_direct_path(self, mock_backup):
        result = backup.find_backups(custom_path=str(mock_backup))
        assert len(result) == 1
        assert result[0] == mock_backup

    def test_finds_backup_in_parent_dir(self, mock_backup):
        parent = mock_backup.parent
        result = backup.find_backups(custom_path=str(parent))
        assert mock_backup in result

    def test_nonexistent_path_exits(self, tmp_dir):
        with pytest.raises(SystemExit):
            backup.find_backups(custom_path=str(tmp_dir / "does_not_exist"))

    def test_empty_dir_exits(self, tmp_dir):
        empty = tmp_dir / "empty_backup_dir"
        empty.mkdir()
        with pytest.raises(SystemExit):
            backup.find_backups(custom_path=str(empty))


# ---------------------------------------------------------------------------
# Test: backup info parsing
# ---------------------------------------------------------------------------


class TestGetBackupInfo:
    def test_parses_info_plist(self, mock_backup):
        info = backup.get_backup_info(mock_backup)
        assert info["device_name"] == "Test iPhone"
        assert info["product_type"] == "iPhone14,2"
        assert info["udid"] == "AABBCCDD1122"
        assert "2024-03-15" in info["last_backup"]

    def test_missing_info_plist_returns_defaults(self, tmp_dir):
        empty_backup = tmp_dir / "no_info"
        empty_backup.mkdir()
        info = backup.get_backup_info(empty_backup)
        assert info["device_name"] == "Unknown Device"


# ---------------------------------------------------------------------------
# Test: encrypted detection
# ---------------------------------------------------------------------------


class TestIsEncrypted:
    def test_unencrypted_backup(self, mock_backup):
        assert backup.is_encrypted(mock_backup) is False

    def test_encrypted_backup(self, tmp_dir):
        enc_backup = tmp_dir / "encrypted"
        enc_backup.mkdir()
        manifest_data = {"IsEncrypted": True}
        with open(enc_backup / "Manifest.plist", "wb") as f:
            plistlib.dump(manifest_data, f)
        assert backup.is_encrypted(enc_backup) is True

    def test_missing_manifest_returns_false(self, tmp_dir):
        no_manifest = tmp_dir / "no_manifest"
        no_manifest.mkdir()
        assert backup.is_encrypted(no_manifest) is False


# ---------------------------------------------------------------------------
# Test: timestamp conversion
# ---------------------------------------------------------------------------


class TestConvertTimestamp:
    def test_unix_timestamp(self):
        # 2024-03-15 10:22:00 UTC
        result = backup.convert_timestamp(1710498120.0)
        assert "2024-03-15" in result
        assert "UTC" in result

    def test_core_data_timestamp(self):
        # Same date but Core Data epoch offset
        core_data_ts = 1710498120.0 - backup.CORE_DATA_EPOCH_OFFSET
        result = backup.convert_timestamp(core_data_ts)
        assert "2024-03-15" in result
        assert "UTC" in result

    def test_zero_returns_empty(self):
        assert backup.convert_timestamp(0) == ""

    def test_none_returns_empty(self):
        assert backup.convert_timestamp(None) == ""

    def test_negative_returns_empty(self):
        assert backup.convert_timestamp(-1) == ""


# ---------------------------------------------------------------------------
# Test: file extraction
# ---------------------------------------------------------------------------


class TestExtractFile:
    def test_extracts_existing_file(self, mock_backup, tmp_dir):
        file_id = "aabbccdd1111111111111111111111111111111111"
        dest = tmp_dir / "output.amr"
        result = backup.extract_file(mock_backup, file_id, dest)
        assert result is True
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_missing_file_returns_false(self, mock_backup, tmp_dir):
        dest = tmp_dir / "output.amr"
        result = backup.extract_file(mock_backup, "0" * 40, dest)
        assert result is False
