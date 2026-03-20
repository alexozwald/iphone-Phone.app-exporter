# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# phone-exporter

CLI tool to extract voicemails and call history from iPhone local backups (iTunes/Finder) and export them as labeled audio files with metadata CSVs.

## Architecture

`src/` package with domain-separated modules. `main.py` is the CLI entry point.

- **`src/backup.py`** — shared backup infrastructure (discovery, Info.plist, Manifest.db, file extraction, timestamp conversion)
- **`src/voicemail.py`** — voicemail extraction, matching, export, CSV
- **`src/call_hist.py`** — call history extraction and CSV
- **`main.py`** — CLI args, orchestration, stdout printing
- **Unencrypted backups**: stdlib only (`sqlite3`, `plistlib`, `shutil`)
- **Encrypted backups**: `iphone-backup-decrypt` + `pycryptodome` (optional, install via `uv sync --extra encrypt`)
- **Audio conversion**: shells out to `ffmpeg` via `subprocess` (optional, detected at runtime)

## Key Files

- `main.py` — CLI entry point and orchestration
- `src/backup.py` — shared backup infrastructure
- `src/voicemail.py` — voicemail domain logic
- `src/call_hist.py` — call history domain logic
- `pyproject.toml` — Project config; encrypted deps under `[project.optional-dependencies] encrypt`
- `tests/conftest.py` — shared pytest fixtures (`tmp_dir`, `mock_backup`)
- `tests/test_backup.py` — backup infrastructure tests
- `tests/test_voicemail.py` — voicemail tests
- `tests/test_call_hist.py` — call history tests

## Common Commands

```bash
# Run the tool (auto-detects backup, prompts for password if encrypted)
uv run export-phoneapp

# Export everything with MP3 conversion and raw archival
uv run export-phoneapp -p "MyBackupPassword" --data=all --save-raw -o "out/phone_app.$(date +%Y%m%d_%H%M)/" --audio-format=mp3

# Encrypted backup (password can also be entered interactively if omitted)
uv run export-phoneapp --password "MyBackupPassword"

# List available backups
uv run export-phoneapp --list-backups

# Run tests
uv run pytest -v

# Lint and format
uv run ruff check .
uv run ruff format .
```

## CLI Flags

- `--data {all,voicemail,call_hist}` — default: `all`
- `--output-dir / -o PATH` — default: `./phone_export`
- `--password / -p PASS` — omit to be prompted interactively on encrypted backups
- `--audio-format {amr,mp3,wav,m4a}` — default: `amr` (no conversion)
- `--backup-dir PATH` — auto-detected if omitted
- `--save-raw` — copies raw DB + blobs to `<output-dir>/raw/`
- `--list-backups` — list backups and exit

## Implementation Notes

- **Backup file layout**: `<backup_dir>/<first2_of_hash>/<full_hash>` (no extension)
- **Voicemail audio filenames**: named after their `voicemail.db` ROWID (e.g., `1.amr`, `2.amr`)
- **Timestamp detection**: values > `1_000_000_000` are Unix epoch; smaller values are Core Data epoch (add `978307200` offset)
- **Output filename format**: `001_2024-03-15_+15551234567.amr`
- **voicemails.csv columns**: index, output_file, sender, callback_num, date, duration, trashed_date, expiration, flags, receiver, uuid, remote_uid, label, rowid, file_id
- **calls.csv columns**: index, date, duration, call_type, direction, answered, address, name, location, service_provider, spam_score, was_emergency, read, rowid
- **Encrypted vs unencrypted**: unencrypted = voicemails only; encrypted = voicemails + call history

## Dependencies

- Python 3.10+
- `pytest` for tests (dev dep: `uv add --dev pytest`)
- `iphone-backup-decrypt>=0.9.0` and `pycryptodome>=3.9.0` for encrypted backups only (`uv sync --extra encrypt`)
- `ffmpeg` in PATH for audio conversion only
