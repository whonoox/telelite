from unittest.mock import patch

from telelite import db
from telelite.telegram_client import TeleliteError
from .conftest import auth_header


# ---- login/request ----


def test_login_request_missing_phone_number(client):
    resp = client.post("/login/request", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_request"


def test_login_request_success(client):
    with patch("telelite.api.send_code") as mock_send_code:
        mock_send_code.return_value = ("session-string", "phone-code-hash")
        resp = client.post("/login/request", json={"phone_number": "+10000000000"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "pending_id" in data
    assert db.get_pending_login(data["pending_id"]) is not None


def test_login_request_telegram_error(client):
    with patch("telelite.api.send_code") as mock_send_code:
        mock_send_code.side_effect = TeleliteError("Invalid phone number.", code="invalid_phone")
        resp = client.post("/login/request", json={"phone_number": "bad"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "invalid_phone"
    assert data["message"] == "Invalid phone number."


def test_login_request_flood_wait_returns_429(client):
    with patch("telelite.api.send_code") as mock_send_code:
        mock_send_code.side_effect = TeleliteError(
            "Rate limited by Telegram, please wait.", code="flood_wait", retry_after=30
        )
        resp = client.post("/login/request", json={"phone_number": "+10000000000"})
    assert resp.status_code == 429
    data = resp.get_json()
    assert data["error"] == "flood_wait"
    assert data["retry_after"] == 30


# ---- login/verify ----


def test_login_verify_missing_fields(client):
    resp = client.post("/login/verify", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_request"


def test_login_verify_unknown_pending_id(client):
    resp = client.post("/login/verify", json={"pending_id": "nope", "code": "12345"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "login_expired"


def test_login_verify_success_creates_session(client):
    with patch("telelite.api.send_code") as mock_send_code:
        mock_send_code.return_value = ("session-string", "phone-code-hash")
        resp = client.post("/login/request", json={"phone_number": "+10000000000"})
    pending_id = resp.get_json()["pending_id"]

    with patch("telelite.api.verify_code") as mock_verify:
        mock_verify.return_value = ("new-session-string", 12345)
        resp = client.post("/login/verify", json={"pending_id": pending_id, "code": "54321"})
    assert resp.status_code == 200
    token = resp.get_json()["token"]
    assert db.get_session(token) is not None
    assert db.get_pending_login(pending_id) is None  # consumed


def test_login_verify_needs_password(client):
    with patch("telelite.api.send_code") as mock_send_code:
        mock_send_code.return_value = ("session-string", "phone-code-hash")
        resp = client.post("/login/request", json={"phone_number": "+10000000000"})
    pending_id = resp.get_json()["pending_id"]

    with patch("telelite.api.verify_code") as mock_verify:
        mock_verify.side_effect = TeleliteError("2FA password required.", code="needs_password")
        resp = client.post("/login/verify", json={"pending_id": pending_id, "code": "54321"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "needs_password"


# ---- auth guard ----


def test_chats_requires_auth(client):
    resp = client.get("/chats")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "not_authenticated"


def test_chats_rejects_invalid_token(client):
    resp = client.get("/chats", headers=auth_header("not-a-real-token"))
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "session_expired"


def test_auth_accepts_cookie_as_well_as_bearer(client, session_token):
    token, _ = session_token
    with patch("telelite.api.list_dialogs") as mock_dialogs:
        mock_dialogs.return_value = []
        client.set_cookie("telelite_token", token)
        resp = client.get("/chats")
    assert resp.status_code == 200


# ---- chats ----


def test_chats_success_passes_through_can_reply(client, session_token):
    token, _ = session_token
    with patch("telelite.api.list_dialogs") as mock_dialogs:
        mock_dialogs.return_value = [
            {
                "chat_id": 1,
                "name": "Regular Chat",
                "unread_count": 2,
                "last_message": "hi",
                "last_message_date": None,
                "can_reply": True,
            },
            {
                "chat_id": 2,
                "name": "Broadcast Channel",
                "unread_count": 0,
                "last_message": None,
                "last_message_date": None,
                "can_reply": False,
            },
        ]
        resp = client.get("/chats", headers=auth_header(token))
    assert resp.status_code == 200
    chats = resp.get_json()["chats"]
    assert chats[0]["can_reply"] is True
    assert chats[1]["can_reply"] is False


def test_list_dialogs_can_reply_self_owned_channel():
    import pytest
    from unittest.mock import AsyncMock, MagicMock
    from telelite.telegram_client import _list_dialogs

    class DummyEntity:
        def __init__(self, title, broadcast=False, creator=False, admin_rights=None):
            self.title = title
            self.broadcast = broadcast
            self.creator = creator
            self.admin_rights = admin_rights

    class DummyDialog:
        def __init__(self, id, name, entity, unread_count=0):
            self.id = id
            self.name = name
            self.entity = entity
            self.unread_count = unread_count

    d1 = DummyDialog(1, "Regular Chat", DummyEntity("Regular Chat", broadcast=False))
    d2 = DummyDialog(2, "Other Channel", DummyEntity("Other Channel", broadcast=True, creator=False))
    d3 = DummyDialog(3, "Self Channel", DummyEntity("Self Channel", broadcast=True, creator=True))
    
    admin_rights = MagicMock()
    admin_rights.post_messages = True
    d4 = DummyDialog(4, "Admin Channel", DummyEntity("Admin Channel", broadcast=True, creator=False, admin_rights=admin_rights))

    mock_client = AsyncMock()
    mock_client.get_dialogs.return_value = [d1, d2, d3, d4]

    result = pytest.Stash() if False else None
    import asyncio
    res = asyncio.run(_list_dialogs(mock_client))
    assert res[0]["can_reply"] is True
    assert res[1]["can_reply"] is False
    assert res[2]["can_reply"] is True
    assert res[3]["can_reply"] is True


# ---- messages ----


def test_get_messages_rejects_non_integer_chat_id(client, session_token):
    token, _ = session_token
    resp = client.get("/chats/not-a-number/messages", headers=auth_header(token))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_request"


def test_get_messages_passes_pagination_params(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_messages") as mock_get_messages:
        mock_get_messages.return_value = []
        resp = client.get(
            "/chats/123/messages?limit=10&before_id=555", headers=auth_header(token)
        )
    assert resp.status_code == 200
    args, kwargs = mock_get_messages.call_args
    assert kwargs["before_id"] == 555
    assert kwargs["limit"] == 10


def test_get_messages_clamps_limit_to_50(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_messages") as mock_get_messages:
        mock_get_messages.return_value = []
        client.get("/chats/123/messages?limit=999", headers=auth_header(token))
    _, kwargs = mock_get_messages.call_args
    assert kwargs["limit"] == 50


def test_post_message_requires_text(client, session_token):
    token, _ = session_token
    resp = client.post("/chats/123/messages", json={}, headers=auth_header(token))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_request"


def test_post_message_success(client, session_token):
    token, _ = session_token
    with patch("telelite.api.send_message") as mock_send:
        mock_send.return_value = {"id": 42, "date": "2026-01-01T00:00:00+00:00"}
        resp = client.post(
            "/chats/123/messages", json={"text": "hello"}, headers=auth_header(token)
        )
    assert resp.status_code == 200
    assert resp.get_json()["message"]["id"] == 42


# ---- avatar ----


def test_avatar_requires_auth(client):
    resp = client.get("/chats/123/avatar")
    assert resp.status_code == 401


def test_avatar_rejects_non_integer_chat_id(client, session_token):
    token, _ = session_token
    resp = client.get("/chats/not-an-id/avatar", headers=auth_header(token))
    assert resp.status_code == 400


def test_avatar_404_when_no_photo(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_avatar_thumbnail") as mock_thumb:
        mock_thumb.return_value = None
        resp = client.get("/chats/123/avatar", headers=auth_header(token))
    assert resp.status_code == 404


def test_avatar_returns_jpeg_by_default(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_avatar_thumbnail") as mock_thumb:
        mock_thumb.return_value = b"fake-jpeg-bytes"
        resp = client.get("/chats/123/avatar", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.data == b"fake-jpeg-bytes"
    mock_thumb.assert_called_once_with("fake-telethon-session-string", 999999, 123, fmt="jpeg")


def test_avatar_supports_png_for_j2me(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_avatar_thumbnail") as mock_thumb:
        mock_thumb.return_value = b"fake-png-bytes"
        resp = client.get("/chats/123/avatar?fmt=png", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    mock_thumb.assert_called_once_with("fake-telethon-session-string", 999999, 123, fmt="png")


def test_avatar_flood_wait_returns_429(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_avatar_thumbnail") as mock_thumb:
        mock_thumb.side_effect = TeleliteError("Rate limited.", code="flood_wait", retry_after=5)
        resp = client.get("/chats/123/avatar", headers=auth_header(token))
    assert resp.status_code == 429


# ---- avatar batch (J2ME) ----


def test_avatar_batch_requires_auth(client):
    resp = client.get("/chats/avatars?ids=1,2")
    assert resp.status_code == 401


def test_avatar_batch_requires_ids(client, session_token):
    token, _ = session_token
    resp = client.get("/chats/avatars", headers=auth_header(token))
    assert resp.status_code == 400


def test_avatar_batch_rejects_non_integer_id(client, session_token):
    token, _ = session_token
    resp = client.get("/chats/avatars?ids=1,not-a-number", headers=auth_header(token))
    assert resp.status_code == 400


def test_avatar_batch_rejects_too_many_ids(client, session_token):
    token, _ = session_token
    ids = ",".join(str(i) for i in range(51))
    resp = client.get(f"/chats/avatars?ids={ids}", headers=auth_header(token))
    assert resp.status_code == 400


def test_avatar_batch_frames_mixed_results(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_avatar_thumbnails") as mock_thumb:
        mock_thumb.return_value = {1: None, 2: b"abc", 3: None}
        resp = client.get("/chats/avatars?ids=1,2,3", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.mimetype == "application/octet-stream"
    # flag byte 0 (no photo), flag byte 1 + 4-byte length (3) + b"abc", flag byte 0
    assert resp.data == b"\x00" + b"\x01" + b"\x00\x00\x00\x03" + b"abc" + b"\x00"
    mock_thumb.assert_called_once_with("fake-telethon-session-string", 999999, [1, 2, 3], fmt="jpeg")


def test_avatar_batch_stops_early_on_flood_wait(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_avatar_thumbnails") as mock_thumb:
        # Partial dict: the batch function stopped at chat 1 (flood_wait),
        # so chats 2 and 3 were never fetched. The endpoint must render
        # them as no-photo and must not make any further Telegram calls.
        mock_thumb.return_value = {1: None}
        resp = client.get("/chats/avatars?ids=1,2,3", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.data == b"\x00\x00\x00"  # all three marked as no-photo
    mock_thumb.assert_called_once_with("fake-telethon-session-string", 999999, [1, 2, 3], fmt="jpeg")


def test_avatar_batch_default_and_png_format(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_avatar_thumbnails") as mock_thumb:
        mock_thumb.return_value = {1: b"x"}
        client.get("/chats/avatars?ids=1", headers=auth_header(token))
        mock_thumb.assert_called_with("fake-telethon-session-string", 999999, [1], fmt="jpeg")

        client.get("/chats/avatars?ids=1&fmt=png", headers=auth_header(token))
        mock_thumb.assert_called_with("fake-telethon-session-string", 999999, [1], fmt="png")


# ---- logout ----


def test_logout_deletes_session_and_clears_cookie(client, session_token):
    token, _ = session_token
    with patch("telelite.api.log_out") as mock_log_out:
        resp = client.post("/logout", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert db.get_session(token) is None
    mock_log_out.assert_called_once()


def test_cors_open_for_api_but_not_web(client):
    origin = {"Origin": "https://evil.example"}
    assert "Access-Control-Allow-Origin" in client.get("/chats", headers=origin).headers
    assert "Access-Control-Allow-Credentials" not in client.get("/chats", headers=origin).headers
    assert "Access-Control-Allow-Origin" not in client.get("/web/login", headers=origin).headers


def test_saved_messages_summary_hides_own_name_and_photo():
    from types import SimpleNamespace
    from telelite.telegram_client import _dialog_summary

    me = SimpleNamespace(is_self=True, photo=object())
    d = SimpleNamespace(id=99, name="My Name", entity=me, unread_count=0)
    s = _dialog_summary(d)
    assert s["name"] == "Saved Messages" and s["has_photo"] is False and s["is_self"] is True
