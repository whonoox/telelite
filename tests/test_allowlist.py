from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from telelite import config, crypto, db
from telelite.telegram_client import TeleliteError, verify_code
from telelite.utils import is_allowed_user


def test_empty_allowlist_allows_everyone(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", frozenset())
    assert is_allowed_user(12345)


def test_allowlist_restricts_to_listed_ids(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", frozenset({1, 2}))
    assert is_allowed_user(2)
    assert not is_allowed_user(3)


def _fake_client(user_id):
    client = AsyncMock()
    client.get_me.return_value = SimpleNamespace(id=user_id)
    client.session.save = lambda: "new-session"
    return client


def test_verify_code_rejects_and_logs_out_disallowed_account(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", frozenset({1}))
    client = _fake_client(user_id=666)
    with patch("telelite.telegram_client._new_client", return_value=client):
        with pytest.raises(TeleliteError) as exc:
            verify_code("session", "+1000", "hash", "12345")
    assert exc.value.code == "account_not_allowed"
    client.log_out.assert_awaited_once()


def test_verify_code_accepts_allowed_account(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", frozenset({1}))
    client = _fake_client(user_id=1)
    with patch("telelite.telegram_client._new_client", return_value=client):
        assert verify_code("session", "+1000", "hash", "12345") == ("new-session", 1)
    client.log_out.assert_not_awaited()


def test_existing_session_of_disallowed_account_is_dropped(app, monkeypatch):
    # Covers turning the allowlist on after strangers already logged in.
    db.create_session("stranger", 666, "+1000", crypto.encrypt("s"))
    db.create_session("owner", 1, "+1001", crypto.encrypt("s"))
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", frozenset({1}))
    assert db.get_session("stranger") is None
    assert db.get_session("owner") is not None
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", frozenset())
    assert db.get_session("stranger") is None  # deleted, not just hidden


def test_web_login_shows_rejection(client, monkeypatch):
    with patch("telelite.web.send_code", return_value=("s", "hash")):
        resp = client.post("/web/login", data={"phone_number": "+1000"})
    pending_id = resp.get_data(as_text=True).split('name="pending_id" value="')[1].split('"')[0]
    with patch(
        "telelite.web.verify_code",
        side_effect=TeleliteError("This Telegram account isn't allowed on this TeleLite server.", code="account_not_allowed"),
    ):
        resp = client.post("/web/login/verify", data={"pending_id": pending_id, "code": "1"})
    assert resp.status_code == 200
    assert "allowed on this TeleLite server" in resp.get_data(as_text=True)
    assert "telelite_token" not in resp.headers.get("Set-Cookie", "")
