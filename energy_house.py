"""energy_house.py
Simple file storage and metadata recorder for the bot.
Stores uploaded files that passed validation into a dated directory under an archive root,
records metadata in a SQLite DB, and deduplicates by MD5 hash (to interoperate with the existing
HASHES_FILE in main.py which uses MD5).

API:
- init_energy_house(archive_root: str = "archive_files", db_path: str = "archive.db", hashes_file: str = "hashes.txt")
- store_file_from_bytes(file_bytes: bytes, original_name: str, user_id: int, message_id: int|None, mime: str|None) -> (storage_path:str, created:bool)
- file_exists(md5_hash: str) -> bool

This module is synchronous (file and DB IO). Call from async code via asyncio.to_thread(...) if needed.
"""

import os
import sqlite3
import hashlib
import uuid
import datetime
from pathlib import Path
from typing import Optional, Tuple

_archive_root: Path = Path("archive_files")
_db_path: str = "archive.db"
_hashes_file: str = "hashes.txt"
_conn: Optional[sqlite3.Connection] = None


def _ensure_dirs():
    _archive_root.mkdir(parents=True, exist_ok=True)


def init_energy_house(archive_root: str = "archive_files", db_path: str = "archive.db", hashes_file: str = "hashes.txt") -> None:
    """Initialize module-level paths and ensure DB is created."""
    global _archive_root, _db_path, _hashes_file, _conn
    _archive_root = Path(archive_root)
    _db_path = db_path
    _hashes_file = hashes_file
    _ensure_dirs()

    # open/create sqlite DB and table
    _conn = sqlite3.connect(_db_path, check_same_thread=False)
    cur = _conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stored_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            user_id INTEGER,
            original_name TEXT,
            storage_path TEXT,
            mime TEXT,
            md5_hash TEXT UNIQUE,
            size INTEGER,
            stored_at TEXT
        )
        """
    )
    _conn.commit()


def _md5_of_bytes(b: bytes) -> str:
    m = hashlib.md5()
    m.update(b)
    return m.hexdigest()


def _sanitize_filename(name: str) -> str:
    if not name:
        return "file"
    # keep safe characters only
    return "".join(c for c in name if c.isalnum() or c in "._- ")[:200].strip()


def file_exists(md5_hash: str) -> bool:
    global _conn
    if not md5_hash:
        return False
    if _conn is None:
        init_energy_house()
    cur = _conn.cursor()
    cur.execute("SELECT 1 FROM stored_files WHERE md5_hash = ? LIMIT 1", (md5_hash,))
    return cur.fetchone() is not None


def _append_hashes_file(md5_hash: str) -> None:
    try:
        with open(_hashes_file, "a") as f:
            f.write(md5_hash + "\n")
    except Exception:
        pass


def store_file_from_bytes(file_bytes: bytes, original_name: Optional[str], user_id: int, message_id: Optional[int], mime: Optional[str]) -> Tuple[str, bool]:
    """Store the provided bytes as a file in the archive and record metadata.

    Returns (storage_path, created) where created==False indicates the file was already present (deduplicated).
    """
    global _conn
    if _conn is None:
        init_energy_house()

    md5_hash = _md5_of_bytes(file_bytes)
    cur = _conn.cursor()
    cur.execute("SELECT storage_path FROM stored_files WHERE md5_hash = ?", (md5_hash,))
    row = cur.fetchone()
    if row:
        return row[0], False

    # Build dated subdir
    now = datetime.datetime.utcnow()
    subdir = _archive_root / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
    subdir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_filename(original_name or md5_hash)
    filename = f"{md5_hash[:16]}-{safe_name}"
    final_path = subdir / filename

    # Write to temp then move
    tmp_name = f".tmp-{uuid.uuid4().hex}"
    tmp_path = subdir / tmp_name
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)
    os.replace(tmp_path, final_path)

    size = final_path.stat().st_size

    cur.execute(
        """
        INSERT INTO stored_files (message_id, user_id, original_name, storage_path, mime, md5_hash, size, stored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (message_id, user_id, original_name, str(final_path), mime, md5_hash, size, now.isoformat()),
    )
    _conn.commit()

    # For backward compatibility with existing code that uses HASHES_FILE, append the md5
    _append_hashes_file(md5_hash)

    return str(final_path), True
