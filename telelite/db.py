import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import config
from .utils import is_allowed_user

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
    if config.TURSO_DATABASE_URL:
        import libsql

        conn = libsql.connect(config.TURSO_DATABASE_URL, auth_token=config.TURSO_AUTH_TOKEN)
    else:
        os.makedirs(os.path.dirname(config.DATABASE_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(config.DATABASE_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _fetchone(conn, sql, params):
    """Returns the first row as a dict, or None. Built from cursor.description
    because libsql connections don't support sqlite3's row_factory."""
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    if row is None:
        return None
    return {col[0]: value for col, value in zip(cursor.description, row)}


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
        row = _fetchone(
            conn, "SELECT * FROM pending_logins WHERE pending_id = ?", (pending_id,)
        )
    if row is None:
        return None
    created_at = _parse(row["created_at"])
    if _now() - created_at > timedelta(minutes=config.PENDING_LOGIN_TTL_MINUTES):
        delete_pending_login(pending_id)
        return None
    return row


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
    missing/expired/no longer allowed (such rows are deleted)."""
    with _connect() as conn:
        row = _fetchone(conn, "SELECT * FROM sessions WHERE token = ?", (token,))
        if row is None:
            return None
        if _now() > _parse(row["expires_at"]) or not is_allowed_user(row["telegram_user_id"]):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        now = _now()
        new_expiry = now + timedelta(hours=config.SESSION_TTL_HOURS)
        conn.execute(
            "UPDATE sessions SET last_active_at = ?, expires_at = ? WHERE token = ?",
            (_iso(now), _iso(new_expiry), token),
        )
    return row


def delete_session(token):
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def purge_expired():
    now_iso = _iso(_now())
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso,))
        cutoff = _iso(_now() - timedelta(minutes=config.PENDING_LOGIN_TTL_MINUTES))
        conn.execute("DELETE FROM pending_logins WHERE created_at < ?", (cutoff,))
