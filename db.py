"""Shared database module — SQLite + sqlite-vec for vector search and application state.

All modules import `get_connection()` from here instead of managing DB connections directly.
The sqlite-vec extension is loaded automatically on every connection.
"""

import json
import os
import sqlite3

import sqlite_vec
from dotenv import load_dotenv
from sqlite_vec import serialize_float32

load_dotenv(override=True)

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_raw_db_path = os.getenv(
    "SQLITE_DB_PATH",
    os.path.join(_PROJECT_ROOT, "data", "research.db"),
)
DB_PATH = _raw_db_path if os.path.isabs(_raw_db_path) else os.path.join(_PROJECT_ROOT, _raw_db_path)

_INIT_SQL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "init-db.sql")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with sqlite-vec loaded."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not hasattr(conn, "enable_load_extension"):
        conn.close()
        raise RuntimeError(
            "This Python build does not support SQLite extension loading.\n"
            "On macOS, use Homebrew Python instead of the python.org installer:\n"
            "  brew install python@3.13\n"
            "  uv venv --python $(brew --prefix python@3.13)/bin/python3.13\n"
            "  uv sync"
        )
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def init_db():
    """Initialize the database schema from scripts/init-db.sql."""
    conn = get_connection()
    with open(_INIT_SQL) as f:
        conn.executescript(f.read())
    conn.close()
