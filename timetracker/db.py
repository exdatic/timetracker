"""SQLite storage, mirroring the Room schema of the Android app."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "timetracker.db"
_DB_PATH_OVERRIDE: ContextVar[Path | None] = ContextVar("timetracker_db_path", default=None)
_DB_LOCK = threading.RLock()
_SCHEMA_LOCK = threading.RLock()
_SCHEMA_READY: set[Path] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordTypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '',
    color_id INTEGER NOT NULL DEFAULT 0,
    color_int TEXT NOT NULL DEFAULT '',
    default_duration INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    hidden INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color_id INTEGER NOT NULL DEFAULT 0,
    color_int TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS recordTypeCategories (
    record_type_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    PRIMARY KEY (record_type_id, category_id)
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    time_started INTEGER NOT NULL,
    time_ended INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_records_range ON records (time_started, time_ended);

CREATE TABLE IF NOT EXISTS runningRecords (
    id INTEGER PRIMARY KEY,
    time_started INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS recordTags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '',
    color_id INTEGER NOT NULL DEFAULT 0,
    color_int TEXT NOT NULL DEFAULT '',
    icon_color_source INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    value_type TEXT NOT NULL DEFAULT 'none',
    value_suffix TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS recordToRecordTag (
    record_id INTEGER NOT NULL,
    record_tag_id INTEGER NOT NULL,
    PRIMARY KEY (record_id, record_tag_id)
);

CREATE TABLE IF NOT EXISTS runningRecordToRecordTag (
    running_record_id INTEGER NOT NULL,
    record_tag_id INTEGER NOT NULL,
    PRIMARY KEY (running_record_id, record_tag_id)
);

CREATE TABLE IF NOT EXISTS recordTypeToTag (
    record_type_id INTEGER NOT NULL,
    record_tag_id INTEGER NOT NULL,
    PRIMARY KEY (record_type_id, record_tag_id)
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_type TEXT NOT NULL,
    id_value INTEGER NOT NULL,
    range TEXT NOT NULL,
    type TEXT NOT NULL,
    value INTEGER NOT NULL,
    subtype TEXT NOT NULL,
    days_of_week TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'
);

CREATE TABLE IF NOT EXISTS prefs (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path() -> Path:
    """Database location; override with ``TIMETRACKER_DB``."""
    return _DB_PATH_OVERRIDE.get() or Path(os.environ.get("TIMETRACKER_DB", DEFAULT_DB_PATH))


@contextmanager
def use_database(path: Path) -> Iterator[None]:
    """Temporarily route repository calls to another database.

    The override is context-local, so building a replacement database cannot
    redirect concurrent Streamlit sessions.
    """
    token = _DB_PATH_OVERRIDE.set(path)
    try:
        yield
    finally:
        _DB_PATH_OVERRIDE.reset(token)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection, create the schema if needed, and commit on success."""
    with _DB_LOCK:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # Write-ahead logging lets readers work while a writer is busy.
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            with _SCHEMA_LOCK:
                # Creating the schema on every connection is wasteful; do it
                # once per database file.
                if path not in _SCHEMA_READY:
                    conn.executescript(SCHEMA)
                    _SCHEMA_READY.add(path)
            yield conn
            conn.commit()
        finally:
            conn.close()


@contextmanager
def database_lock() -> Iterator[None]:
    """Prevent live reads or writes while replacing the database file."""
    with _DB_LOCK:
        yield


@contextmanager
def schema_lock() -> Iterator[None]:
    """Keep the schema bookkeeping stable while a database file is built or replaced."""
    with _SCHEMA_LOCK:
        yield
        _SCHEMA_READY.discard(db_path())


def reset_database() -> None:
    """Drop every table and recreate an empty schema."""
    with _SCHEMA_LOCK:
        _SCHEMA_READY.discard(db_path())
        with connect() as conn:
            tables = [
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in tables:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.executescript(SCHEMA)
