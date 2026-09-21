"""SQLite-backed storage for collected VLESS links.

Deduplication is enforced at the DB level via a UNIQUE constraint on
the link text, so callers don't need to check for existence first.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "vless_links.db"


def init_db(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE NOT NULL,
                source_bot TEXT NOT NULL,
                collected_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_link(link: str, source_bot: str, db_path: Path = DB_PATH) -> bool:
    """Insert a link. Returns True if newly saved, False if it was a duplicate."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO links (link, source_bot) VALUES (?, ?)",
            (link, source_bot),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_all_links(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT link, source_bot, collected_at FROM links ORDER BY collected_at DESC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def count_links(db_path: Path = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM links")
        return cur.fetchone()[0]
    finally:
        conn.close()
