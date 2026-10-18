"""
services/twitter_db.py — SQLite storage for the Twitter/X image monitor.

Reuses the schema/contract from the old ``onlinefabster/bot`` twitter monitor so
the database is a drop-in migration.

Tables:
  twitter_watches    — list of Twitter usernames to monitor
  twitter_seen       — image URLs already handled (dedupe)
  twitter_signatures — content hashes (sha256) of images already uploaded (dedupe)
  twitter_uploads    — archive/dashboard record of every uploaded image
  twitter_runs       — monitor run history (status panel / dashboard)
"""

import sqlite3
import os
import logging
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "/app/data/twitter-monitor.db"))
logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS twitter_watches (
                username    TEXT PRIMARY KEY,
                added_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS twitter_seen (
                image_url   TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                seen_at     TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS twitter_signatures (
                sha256       TEXT PRIMARY KEY,
                username     TEXT NOT NULL,
                source_url   TEXT,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS twitter_uploads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256        TEXT NOT NULL,
                username      TEXT NOT NULL,
                image_url     TEXT,
                local_filename TEXT,
                immich_asset_id TEXT,
                uploaded_at   TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(sha256)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS twitter_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                status      TEXT,
                summary     TEXT
            )
        """)


# ── Watch list helpers ──────────────────────────────────────────────────────

def add_watch(username: str) -> bool:
    """Add a username to the watch list. Returns True if newly added."""
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO twitter_watches (username) VALUES (?)",
                (username.lower().strip(),),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_watch(username: str) -> bool:
    """Remove a username from the watch list. Returns True if it existed."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM twitter_watches WHERE username = ?",
            (username.lower().strip(),),
        )
        return cur.rowcount > 0


def list_watches() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT username FROM twitter_watches ORDER BY added_at"
        ).fetchall()
        return [r["username"] for r in rows]


# ── Seen-image (URL) helpers ────────────────────────────────────────────────

def is_seen(image_url: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM twitter_seen WHERE image_url = ?", (image_url,)
        ).fetchone()
        return row is not None


def mark_seen(image_url: str, username: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO twitter_seen (image_url, username) VALUES (?, ?)",
            (image_url, username),
        )


# ── Signature (content hash) helpers ───────────────────────────────────────

def is_signature_seen(sha256: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM twitter_signatures WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
        return row is not None


def mark_signature_seen(sha256: str, username: str, source_url: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO twitter_signatures (sha256, username, source_url) VALUES (?, ?, ?)",
            (sha256, username, source_url),
        )


# ── Upload record helpers ───────────────────────────────────────────────────

def record_upload(
    sha256: str,
    username: str,
    image_url: str | None,
    local_filename: str | None,
    immich_asset_id: str | None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO twitter_uploads
                (sha256, username, image_url, local_filename, immich_asset_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sha256, username, image_url, local_filename, immich_asset_id),
        )


def list_uploads(username: str | None = None, limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM twitter_uploads"
    args: list = []
    if username:
        sql += " WHERE username = ?"
        args.append(username.lower().strip())
    sql += " ORDER BY uploaded_at DESC LIMIT ?"
    args.append(int(limit))
    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]


def upload_count(username: str | None = None) -> int:
    sql = "SELECT COUNT(*) AS c FROM twitter_uploads"
    args: list = []
    if username:
        sql += " WHERE username = ?"
        args.append(username)
    with get_connection() as conn:
        row = conn.execute(sql, args).fetchone()
        return row["c"] if row else 0


# ── Run history helpers ────────────────────────────────────────────────────

def record_run_start() -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO twitter_runs (started_at, status) VALUES (datetime('now'), 'running')"
        )
        return cur.lastrowid


def record_run_finish(run_id: int, status: str, summary: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE twitter_runs
            SET finished_at = datetime('now'), status = ?, summary = ?
            WHERE id = ?
            """,
            (status, summary, run_id),
        )


def last_run(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM twitter_runs ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]