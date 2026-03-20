"""
Shared backup infrastructure for iPhone backup tools.

Handles backup discovery, Info.plist parsing, Manifest.db access,
file extraction, and timestamp conversion.
"""

import os
import platform
import plistlib
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Core Data epoch: Jan 1, 2001 UTC (seconds since Unix epoch 1970)
CORE_DATA_EPOCH_OFFSET = 978307200

# Threshold: timestamps > this are Unix epoch, <= are Core Data epoch offsets
# (Apple timestamps pre-2001 are implausible for voicemails)
UNIX_THRESHOLD = 1_000_000_000


def find_backups(custom_path=None):
    """Auto-detect OS backup directory or use custom path.

    Returns a list of backup directory Paths.
    """
    if custom_path:
        p = Path(custom_path)
        if not p.exists():
            print(f"Error: Backup path does not exist: {p}", file=sys.stderr)
            sys.exit(1)
        # If the user pointed directly at a single backup dir (has Manifest.plist)
        if (p / "Manifest.plist").exists():
            return [p]
        # Otherwise treat it as the parent containing multiple backups
        candidates = [
            d for d in p.iterdir() if d.is_dir() and (d / "Manifest.plist").exists()
        ]
        if not candidates:
            print(f"Error: No valid iPhone backups found in: {p}", file=sys.stderr)
            sys.exit(1)
        return candidates

    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "MobileSync" / "Backup"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        base = Path(appdata) / "Apple Computer" / "MobileSync" / "Backup"
    else:
        # Linux — iTunes via Wine or user-specified
        base = (
            Path.home()
            / ".wine"
            / "drive_c"
            / "Users"
            / os.environ.get("USER", "user")
            / "AppData"
            / "Roaming"
            / "Apple Computer"
            / "MobileSync"
            / "Backup"
        )

    if not base.exists():
        print(f"Error: Default backup directory not found: {base}", file=sys.stderr)
        print("Use --backup-dir to specify a custom path.", file=sys.stderr)
        sys.exit(1)

    try:
        candidates = [
            d for d in base.iterdir() if d.is_dir() and (d / "Manifest.plist").exists()
        ]
    except PermissionError:
        print(f"Error: Permission denied accessing: {base}", file=sys.stderr)
        print("macOS is blocking access to the iPhone backup folder.", file=sys.stderr)
        print(
            "To fix this, grant Full Disk Access to your terminal app:", file=sys.stderr
        )
        print(
            "  macOS 13+: System Settings → Privacy & Security → Full Disk Access",
            file=sys.stderr,
        )
        print(
            "  macOS 12-: System Preferences → Security & Privacy → Full Disk Access",
            file=sys.stderr,
        )
        print(
            "Add your terminal app (Terminal, iTerm2, VS Code, etc.), then quit",
            file=sys.stderr,
        )
        print(
            "and relaunch the terminal app before running this script again.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not candidates:
        print(f"Error: No iPhone backups found in: {base}", file=sys.stderr)
        sys.exit(1)

    return candidates


def get_backup_info(backup_path):
    """Parse Info.plist for device name, last backup date, product type.

    Returns a dict with keys: device_name, last_backup, product_type, udid.
    """
    info_plist = backup_path / "Info.plist"
    result = {
        "device_name": "Unknown Device",
        "last_backup": "Unknown",
        "product_type": "Unknown",
        "udid": backup_path.name,
    }
    if not info_plist.exists():
        return result

    with open(info_plist, "rb") as f:
        data = plistlib.load(f)

    result["device_name"] = data.get("Device Name", result["device_name"])
    result["product_type"] = data.get("Product Type", result["product_type"])
    result["udid"] = data.get("Unique Identifier", result["udid"])

    last_backup = data.get("Last Backup Date")
    if isinstance(last_backup, datetime):
        result["last_backup"] = last_backup.strftime("%Y-%m-%d %H:%M:%S UTC")
    elif last_backup:
        result["last_backup"] = str(last_backup)

    return result


def select_backup(backups):
    """Interactively prompt user to select from multiple backups.

    Returns the chosen backup Path.
    """
    if len(backups) == 1:
        return backups[0]

    print("\nMultiple backups found:")
    for i, bp in enumerate(backups, 1):
        info = get_backup_info(bp)
        print(
            f"  [{i}] {info['device_name']}  |  {info['product_type']}  |  {info['last_backup']}"
        )
        print(f"      Path: {bp}")

    while True:
        try:
            choice = input(f"\nSelect backup [1-{len(backups)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(backups):
                return backups[idx]
        except (ValueError, KeyboardInterrupt):
            pass
        print(f"Please enter a number between 1 and {len(backups)}.")


def is_encrypted(backup_path):
    """Return True if Manifest.plist indicates the backup is encrypted."""
    manifest_plist = backup_path / "Manifest.plist"
    if not manifest_plist.exists():
        return False
    with open(manifest_plist, "rb") as f:
        data = plistlib.load(f)
    return bool(data.get("IsEncrypted", False))


def open_manifest_db(backup_path, password=None):
    """Open Manifest.db and return a sqlite3 connection.

    For encrypted backups, decrypts to a temp file first using
    iphone-backup-decrypt. Returns (connection, temp_dir_or_None, enc_backup_or_None).
    """
    if is_encrypted(backup_path):
        if password is None:
            password = input("Backup is encrypted. Enter password: ")
        try:
            from iphone_backup_decrypt import EncryptedBackup
        except ImportError:
            print(
                "Error: Encrypted backup requires 'iphone-backup-decrypt'.\n"
                "Install it with: pip install iphone-backup-decrypt",
                file=sys.stderr,
            )
            sys.exit(1)

        tmp_dir = tempfile.mkdtemp(prefix="voicemail_export_")
        backup = EncryptedBackup(backup_directory=str(backup_path), passphrase=password)
        manifest_db_path = Path(tmp_dir) / "Manifest.db"
        backup.save_manifest_file(str(manifest_db_path))
        conn = sqlite3.connect(str(manifest_db_path))
        return conn, tmp_dir, backup

    manifest_db = backup_path / "Manifest.db"
    if not manifest_db.exists():
        print(f"Error: Manifest.db not found in {backup_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(manifest_db))
    return conn, None, None


def extract_file(
    backup_path, file_id, dest_path, encrypted_backup=None, relative_path=None
):
    """Copy a backup file to dest_path.

    For unencrypted: reads from <backup>/<first2>/<fileID>.
    For encrypted: uses the EncryptedBackup object.
    """
    if encrypted_backup is not None:
        try:
            encrypted_backup.extract_file(
                relative_path=relative_path,
                output_filename=str(dest_path),
            )
            return True
        except Exception:
            return False

    src = backup_path / file_id[:2] / file_id
    try:
        shutil.copy2(str(src), str(dest_path))
        return True
    except FileNotFoundError:
        return False


def convert_timestamp(ts):
    """Convert a numeric timestamp to a UTC datetime string.

    Detects Unix epoch vs Core Data epoch automatically.
    Returns ISO-format string or empty string on failure.
    """
    if ts is None:
        return ""
    try:
        ts = float(ts)
        if ts <= 0:
            return ""
        if ts < UNIX_THRESHOLD:
            # Core Data epoch (seconds since 2001-01-01)
            ts += CORE_DATA_EPOCH_OFFSET
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, OSError, OverflowError):
        return ""
