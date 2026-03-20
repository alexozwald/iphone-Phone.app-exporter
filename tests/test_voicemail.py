"""
Tests for src/voicemail.py — Manifest.db queries, metadata parsing,
matching, filename generation, export pipeline, and CSV output.
"""

import csv
import sqlite3
from unittest.mock import patch


import src.backup as backup
import src.voicemail as voicemail


# ---------------------------------------------------------------------------
# Test: Manifest.db queries
# ---------------------------------------------------------------------------


class TestManifestDb:
    def test_find_voicemail_files(self, mock_backup):
        conn, _, _ = backup.open_manifest_db(mock_backup)
        files = voicemail.find_voicemail_files(conn)
        conn.close()
        assert len(files) == 2
        filenames = {f["filename"] for f in files}
        assert "1" in filenames
        assert "2" in filenames

    def test_find_voicemail_db(self, mock_backup):
        conn, _, _ = backup.open_manifest_db(mock_backup)
        file_id, rel_path = voicemail.find_voicemail_db(conn)
        conn.close()
        assert file_id == "ccddee003333333333333333333333333333333333"
        assert rel_path == "Library/Voicemail/voicemail.db"

    def test_find_voicemail_files_empty_backup(self, tmp_dir):
        empty_db = tmp_dir / "empty_manifest.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute(
            """CREATE TABLE Files (
                fileID TEXT, domain TEXT, relativePath TEXT,
                flags INTEGER, file BLOB
            )"""
        )
        conn.commit()
        files = voicemail.find_voicemail_files(conn)
        conn.close()
        assert files == []


# ---------------------------------------------------------------------------
# Test: metadata parsing
# ---------------------------------------------------------------------------


class TestParseVoicemailMetadata:
    def test_parses_both_rows(self, mock_backup):
        vm_db_path = mock_backup / "cc" / "ccddee003333333333333333333333333333333333"
        metadata = voicemail.parse_voicemail_metadata(vm_db_path)
        assert len(metadata) == 2

        row1 = next(m for m in metadata if m["rowid"] == 1)
        assert row1["sender"] == "+15551234567"
        assert "2024-03-15" in row1["date_str"]

        row2 = next(m for m in metadata if m["rowid"] == 2)
        assert row2["sender"] == "+15559876543"
        assert row2["label"] == "Saved"
        # Core Data timestamp should resolve to same date
        assert "2024-03-15" in row2["date_str"]


# ---------------------------------------------------------------------------
# Test: matching
# ---------------------------------------------------------------------------


class TestMatchVoicemails:
    def test_matches_by_rowid(self):
        audio_files = [
            {
                "file_id": "aaa",
                "relative_path": "Library/Voicemail/1.amr",
                "filename": "1",
            },
            {
                "file_id": "bbb",
                "relative_path": "Library/Voicemail/2.amr",
                "filename": "2",
            },
        ]
        metadata = [
            {
                "rowid": 1,
                "sender": "+15551234567",
                "date_str": "2024-03-15 10:22:00 UTC",
                "duration": 30.5,
                "date": 1710498120.0,
            },
            {
                "rowid": 2,
                "sender": "+15559876543",
                "date_str": "2024-03-15 10:25:00 UTC",
                "duration": 60.0,
                "date": 1710498300.0,
            },
        ]
        matched = voicemail.match_voicemails(audio_files, metadata)
        assert len(matched) == 2
        senders = {m.get("sender") for m in matched}
        assert "+15551234567" in senders
        assert "+15559876543" in senders

    def test_unmatched_audio_included(self):
        audio_files = [
            {
                "file_id": "aaa",
                "relative_path": "Library/Voicemail/99.amr",
                "filename": "99",
            },
        ]
        metadata = []
        matched = voicemail.match_voicemails(audio_files, metadata)
        assert len(matched) == 1
        assert matched[0]["file_id"] == "aaa"

    def test_metadata_without_audio_included(self):
        audio_files = []
        metadata = [
            {
                "rowid": 5,
                "sender": "+15550000000",
                "date_str": "",
                "duration": 10.0,
                "date": None,
            },
        ]
        matched = voicemail.match_voicemails(audio_files, metadata)
        assert len(matched) == 1
        assert matched[0]["rowid"] == 5
        assert matched[0]["file_id"] is None


# ---------------------------------------------------------------------------
# Test: filename generation
# ---------------------------------------------------------------------------


class TestMakeOutputFilename:
    def test_basic_filename(self):
        entry = {
            "date_str": "2024-03-15 10:22:00 UTC",
            "sender": "+15551234567",
        }
        name = voicemail.make_output_filename(entry, 1)
        assert name == "001_2024-03-15_+15551234567.amr"

    def test_unknown_sender(self):
        entry = {"date_str": "", "sender": None, "callback_num": None}
        name = voicemail.make_output_filename(entry, 3, fmt="mp3")
        assert name.startswith("003_")
        assert name.endswith(".mp3")
        assert "unknown" in name

    def test_sanitizes_special_chars(self):
        entry = {"date_str": "2024-03-15 10:22:00 UTC", "sender": "+1 (555) 123-4567"}
        name = voicemail.make_output_filename(entry, 2)
        assert "/" not in name
        assert " " not in name

    def test_format_extension(self):
        entry = {"date_str": "2024-01-01 00:00:00 UTC", "sender": "+1"}
        assert voicemail.make_output_filename(entry, 1, fmt="wav").endswith(".wav")
        assert voicemail.make_output_filename(entry, 1, fmt="mp3").endswith(".mp3")


# ---------------------------------------------------------------------------
# Test: full export pipeline
# ---------------------------------------------------------------------------


class TestExportVoicemails:
    def test_exports_files(self, mock_backup, tmp_dir):
        conn, _, _ = backup.open_manifest_db(mock_backup)
        audio_files = voicemail.find_voicemail_files(conn)
        conn.close()

        vm_db_path = mock_backup / "cc" / "ccddee003333333333333333333333333333333333"
        metadata = voicemail.parse_voicemail_metadata(vm_db_path)
        matched = voicemail.match_voicemails(audio_files, metadata)

        output_dir = tmp_dir / "export"
        exported = voicemail.export_voicemails(matched, output_dir, mock_backup)

        assert output_dir.exists()
        exported_files = [e for e in exported if e.get("output_file")]
        assert len(exported_files) == 2

    def test_writes_csv(self, mock_backup, tmp_dir):
        conn, _, _ = backup.open_manifest_db(mock_backup)
        audio_files = voicemail.find_voicemail_files(conn)
        conn.close()

        vm_db_path = mock_backup / "cc" / "ccddee003333333333333333333333333333333333"
        metadata = voicemail.parse_voicemail_metadata(vm_db_path)
        matched = voicemail.match_voicemails(audio_files, metadata)

        output_dir = tmp_dir / "export_csv"
        exported = voicemail.export_voicemails(matched, output_dir, mock_backup)
        csv_path = voicemail.write_csv(exported, output_dir)

        assert csv_path.exists()
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(exported)
        # Verify expected columns exist
        for col in ("index", "output_file", "sender", "date", "duration"):
            assert col in rows[0]

    def test_csv_has_correct_sender(self, mock_backup, tmp_dir):
        conn, _, _ = backup.open_manifest_db(mock_backup)
        audio_files = voicemail.find_voicemail_files(conn)
        conn.close()

        vm_db_path = mock_backup / "cc" / "ccddee003333333333333333333333333333333333"
        metadata = voicemail.parse_voicemail_metadata(vm_db_path)
        matched = voicemail.match_voicemails(audio_files, metadata)

        output_dir = tmp_dir / "export_sender"
        exported = voicemail.export_voicemails(matched, output_dir, mock_backup)
        csv_path = voicemail.write_csv(exported, output_dir)

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        senders = {r["sender"] for r in rows if r["sender"]}
        assert "+15551234567" in senders or "+15559876543" in senders


# ---------------------------------------------------------------------------
# Test: convert_audio skips gracefully when ffmpeg is absent
# ---------------------------------------------------------------------------


class TestConvertAudio:
    def test_returns_false_when_ffmpeg_missing(self, tmp_dir):
        src = tmp_dir / "test.amr"
        src.write_bytes(b"fake amr")
        dest = tmp_dir / "test.mp3"
        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                result = voicemail.convert_audio(src, dest, "mp3")
        assert result is False
