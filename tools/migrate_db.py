#!/usr/bin/env python3
"""tools/migrate_db.py — migrate the Twitter monitor database into the fresh
standalone ``twitter-monitor.db``.

By default only ``twitter_watches`` (the account list) is copied. The ``seen``
URL table and ``twitter_signatures`` dedup table are NOT migrated by default
(plan Q1: backfill Immich with current media on first run). Pass
``--copy-seen`` / ``--copy-signatures`` to override.

Usage:
    python tools/migrate_db.py --src <schedules.db> --dst <twitter-monitor.db>
        [--copy-seen] [--copy-signatures]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import twitter_db  # noqa: E402


def copy_table(src_conn, dst_conn, name):
    rows = src_conn.execute(f"SELECT * FROM {name}").fetchall()
    if not rows:
        return 0
    cols = [d[0] for d in src_conn.execute(f"SELECT * FROM {name} LIMIT 0").description]
    placeholders = ",".join("?" * len(cols))
    col_names = ",".join(cols)
    dst_conn.executemany(
        f"INSERT OR IGNORE INTO {name} ({col_names}) VALUES ({placeholders})",
        [tuple(r) for r in rows],
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description="Migrate twitter DB tables into a fresh DB.")
    ap.add_argument("--src", required=True, help="Path to the old schedules.db")
    ap.add_argument("--dst", default=None, help="dst DB path (default: DB_PATH env)")
    ap.add_argument("--copy-seen", action="store_true", help="Also copy twitter_seen")
    ap.add_argument("--copy-signatures", action="store_true", help="Also copy twitter_signatures")
    args = ap.parse_args()

    src_path = Path(args.src)
    if not src_path.exists():
        print(f"ERROR: source DB not found: {src_path}", file=sys.stderr)
        return 1

    dst_path = Path(args.dst) if args.dst else twitter_db.DB_PATH
    twitter_db.init_db()

    src = sqlite3.connect(str(src_path))
    dst = twitter_db.get_connection()
    try:
        n = copy_table(src, dst, "twitter_watches")
        print(f"twitter_watches: copied {n} row(s)")

        if args.copy_seen:
            n = copy_table(src, dst, "twitter_seen")
            print(f"twitter_seen: copied {n} row(s)")
        else:
            print("twitter_seen: SKIPPED (re-scrape/upload on first run)")

        if args.copy_signatures:
            n = copy_table(src, dst, "twitter_signatures")
            print(f"twitter_signatures: copied {n} row(s)")
        else:
            print("twitter_signatures: SKIPPED (re-upload on first run)")

        dst.commit()
        print("\nMigration complete. New DB:", dst_path)
        print("Watched accounts:")
        for w in twitter_db.list_watches():
            print(f"  - {w}")
        return 0
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    raise SystemExit(main())