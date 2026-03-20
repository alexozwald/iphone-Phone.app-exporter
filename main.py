#!/usr/bin/env python3
"""
iPhone Phone Data Export Tool

Extracts voicemails and call history from iPhone local backups
(iTunes/Finder) and exports them as labeled audio files and CSV manifests.
"""

import argparse
import getpass
import shutil
import tempfile
from pathlib import Path

from src.backup import (
    extract_file,
    find_backups,
    get_backup_info,
    is_encrypted,
    open_manifest_db,
    select_backup,
)
from src.call_hist import find_call_history_db, parse_call_history, write_calls_csv
from src.voicemail import (
    dump_raw_files,
    export_voicemails,
    find_voicemail_db,
    find_voicemail_files,
    match_voicemails,
    parse_voicemail_metadata,
    write_csv,
)


def main():
    parser = argparse.ArgumentParser(
        description="Export voicemails and call history from an iPhone backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        color=True,
        epilog="""
Examples:
  # Auto-detect backup, export to ./phone_export
  uv run export-phoneapp
  uv run main.py

  # Specify backup directory and output path
  python main.py --backup-dir /path/to/backup --output ./my_export

  # Convert voicemails to MP3 (requires ffmpeg)
  python main.py --audio-format mp3

  # Encrypted backup
  python main.py --password "MyBackupPassword"
        """,
    )
    parser.add_argument(
        "--data",
        choices=["all", "voicemail", "call_hist"],
        default="all",
        type=str.lower,
        help="What to export: all (default), voicemail only, or call_hist only",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        metavar="PATH",
        default="./phone_export",
        help="Output directory (default: ./phone_export)",
    )
    parser.add_argument(
        "--password",
        "-p",
        metavar="PASS",
        help="Password for encrypted backups",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="Copy raw voicemail.db and all backup blobs to <output-dir>/raw/ for archival",
    )
    parser.add_argument(
        "--backup-dir",
        metavar="PATH",
        help="Path to iTunes/Finder backup directory (auto-detected if omitted)",
    )
    parser.add_argument(
        "--audio-format",
        choices=["amr", "mp3", "wav", "m4a"],
        type=str.lower,
        help="Convert audio to this format (default: amr [non-converted]). Conversion requires ffmpeg.",
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List available backups and exit",
    )

    args = parser.parse_args()

    # Discover backups
    backups = find_backups(args.backup_dir)

    if args.list_backups:
        print(f"Found {len(backups)} backup(s):")
        for bp in backups:
            info = get_backup_info(bp)
            print(
                f"  {info['device_name']} ({info['product_type']})  —  {info['last_backup']}"
            )
            print(f"    {bp}")
        return

    backup_path = select_backup(backups)
    info = get_backup_info(backup_path)
    print(f"\nUsing backup: {info['device_name']} ({info['product_type']})")
    print(f"  Last backup: {info['last_backup']}")
    print(f"  Path: {backup_path}")

    encrypted = is_encrypted(backup_path)
    if encrypted:
        print("  Backup is ENCRYPTED")
        if not args.password:
            args.password = getpass.getpass("  Enter backup password: ")

    export_voicemail = args.data in ("all", "voicemail")
    export_calls = args.data in ("all", "call_hist")

    # Open Manifest.db
    manifest_conn, tmp_dir, enc_backup = open_manifest_db(backup_path, args.password)

    output_dir = Path(args.output_dir)

    try:
        if export_voicemail:
            # Find voicemail files and DB
            audio_files = find_voicemail_files(manifest_conn)
            vm_db_file_id, vm_db_rel_path = find_voicemail_db(manifest_conn)

            print(f"\nFound {len(audio_files)} voicemail audio file(s)")

            if not audio_files and not vm_db_file_id:
                print("No voicemails found in this backup.")
            else:
                # Extract voicemail.db to temp for parsing
                metadata = []
                if vm_db_file_id:
                    with tempfile.NamedTemporaryFile(
                        suffix=".db", delete=False
                    ) as tmp_db:
                        tmp_db_path = Path(tmp_db.name)
                    success = extract_file(
                        backup_path,
                        vm_db_file_id,
                        tmp_db_path,
                        enc_backup,
                        relative_path=vm_db_rel_path,
                    )
                    if success:
                        metadata = parse_voicemail_metadata(tmp_db_path)
                        print(f"Found {len(metadata)} voicemail metadata record(s)")
                    tmp_db_path.unlink(missing_ok=True)
                else:
                    print(
                        "Warning: voicemail.db not found — exporting audio files without metadata."
                    )

                # Match audio with metadata
                matched = match_voicemails(audio_files, metadata)

                # Determine conversion format
                convert_format = args.audio_format

                print(f"\nExporting voicemails to: {output_dir.resolve()}")
                exported = export_voicemails(
                    matched,
                    output_dir,
                    backup_path,
                    convert_format=convert_format,
                    encrypted_backup=enc_backup,
                )

                csv_path = write_csv(exported, output_dir)

                if args.save_raw:
                    print("\nSaving raw files...")
                    dump_raw_files(manifest_conn, backup_path, output_dir, enc_backup)

                success_count = sum(1 for e in exported if e.get("output_file"))
                print("\nVoicemail export complete:")
                print(f"  Audio files: {success_count}/{len(exported)}")
                print(f"  CSV manifest: {csv_path}")

        if export_calls:
            ch_file_id, ch_rel_path = find_call_history_db(manifest_conn)
            if not ch_file_id:
                print("\nCall history not found in this backup (skipping).")
            else:
                with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
                    tmp_ch = Path(f.name)
                if extract_file(
                    backup_path,
                    ch_file_id,
                    tmp_ch,
                    enc_backup,
                    relative_path=ch_rel_path,
                ):
                    calls = parse_call_history(tmp_ch)
                    tmp_ch.unlink(missing_ok=True)
                    if calls:
                        output_dir.mkdir(parents=True, exist_ok=True)
                        calls_csv = write_calls_csv(calls, output_dir)
                        print(f"\nCall history: {len(calls)} records → {calls_csv}")
                    else:
                        print("\nCall history DB found but contains no records.")
                else:
                    tmp_ch.unlink(missing_ok=True)
                    print("\nWarning: could not extract CallHistory.storedata.")

    finally:
        manifest_conn.close()
        if tmp_dir and Path(tmp_dir).exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
