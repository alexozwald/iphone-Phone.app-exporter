"""
Call history extraction and export for iPhone backup tools.

Handles finding CallHistory.storedata in Manifest.db, parsing call
records, and writing the calls CSV.
"""

import csv
import sqlite3
from pathlib import Path

from src.backup import convert_timestamp

CALL_TYPE_MAP = {1: "phone", 8: "facetime_audio", 16: "facetime_video"}
DIRECTION_MAP = {0: "incoming", 1: "outgoing"}


def find_call_history_db(manifest_conn):
    """Returns (file_id, relative_path) or (None, None)."""
    cursor = manifest_conn.cursor()
    cursor.execute(
        """SELECT fileID, relativePath FROM Files
           WHERE domain = 'HomeDomain'
             AND relativePath = 'Library/CallHistoryDB/CallHistory.storedata'
           LIMIT 1"""
    )
    row = cursor.fetchone()
    return (row[0], row[1]) if row else (None, None)


def parse_call_history(db_path):
    """Read ZCALLRECORD table from CallHistory.storedata.

    Returns list of dicts with call record fields.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(ZCALLRECORD)")
    columns = {row["name"] for row in cursor.fetchall()}

    if not columns:
        conn.close()
        return []

    candidate_cols = [
        "Z_PK",
        "ZDATE",
        "ZDURATION",
        "ZADDRESS",
        "ZNAME",
        "ZLOCATION",
        "ZORIGINATED",
        "ZCALLTYPE",
        "ZANSWERED",
        "ZREAD",
        "ZJUNKCONFIDENCE",
        "ZWASEMERGENCYCALL",
        "ZSERVICE_PROVIDER",
        "ZUNIQUE_ID",
    ]
    select_cols = [c for c in candidate_cols if c in columns]
    if not select_cols:
        conn.close()
        return []

    cursor.execute(f"SELECT {', '.join(select_cols)} FROM ZCALLRECORD ORDER BY Z_PK")

    results = []
    for row in cursor.fetchall():
        r = dict(row)
        v_type = r.get("ZCALLTYPE")
        v_dir = r.get("ZORIGINATED")
        v_ans = r.get("ZANSWERED")
        entry = {
            "rowid": r.get("Z_PK", ""),
            "date_str": convert_timestamp(r.get("ZDATE")),
            "duration": r.get("ZDURATION", ""),
            "call_type": CALL_TYPE_MAP.get(
                v_type, str(v_type) if v_type is not None else ""
            ),
            "direction": DIRECTION_MAP.get(
                v_dir, str(v_dir) if v_dir is not None else ""
            ),
            "answered": ("yes" if v_ans == 1 else "no") if v_ans is not None else "",
            "address": r.get("ZADDRESS") or "",
            "name": r.get("ZNAME") or "",
            "location": r.get("ZLOCATION") or "",
            "service_provider": r.get("ZSERVICE_PROVIDER") or "",
            "spam_score": r.get("ZJUNKCONFIDENCE", ""),
            "was_emergency": r.get("ZWASEMERGENCYCALL", ""),
            "read": r.get("ZREAD", ""),
        }
        results.append(entry)

    conn.close()
    return results


def write_calls_csv(calls, output_dir):
    """Write calls.csv to output_dir."""
    output_dir = Path(output_dir)
    csv_path = output_dir / "calls.csv"

    fieldnames = [
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
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for i, entry in enumerate(calls, 1):
            row = {
                "index": i,
                "date": entry.get("date_str", ""),
                "duration": entry.get("duration", ""),
                "call_type": entry.get("call_type", ""),
                "direction": entry.get("direction", ""),
                "answered": entry.get("answered", ""),
                "address": entry.get("address", ""),
                "name": entry.get("name", ""),
                "location": entry.get("location", ""),
                "service_provider": entry.get("service_provider", ""),
                "spam_score": entry.get("spam_score", ""),
                "was_emergency": entry.get("was_emergency", ""),
                "read": entry.get("read", ""),
                "rowid": entry.get("rowid", ""),
            }
            writer.writerow(row)

    return csv_path
