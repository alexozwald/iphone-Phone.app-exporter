# iPhone Phone.app Exporter

Export voicemails and call history from iPhone local backups (iTunes/Finder) to labeled audio files and metadata CSVs.

Voicemails & call history (i.e. `Phone.app` data) is one of the last vestiges of carrier-managed data that's poorly managed & suffers from limited storage + disappearing history. Call history only goes back so far, there are no user-controls over how to save it or how long it's saved, and there's no simple way to archive it oneself. Voicemailboxes are still carrier server-side managed, limit recordings to an 8k sample rate, and still fill up quickly forcing users to delete valuable memories & the last recorded words of departed loved ones.

This project seeks to save + archive `Phone.app` data and break the last carrier-dominated penny-squeezed data black-box that users & data-hoarders have sparing control over saving.

> [!NOTE]
> There is presently a bug in iphone backups that they do not store all voicemails, even if they've been recently cached + backed up. As of 2026-03-19, this bug affects both iMazing & this codebase--the data is inaccessible. At time of writing, my phone has 193 voicemails (137 + 56 deleted), yet only 52 can be backed up or appear in the backup database.
>
> Until Apple fixes this, some voicemails will be totally inaccessible via any backup solution (unless airdropped—which strips metadata).

## Features

- **Unencrypted backups**: voicemail export (audio + CSV)
- **Encrypted backups**: voicemail export + call history CSV
- Exports `.amr` audio with human-readable names: `001_2024-03-15_+15551234567.amr`
- Converts to **MP3, WAV, or M4A** via ffmpeg (optional)
- Auto-detects backup location on macOS, Windows, and Linux
- Interactive backup selection when multiple devices are found

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- [ffmpeg](https://ffmpeg.org/) (optional) — for audio conversion; ffmpeg needs to be your PATH for this to work

## Installation

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and set up
git clone <repo-url>
cd iphone-Phone.app-exporter
uv sync

# Get started!
uv run export-phoneapp
```

## Usage

```bash
# RECOMMENDED USE: Exports all voicemails + call hist (if possible); requests password if needed.
uv run export-phoneapp

# DEV PREFERRED: detect backup, save all data types including raw data
uv run export-phoneapp -p PASSWORD --data=all --save-raw -o "out/phone_app.$(date +%Y%m%d_%H%M)/" --audio-format=mp3

# Voicemail only, convert to MP3
uv run export-phoneapp --data voicemail --audio-format mp3 --output-dir ./my_export

# Encrypted backup (enables call history export too)
uv run export-phoneapp --password "MyBackupPassword"

# Specify a backup directory manually
uv run export-phoneapp --backup-dir /path/to/backup/AABBCCDD1122

# List available backups
uv run export-phoneapp --list-backups

# Archive raw backup blobs alongside export
uv run export-phoneapp --save-raw
```

## Options

```
usage: export-phoneapp [-h] [--data {all,voicemail,call_hist}] [--output-dir PATH]
                       [--password PASS] [--save-raw] [--backup-dir PATH]
                       [--audio-format {amr,mp3,wav,m4a}] [--list-backups]

Export voicemails and call history from an iPhone backup.

  --data {all,voicemail,call_hist}  What to export: all (default), voicemail only, or call_hist only
  --output-dir, -o PATH             Output directory (default: ./phone_export)
  --password, -p PASS               Password for encrypted backups
  --save-raw                        Copy raw voicemail.db and all backup blobs to <output-dir>/raw/ for archival
  --backup-dir PATH                 Path to iTunes/Finder backup directory (auto-detected if omitted)
  --audio-format {amr,mp3,wav,m4a}  Convert audio to this format (default: amr [non-converted]). Conversion requires ffmpeg.
  --list-backups                    List available backups and exit
```

## Output

```
phone_export/
├── 001_2024-03-15_+15551234567.amr
├── 002_2024-03-16_+15559876543.amr
├── voicemails.csv
└── calls.csv                        ← encrypted backups only
```

### voicemails.csv columns

| Column       | Description                                   |
|--------------|-----------------------------------------------|
| index        | Export order (1-based)                        |
| output_file  | Exported filename                             |
| sender       | Caller phone number                           |
| callback_num | Callback number                               |
| date         | Voicemail date/time (UTC)                     |
| duration     | Duration in seconds                           |
| trashed_date | When deleted (UTC), if ever                   |
| expiration   | Carrier expiry date/time (UTC)                |
| flags        | Bitmask – *Unclear definitions*               |
| receiver     | Number that received the voicemail            |
| uuid         | Apple UUID for the voicemail                  |
| remote_uid   | Carrier's voicemail ID                        |
| label        | User label (if set)                           |
| rowid        | Internal voicemail.db row ID                  |
| file_id      | Backup file hash                              |

### calls.csv columns

| Column           | Description                                |
|------------------|--------------------------------------------|
| index            | Export order (1-based)                     |
| date             | Call date/time (UTC)                       |
| duration         | Duration in seconds                        |
| call_type        | Call type (cellular, FaceTime, etc.)       |
| direction        | `inbound` or `outbound`                    |
| answered         | Whether the call was answered              |
| address          | Remote phone number or address             |
| name             | Contact name (if available)                |
| location         | City/region associated with the number     |
| service_provider | Carrier or service used                    |
| spam_score       | Spam likelihood score                      |
| was_emergency    | Whether it was an emergency call           |
| read             | Whether the missed call was marked read    |
| rowid            | Internal CallHistory.storedata row ID      |

## Creating an iPhone Backup

> [!NOTE]
> Visual Voicemail downloads lazily — voicemails you haven't played yet are stored on your carrier's server, not on your phone. Before backing up: open **Phone** → **Voicemail**, scroll to the bottom, and tap each voicemail to trigger the download. Then back up immediately.

1. Connect your iPhone to your Mac or PC
2. **macOS (Catalina+)**: Finder → select your iPhone → "Back Up Now"
3. **macOS (Mojave and earlier) / Windows**: iTunes → select your iPhone → "Back Up Now"
4. For encrypted backups, set a password in the backup settings panel
5. Wait for the backup to complete before running this tool

## Contributing

```bash
# Run tests
uv run pytest -v

# Lint and format
uv run ruff check .
uv run ruff format .
```

## To-Do

- [ ] Add support for merging data from regular backups / exports

## Out of Scope

- iCloud backup support
- Direct USB device access (no [libimobiledevice](https://github.com/libimobiledevice/libimobiledevice))
- Voicemail transcription (possible future feature via whisperX)

## Credits

Encrypted backup support powered by [iphone-backup-decrypt](https://github.com/jsharkey13/iphone_backup_decrypt).

Based on [iphone-voicemail-exporter](https://github.com/sawwavecircuits/iphone-voicemail-exporter) by sawwavecircuits.
