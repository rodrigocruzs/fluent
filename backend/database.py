"""
Postgres user store via psycopg2, backed by Neon.
Reads DATABASE_URL from the environment.
Schema: users(id, email, hashed_password, created_at)
"""

import os
import time
import psycopg2
import psycopg2.extras

def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    # psycopg2 doesn't support channel_binding — strip it if present
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    parsed = urlparse(url)
    params = {k: v for k, v in parse_qs(parsed.query).items() if k != "channel_binding"}
    cleaned = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in params.items()})))
    return cleaned


def _conn() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(_database_url())
    conn.autocommit = False
    return conn


def init_db():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id              SERIAL PRIMARY KEY,
                    email           TEXT   UNIQUE NOT NULL,
                    hashed_password TEXT   NOT NULL,
                    created_at      FLOAT  NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    slug        TEXT    NOT NULL,
                    name        TEXT    NOT NULL,
                    date        TEXT    NOT NULL,
                    duration    FLOAT   NOT NULL DEFAULT 0,
                    transcript  TEXT    NOT NULL DEFAULT '',
                    created_at  FLOAT   NOT NULL,
                    UNIQUE (user_id, slug)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS issues (
                    id          SERIAL PRIMARY KEY,
                    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    number      INTEGER NOT NULL,
                    category    TEXT    NOT NULL,
                    original    TEXT    NOT NULL,
                    improved    TEXT    NOT NULL,
                    explanation TEXT    NOT NULL DEFAULT ''
                )
            """)
        conn.commit()


def create_user(email: str, hashed_password: str) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, hashed_password, created_at) VALUES (%s, %s, %s) RETURNING id",
                (email.lower().strip(), hashed_password, time.time()),
            )
            row = cur.fetchone()
        conn.commit()
        return row[0]


def get_user_by_email(email: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM users WHERE email = %s",
                (email.lower().strip(),),
            )
            return cur.fetchone()


def get_user_by_id(user_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM users WHERE id = %s",
                (user_id,),
            )
            return cur.fetchone()


# ── Sessions ──────────────────────────────────────────────────────────────────

def save_session(user_id: int, slug: str, name: str, date: str,
                 duration: float, transcript: str,
                 issues: list[dict]) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sessions (user_id, slug, name, date, duration, transcript, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, slug) DO UPDATE
                    SET name       = EXCLUDED.name,
                        date       = EXCLUDED.date,
                        duration   = EXCLUDED.duration,
                        transcript = EXCLUDED.transcript
                RETURNING id
            """, (user_id, slug, name, date, duration, transcript, time.time()))
            session_id = cur.fetchone()[0]

            cur.execute("DELETE FROM issues WHERE session_id = %s", (session_id,))
            if issues:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO issues (session_id, number, category, original, improved, explanation)
                    VALUES %s
                """, [
                    (session_id, i + 1, iss.get("category", ""), iss.get("original", ""),
                     iss.get("improved", ""), iss.get("explanation", ""))
                    for i, iss in enumerate(issues)
                ])
        conn.commit()
        return session_id


def get_sessions(user_id: int) -> list[dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT s.id, s.slug, s.name, s.date, s.duration, s.transcript,
                       COUNT(i.id) AS issue_count
                FROM sessions s
                LEFT JOIN issues i ON i.session_id = s.id
                WHERE s.user_id = %s
                GROUP BY s.id
                ORDER BY s.created_at DESC
            """, (user_id,))
            return cur.fetchall()


def get_session_with_issues(user_id: int, slug: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, slug, name, date, duration, transcript
                FROM sessions WHERE user_id = %s AND slug = %s
            """, (user_id, slug))
            session = cur.fetchone()
            if not session:
                return None
            cur.execute("""
                SELECT number, category, original, improved, explanation
                FROM issues WHERE session_id = %s ORDER BY number
            """, (session["id"],))
            session = dict(session)
            session["issues"] = cur.fetchall()
            return session
