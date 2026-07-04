"""
Postgres user store via psycopg2, backed by Neon.
Reads DATABASE_URL from the environment.
Schema: users(id, email, hashed_password, created_at, stripe_customer_id,
              stripe_subscription_id, plan_status, trial_ends_at, current_period_end)
"""

import os
import time
import psycopg2
import psycopg2.extras
import psycopg2.pool

def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    # psycopg2 doesn't support channel_binding — strip it if present
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    parsed = urlparse(url)
    params = {k: v for k, v in parse_qs(parsed.query).items() if k != "channel_binding"}
    cleaned = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in params.items()})))
    return cleaned


# A warm Vercel Lambda instance reuses this module across invocations, so a
# process-wide pool lets requests handled by the same warm instance reuse
# already-established connections instead of paying a fresh TCP+TLS handshake
# to the (cross-region) Neon pooler on every single call. Small ceiling since
# each serverless instance only ever runs one request at a time.
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, _database_url())
    return _pool


class _PooledConnection:
    """Context manager that checks a connection out of the pool and returns
    it (instead of closing it) on exit, so the underlying TCP/TLS session
    survives across requests within the same warm Lambda instance."""

    def __init__(self):
        self._pool = _get_pool()
        self._conn = self._pool.getconn()
        self._conn.autocommit = False

    def __enter__(self) -> psycopg2.extensions.connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                self._conn.rollback()
        finally:
            self._pool.putconn(self._conn, close=exc_type is not None)


def _conn() -> _PooledConnection:
    return _PooledConnection()


def init_db():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id                     SERIAL PRIMARY KEY,
                    email                  TEXT   UNIQUE NOT NULL,
                    hashed_password        TEXT   NOT NULL,
                    created_at             FLOAT  NOT NULL,
                    stripe_customer_id     TEXT,
                    stripe_subscription_id TEXT,
                    plan_status            TEXT   NOT NULL DEFAULT 'trial',
                    trial_ends_at          FLOAT,
                    current_period_end     FLOAT
                )
            """)
            # Migrate existing tables that lack billing columns
            for col, definition in [
                ("stripe_customer_id",     "TEXT"),
                ("stripe_subscription_id", "TEXT"),
                ("plan_status",            "TEXT NOT NULL DEFAULT 'trial'"),
                ("trial_ends_at",          "FLOAT"),
                ("current_period_end",     "FLOAT"),
                ("cancel_at_period_end",   "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("google_id",              "TEXT"),
                ("name",                   "TEXT"),
                ("google_access_token",    "TEXT"),
                ("google_refresh_token",   "TEXT"),
                ("google_token_expiry",    "FLOAT"),
                # Communication Profile: JSON blob regenerated after each session.
                ("communication_profile",  "TEXT"),
            ]:
                cur.execute(f"""
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}
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
                    segments    TEXT    NOT NULL DEFAULT '[]',
                    system_audio_captured BOOLEAN NOT NULL DEFAULT TRUE,
                    meeting_type TEXT,
                    created_at  FLOAT   NOT NULL,
                    UNIQUE (user_id, slug)
                )
            """)
            for col, definition in [
                ("segments",              "TEXT NOT NULL DEFAULT '[]'"),
                ("system_audio_captured", "BOOLEAN NOT NULL DEFAULT TRUE"),
                ("meeting_type",          "TEXT"),
            ]:
                cur.execute(f"""
                    ALTER TABLE sessions ADD COLUMN IF NOT EXISTS {col} {definition}
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_meeting_types (
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    event_id     TEXT    NOT NULL,
                    meeting_type TEXT    NOT NULL,
                    updated_at   FLOAT   NOT NULL,
                    PRIMARY KEY (user_id, event_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token      TEXT    PRIMARY KEY,
                    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at FLOAT   NOT NULL,
                    used       BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
        conn.commit()


TRIAL_DAYS = 7

def create_user(email: str, hashed_password: str) -> int:
    """Insert a new user (always a fresh account). Returns user id."""
    now = time.time()
    trial_ends_at = now + TRIAL_DAYS * 86400
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (email, hashed_password, created_at, trial_ends_at)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (email.lower().strip(), hashed_password, now, trial_ends_at),
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


def user_exists(user_id: int) -> bool:
    """Cheap existence check for the auth dependency — avoids fetching and
    deserializing the full user row (bcrypt hash, tokens, etc.) on every
    authenticated request when only a yes/no is needed."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
            return cur.fetchone() is not None


# ── Sessions ──────────────────────────────────────────────────────────────────

def save_session(user_id: int, slug: str, name: str, date: str,
                 duration: float, transcript: str,
                 issues: list[dict],
                 segments: list[dict] | None = None,
                 system_audio_captured: bool = True,
                 meeting_type: str | None = None) -> int:
    import json
    segments_json = json.dumps(segments or [])
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sessions (user_id, slug, name, date, duration, transcript,
                                      segments, system_audio_captured, meeting_type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, slug) DO UPDATE
                    SET name                  = EXCLUDED.name,
                        date                  = EXCLUDED.date,
                        duration              = EXCLUDED.duration,
                        transcript            = EXCLUDED.transcript,
                        segments              = EXCLUDED.segments,
                        system_audio_captured = EXCLUDED.system_audio_captured,
                        -- Keep an existing meeting type if this save doesn't
                        -- carry one, so a session-page edit isn't overwritten.
                        meeting_type          = COALESCE(EXCLUDED.meeting_type, sessions.meeting_type)
                RETURNING id
            """, (user_id, slug, name, date, duration, transcript,
                  segments_json, system_audio_captured, meeting_type, time.time()))
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
            # Transcript text is intentionally excluded — the sessions list UI
            # only needs name/date/duration/issue-count, and transcripts can be
            # large enough to noticeably bloat this response on every launch.
            cur.execute("""
                SELECT s.id, s.slug, s.name, s.date, s.duration,
                       s.meeting_type,
                       COUNT(i.id) AS issue_count
                FROM sessions s
                LEFT JOIN issues i ON i.session_id = s.id
                WHERE s.user_id = %s
                GROUP BY s.id
                ORDER BY s.created_at DESC
            """, (user_id,))
            return cur.fetchall()


def get_recent_sessions_for_profile(user_id: int, limit: int = 8) -> list[dict]:
    """
    Most-recent sessions with their transcript and full issue list, used to
    generate the communication profile. Ordered newest-first so the prompt can
    weight recent meetings more heavily.
    """
    import json
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, slug, name, date, duration, transcript
                FROM sessions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))
            sessions = cur.fetchall()
            if not sessions:
                return []
            ids = tuple(s["id"] for s in sessions)
            cur.execute("""
                SELECT session_id, category, original, improved, explanation
                FROM issues
                WHERE session_id IN %s
                ORDER BY session_id, number
            """, (ids,))
            by_session: dict[int, list[dict]] = {}
            for row in cur.fetchall():
                by_session.setdefault(row["session_id"], []).append({
                    "category": row["category"],
                    "original": row["original"],
                    "improved": row["improved"],
                    "explanation": row["explanation"],
                })
            for s in sessions:
                s["issues"] = by_session.get(s["id"], [])
            return sessions


def save_communication_profile(user_id: int, profile_json: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET communication_profile = %s WHERE id = %s",
                (profile_json, user_id),
            )
        conn.commit()


def get_communication_profile(user_id: int) -> str | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT communication_profile FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def update_user_password(user_id: int, hashed_password: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET hashed_password = %s WHERE id = %s",
                (hashed_password, user_id),
            )
        conn.commit()


def delete_user(user_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()


def update_user_email(user_id: int, new_email: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET email = %s WHERE id = %s", (new_email, user_id))
        conn.commit()


def update_user_billing(user_id: int, **fields) -> None:
    allowed = {"stripe_customer_id", "stripe_subscription_id", "plan_status",
                "trial_ends_at", "current_period_end", "cancel_at_period_end",
                "google_access_token", "google_refresh_token", "google_token_expiry"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k} = %s" for k in updates)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE users SET {cols} WHERE id = %s",
                (*updates.values(), user_id),
            )
        conn.commit()


def get_user_by_stripe_customer(customer_id: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM users WHERE stripe_customer_id = %s",
                (customer_id,),
            )
            return cur.fetchone()


def get_user_by_google_id(google_id: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE google_id = %s", (google_id,))
            return cur.fetchone()


def upsert_google_user(google_id: str, email: str, name: str,
                       access_token: str = "", refresh_token: str = "",
                       token_expiry: float = 0) -> tuple[int, bool]:
    """Create or update a Google-authenticated user.

    Returns (user_id, is_new) where is_new is True only when this call
    inserted a brand-new account (vs. updating an existing one on re-login).
    The `xmax = 0` check is the standard Postgres trick for distinguishing an
    INSERT from an ON CONFLICT UPDATE in a single statement.
    """
    now = time.time()
    trial_ends_at = now + TRIAL_DAYS * 86400
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (email, hashed_password, created_at, trial_ends_at,
                                   google_id, name, google_access_token,
                                   google_refresh_token, google_token_expiry)
                VALUES (%s, '', %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                    SET google_id            = EXCLUDED.google_id,
                        name                 = EXCLUDED.name,
                        google_access_token  = EXCLUDED.google_access_token,
                        google_refresh_token = CASE
                            WHEN EXCLUDED.google_refresh_token != ''
                            THEN EXCLUDED.google_refresh_token
                            ELSE users.google_refresh_token END,
                        google_token_expiry  = EXCLUDED.google_token_expiry
                RETURNING id, (xmax = 0) AS is_new
            """, (email.lower().strip(), now, trial_ends_at,
                  google_id, name, access_token, refresh_token, token_expiry))
            row = cur.fetchone()
        conn.commit()
        return row[0], bool(row[1])


def create_password_reset_token(user_id: int, token: str, ttl_seconds: int = 3600) -> None:
    expires_at = time.time() + ttl_seconds
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO password_reset_tokens (token, user_id, expires_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (token) DO NOTHING""",
                (token, user_id, expires_at),
            )
        conn.commit()


def consume_password_reset_token(token: str) -> int | None:
    """Mark token used and return user_id, or None if invalid/expired/used."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT user_id, expires_at, used
                   FROM password_reset_tokens WHERE token = %s""",
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return None
            user_id, expires_at, used = row
            if used or time.time() > expires_at:
                return None
            cur.execute(
                "UPDATE password_reset_tokens SET used = TRUE WHERE token = %s",
                (token,),
            )
        conn.commit()
        return user_id


def get_session_with_issues(user_id: int, slug: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, slug, name, date, duration, transcript,
                       segments, system_audio_captured, meeting_type
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
            import json
            try:
                session["segments"] = json.loads(session.get("segments") or "[]")
            except (ValueError, TypeError):
                session["segments"] = []
            session["issues"] = cur.fetchall()
            return session


def update_session_meeting_type(user_id: int, slug: str, meeting_type: str) -> bool:
    """Set the meeting type on an existing session. Returns False if not found."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET meeting_type = %s WHERE user_id = %s AND slug = %s",
                (meeting_type, user_id, slug),
            )
            updated = cur.rowcount
        conn.commit()
        return updated > 0


def set_event_meeting_type(user_id: int, event_id: str, meeting_type: str) -> None:
    """Upsert the pre-record meeting type chosen for a calendar event."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO event_meeting_types (user_id, event_id, meeting_type, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, event_id) DO UPDATE
                    SET meeting_type = EXCLUDED.meeting_type,
                        updated_at   = EXCLUDED.updated_at
            """, (user_id, event_id, meeting_type, time.time()))
        conn.commit()


def get_event_meeting_types(user_id: int, event_ids: list[str]) -> dict[str, str]:
    """Map of event_id -> meeting_type for the given ids (only those set)."""
    if not event_ids:
        return {}
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id, meeting_type FROM event_meeting_types "
                "WHERE user_id = %s AND event_id = ANY(%s)",
                (user_id, list(event_ids)),
            )
            return {row[0]: row[1] for row in cur.fetchall()}
