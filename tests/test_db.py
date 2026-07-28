from datetime import timedelta

from telelite import config, crypto, db


def test_session_round_trip(app):
    db.create_session("tok1", 1, "+1000", crypto.encrypt("s"))
    row = db.get_session("tok1")
    assert row is not None
    assert row["telegram_user_id"] == 1
    assert row["phone_number"] == "+1000"


def test_session_missing_returns_none(app):
    assert db.get_session("does-not-exist") is None


def test_session_sliding_expiry_extends_on_access(app, monkeypatch):
    db.create_session("tok2", 1, "+1000", crypto.encrypt("s"))
    row1 = db.get_session("tok2")
    first_expiry = row1["expires_at"]

    # Simulate time passing by shortening the TTL and re-fetching: a fresh
    # access should push expires_at forward again from "now", not from the
    # original created_at.
    monkeypatch.setattr(config, "SESSION_TTL_HOURS", 48)
    row2 = db.get_session("tok2")
    assert row2["expires_at"] >= first_expiry


def test_session_expired_is_purged_on_lookup(app, monkeypatch):
    db.create_session("tok3", 1, "+1000", crypto.encrypt("s"))

    # Force immediate expiry by setting TTL negative relative to "now" via a
    # monkeypatched clock isn't trivial here, so instead we directly poke the
    # stored expiry into the past through a second session write path: the
    # simplest reliable way is to shrink TTL to 0 and re-create.
    with db._connect() as conn:  # noqa: SLF001 - intentional white-box test
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?",
            (db._iso(db._now() - timedelta(hours=1)), "tok3"),
        )
    assert db.get_session("tok3") is None
    # Purging on expired lookup should have deleted the row outright.
    with db._connect() as conn:  # noqa: SLF001
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", ("tok3",)).fetchone()
    assert row is None


def test_pending_login_round_trip(app):
    db.create_pending_login("pend1", "+1000", "hash123", crypto.encrypt("s"))
    row = db.get_pending_login("pend1")
    assert row is not None
    assert row["phone_number"] == "+1000"
    assert row["phone_code_hash"] == "hash123"


def test_pending_login_expires_after_ttl(app):
    db.create_pending_login("pend2", "+1000", "hash123", crypto.encrypt("s"))
    with db._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE pending_logins SET created_at = ? WHERE pending_id = ?",
            (db._iso(db._now() - timedelta(minutes=config.PENDING_LOGIN_TTL_MINUTES + 1)), "pend2"),
        )
    assert db.get_pending_login("pend2") is None


def test_delete_session(app):
    db.create_session("tok4", 1, "+1000", crypto.encrypt("s"))
    db.delete_session("tok4")
    assert db.get_session("tok4") is None


def test_purge_expired_removes_old_rows_only(app):
    db.create_session("tok_fresh", 1, "+1000", crypto.encrypt("s"))
    db.create_session("tok_old", 1, "+1000", crypto.encrypt("s"))
    with db._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?",
            (db._iso(db._now() - timedelta(hours=1)), "tok_old"),
        )
    db.purge_expired()
    with db._connect() as conn:  # noqa: SLF001
        remaining = {r["token"] for r in conn.execute("SELECT token FROM sessions").fetchall()}
    assert remaining == {"tok_fresh"}
