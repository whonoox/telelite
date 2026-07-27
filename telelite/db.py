import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    phone_number TEXT NOT NULL,
    encrypted_session TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_logins (
    pending_id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    phone_code_hash TEXT NOT NULL,
    encrypted_session TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _parse(iso_str):
    return datetime.fromisoformat(iso_str)


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(config.DATABASE_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.executescript(SCHEMA)


def create_pending_login(pending_id, phone_number, phone_code_hash, encrypted_session):
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_logins "
            "(pending_id, phone_number, phone_code_hash, encrypted_session, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (pending_id, phone_number, phone_code_hash, encrypted_session, _iso(_now())),
        )


def get_pending_login(pending_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_logins WHERE pending_id = ?", (pending_id,)
        ).fetchone()
    if row is None:
        return None
    created_at = _parse(row["created_at"])
    if _now() - created_at > timedelta(minutes=config.PENDING_LOGIN_TTL_MINUTES):
        delete_pending_login(pending_id)
        return None
    return dict(row)


def delete_pending_login(pending_id):
    with _connect() as conn:
        conn.execute("DELETE FROM pending_logins WHERE pending_id = ?", (pending_id,))


def create_session(token, telegram_user_id, phone_number, encrypted_session):
    now = _now()
    expires_at = now + timedelta(hours=config.SESSION_TTL_HOURS)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions "
            "(token, telegram_user_id, phone_number, encrypted_session, "
            " created_at, last_active_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                telegram_user_id,
                phone_number,
                encrypted_session,
                _iso(now),
                _iso(now),
                _iso(expires_at),
            ),
        )


def get_session(token):
    """Returns the session row and slides its expiry forward, or None if
    missing/expired (expired rows are deleted)."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        if row is None:
            return None
        if _now() > _parse(row["expires_at"]):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        now = _now()
        new_expiry = now + timedelta(hours=config.SESSION_TTL_HOURS)
        conn.execute(
            "UPDATE sessions SET last_active_at = ?, expires_at = ? WHERE token = ?",
            (_iso(now), _iso(new_expiry), token),
        )
    return dict(row)


def delete_session(token):
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def purge_expired():
    now_iso = _iso(_now())
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso,))
        cutoff = _iso(_now() - timedelta(minutes=config.PENDING_LOGIN_TTL_MINUTES))
        conn.execute("DELETE FROM pending_logins WHERE created_at < ?", (cutoff,))
