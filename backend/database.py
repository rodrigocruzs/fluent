"""
SQLite user store via Python's built-in sqlite3.
Schema: users(id, email, hashed_password, created_at)
"""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "fluent.db"


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                email           TEXT    UNIQUE NOT NULL,
                hashed_password TEXT    NOT NULL,
                created_at      REAL    NOT NULL
            )
        """)


def create_user(email: str, hashed_password: str) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO users (email, hashed_password, created_at) VALUES (?, ?, ?)",
            (email.lower().strip(), hashed_password, time.time()),
        )
        return cur.lastrowid


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
