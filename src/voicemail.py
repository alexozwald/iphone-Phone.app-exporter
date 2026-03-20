"""
Voicemail extraction and export for iPhone backup tools.

Handles finding voicemail files in Manifest.db, parsing voicemail.db
metadata, matching audio to metadata, exporting audio files, and
writing the CSV manifest.
"""

import csv
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from src.backup import convert_timestamp, extract_file


def find_voicemail_files(manifest_conn):
    """Query Manifest.db for voicemail audio files.

    Returns list of dicts: {file_id, relative_path, filename}.
    """
    cursor = manifest_conn.cursor()
    cursor.execute(
        """
        SELECT fileID, relativePath
        FROM Files
        WHERE domain = 'HomeDomain'
          AND relativePath LIKE 'Library/Voicemail/%.amr'
        ORDER BY relativePath
        """
    )
    results = []
    for file_id, rel_path in cursor.fetchall():
        results.append(
            {
                "file_id": file_id,
                "relative_path": rel_path,
                "filename": Path(rel_path).stem,  # e.g. "1" from "1.amr"
            }
        )
    return results


def find_voicemail_db(manifest_conn):
    """Query Manifest.db for the voicemail.db file entry.

    Returns (file_id, relative_path) or (None, None).
    """
    cursor = manifest_conn.cursor()
    cursor.execute(
        """
        SELECT fileID, relativePath
        FROM Files
        WHERE domain = 'HomeDomain'
          AND relativePath = 'Library/Voicemail/voicemail.db'
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row:
        return row[0], row[1]
    return None, None


def parse_voicemail_metadata(voicemail_db_path):
    """Read voicemail table from voicemail.db.

    Returns list of dicts with keys: rowid, sender, date_str, duration,
    callback_num, label.
    """
    conn = sqlite3.connect(str(voicemail_db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Discover columns (schema varies across iOS versions)
    cursor.execute("PRAGMA table_info(voicemail)")
    columns = {row["name"] for row in cursor.fetchall()}

    # Build a safe SELECT based on available columns
    select_cols = ["ROWID"]
    for col in (
        "sender",
        "callback_num",
        "date",
        "duration",
        "flags",
        "expiration",
        "expiration_date",
        "trashed_date",
        "label",
        "receiver",
        "uuid",
        "remote_uid",
    ):
        if col in columns:
            select_cols.append(col)

    cursor.execute(f"SELECT {', '.join(select_cols)} FROM voicemail ORDER BY ROWID")

    results = []
    for row in cursor.fetchall():
        entry = dict(row)
        entry["rowid"] = entry.pop("ROWID")
        entry["date_str"] = convert_timestamp(entry.get("date"))
        entry["trashed_date_str"] = convert_timestamp(entry.get("trashed_date"))
        exp_ts = entry.get("expiration") or entry.get("expiration_date")
        entry["expiration_str"] = convert_timestamp(exp_ts)
        results.append(entry)

    conn.close()
    return results


def match_voicemails(audio_files, metadata):
    """Join audio files with metadata by ROWID / filename.

    iPhone voicemail audio files are named after their ROWID (e.g., "1.amr").
    Returns list of dicts combining both sources.
    """
    meta_by_rowid = {str(m["rowid"]): m for m in metadata}

    matched = []
    for af in audio_files:
        entry = dict(af)
        meta = meta_by_rowid.get(af["filename"], {})
        entry.update(meta)
        matched.append(entry)

    # Also include metadata entries with no audio file (edge case)
    audio_filenames = {af["filename"] for af in audio_files}
    for m in metadata:
        if str(m["rowid"]) not in audio_filenames:
            entry = dict(m)
            entry["file_id"] = None
            entry["relative_path"] = None
            entry["filename"] = str(m["rowid"])
            matched.append(entry)

    return matched


def make_output_filename(entry, index, fmt="amr"):
    """Generate a human-readable output filename for a voicemail."""
    date_part = ""
    date_str = entry.get("date_str", "")
    if date_str:
        # e.g. "2024-03-15 10:22:00 UTC" -> "2024-03-15"
        date_part = date_str.split(" ")[0]

    sender = entry.get("sender") or entry.get("callback_num") or "unknown"
    # Sanitize: keep only alphanumerics, dashes, underscores, plus
    safe_sender = "".join(c if c.isalnum() or c in "-_+" else "_" for c in sender)
    safe_sender = safe_sender.strip("_")[:40] or "unknown"

    parts = [f"{index:03d}"]
    if date_part:
        parts.append(date_part)
    parts.append(safe_sender)
    return "_".join(parts) + f".{fmt}"


def convert_audio(src_path, dest_path, fmt):
    """Shell out to ffmpeg to convert audio file.

    Returns True on success, False on failure.
    """
    cmd = ["ffmpeg", "-y", "-i", str(src_path), str(dest_path)]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        return result.returncode == 0
    except FileNotFoundError:
        print(
            "Error: ffmpeg not found. Install ffmpeg or use --no-convert.",
            file=sys.stderr,
        )
        return False
    except subprocess.TimeoutExpired:
        print(f"Warning: ffmpeg timed out converting {src_path}", file=sys.stderr)
        return False


def export_voicemails(
    matched, output_dir, backup_path, convert_format=None, encrypted_backup=None
):
    """Copy/rename voicemail audio files to output_dir, with optional conversion.

    Returns list of matched entries updated with 'output_file' key.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_available = shutil.which("ffmpeg") is not None
    if convert_format and not ffmpeg_available:
        print(
            f"Warning: ffmpeg not found — skipping conversion to {convert_format}. "
            "Files will be exported as .amr.",
            file=sys.stderr,
        )
        convert_format = None

    exported = []
    for i, entry in enumerate(matched, 1):
        file_id = entry.get("file_id")
        if not file_id:
            entry["output_file"] = ""
            exported.append(entry)
            continue

        out_fmt = convert_format or "amr"
        out_name = make_output_filename(entry, i, fmt=out_fmt)
        out_path = output_dir / out_name

        if convert_format:
            # Extract to temp first, then convert
            with tempfile.NamedTemporaryFile(suffix=".amr", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            success = extract_file(
                backup_path,
                file_id,
                tmp_path,
                encrypted_backup,
                relative_path=entry.get("relative_path"),
            )
            if success:
                ok = convert_audio(tmp_path, out_path, convert_format)
                if not ok:
                    # Fall back to copying .amr
                    fallback = out_path.with_suffix(".amr")
                    shutil.copy2(str(tmp_path), str(fallback))
                    entry["output_file"] = fallback.name
                else:
                    entry["output_file"] = out_name
            else:
                entry["output_file"] = ""
            tmp_path.unlink(missing_ok=True)
        else:
            out_name = make_output_filename(entry, i, fmt="amr")
            out_path = output_dir / out_name
            success = extract_file(
                backup_path,
                file_id,
                out_path,
                encrypted_backup,
                relative_path=entry.get("relative_path"),
            )
            entry["output_file"] = out_name if success else ""

        exported.append(entry)

    return exported


def write_csv(matched, output_dir):
    """Write voicemails.csv manifest to output_dir."""
    output_dir = Path(output_dir)
    csv_path = output_dir / "voicemails.csv"

    fieldnames = [
        "index",
        "output_file",
        "sender",
        "callback_num",
        "date",
        "duration",
        "trashed_date",
        "expiration",
        "flags",
        "receiver",
        "uuid",
        "remote_uid",
        "label",
        "rowid",
        "file_id",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for i, entry in enumerate(matched, 1):
            row = {
                "index": i,
                "output_file": entry.get("output_file", ""),
                "sender": entry.get("sender", ""),
                "callback_num": entry.get("callback_num", ""),
                "date": entry.get("date_str", ""),
                "duration": entry.get("duration", ""),
                "trashed_date": entry.get("trashed_date_str", ""),
                "expiration": entry.get("expiration_str", ""),
                "flags": entry.get("flags", ""),
                "receiver": entry.get("receiver", ""),
                "uuid": entry.get("uuid", ""),
                "remote_uid": entry.get("remote_uid", ""),
                "label": entry.get("label", ""),
                "rowid": entry.get("rowid", ""),
                "file_id": entry.get("file_id", ""),
            }
            writer.writerow(row)

    return csv_path


def dump_raw_files(manifest_conn, backup_path, output_dir, encrypted_backup=None):
    """Copy all HomeDomain Library/Voicemail/* backup blobs to <output_dir>/raw/.

    Preserves the original relative path structure so future analysis can map
    files back to their iOS paths.
    """
    raw_dir = Path(output_dir) / "raw"
    cursor = manifest_conn.cursor()
    cursor.execute(
        """
        SELECT fileID, relativePath
        FROM Files
        WHERE domain = 'HomeDomain'
          AND relativePath LIKE 'Library/Voicemail/%'
        ORDER BY relativePath
        """
    )
    rows = cursor.fetchall()

    copied = 0
    for file_id, rel_path in rows:
        dest = raw_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if extract_file(
            backup_path, file_id, dest, encrypted_backup, relative_path=rel_path
        ):
            copied += 1

    print(f"  Saved {copied} raw file(s) to {raw_dir}")
