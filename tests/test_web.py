from unittest.mock import patch

from telelite import config, db
from telelite.telegram_client import TeleliteError


def test_login_verify_sets_persistent_cookie(client):
    """The /web login cookie must carry Max-Age/Expires, not be a
    browser session cookie -- feature-phone browsers routinely close
    between visits and would otherwise drop it, forcing a re-login even
    though the server-side session is still valid."""
    with patch("telelite.web.send_code") as mock_send_code:
        mock_send_code.return_value = ("session-string", "phone-code-hash")
        resp = client.post("/web/login", data={"phone_number": "+10000000000"})
    pending_id = resp.request.path and _extract_pending_id(resp)

    with patch("telelite.web.verify_code") as mock_verify:
        mock_verify.return_value = ("new-session-string", 12345)
        resp = client.post(
            "/web/login/verify", data={"pending_id": pending_id, "code": "54321"}
        )

    assert resp.status_code == 302
    set_cookie = resp.headers.get("Set-Cookie")
    assert set_cookie is not None
    assert "Max-Age" in set_cookie
    assert f"Max-Age={config.SESSION_TTL_HOURS * 3600}" in set_cookie


def test_authenticated_request_slides_cookie_expiry(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    resp = client.get("/web/chats")
    set_cookie = resp.headers.get("Set-Cookie")
    assert set_cookie is not None
    assert f"Max-Age={config.SESSION_TTL_HOURS * 3600}" in set_cookie
    # Server-side expiry was pushed forward too (db.get_session slides it).
    assert db.get_session(token) is not None


# ---- avatar ----


def test_avatar_requires_auth(client):
    resp = client.get("/web/chats/123/avatar")
    assert resp.status_code == 302  # redirected to login, like every other /web/* route


def test_avatar_404_when_no_photo(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.get_avatar_thumbnail") as mock_thumb:
        mock_thumb.return_value = None
        resp = client.get("/web/chats/123/avatar")
    assert resp.status_code == 404


def test_avatar_returns_jpeg_with_cache_headers(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.get_avatar_thumbnail") as mock_thumb:
        mock_thumb.return_value = b"fake-jpeg-bytes"
        resp = client.get("/web/chats/123/avatar")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.data == b"fake-jpeg-bytes"
    assert "max-age" in resp.headers.get("Cache-Control", "")
    mock_thumb.assert_called_once_with("fake-telethon-session-string", 999999, 123, fmt="jpeg")


def test_avatar_falls_back_silently_on_telegram_error(client, session_token):
    """A flaky/rate-limited avatar fetch shouldn't break the page -- it
    should degrade to no image for that one chat, not a 5xx or an error
    page in place of the whole chat list."""
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.get_avatar_thumbnail") as mock_thumb:
        mock_thumb.side_effect = TeleliteError("Rate limited.", code="flood_wait", retry_after=5)
        resp = client.get("/web/chats/123/avatar")
    assert resp.status_code == 404


def _extract_pending_id(resp):
    # login_code.html renders `pending_id` into a hidden input.
    body = resp.get_data(as_text=True)
    marker = 'name="pending_id" value="'
    start = body.index(marker) + len(marker)
    end = body.index('"', start)
    return body[start:end]


def _login_and_get_cookie(client, headers=None):
    with patch("telelite.web.send_code", return_value=("s", "hash")):
        resp = client.post("/web/login", data={"phone_number": "+1000"})
    pending_id = resp.get_data(as_text=True).split('name="pending_id" value="')[1].split('"')[0]
    with patch("telelite.web.verify_code", return_value=("new-session", 999999)):
        resp = client.post(
            "/web/login/verify", data={"pending_id": pending_id, "code": "1"}, headers=headers
        )
    return resp.headers["Set-Cookie"]


def test_cookie_is_secure_behind_https_proxy(client):
    assert "Secure" in _login_and_get_cookie(client, {"X-Forwarded-Proto": "https"})


def test_cookie_still_works_over_plain_http(client):
    assert "Secure" not in _login_and_get_cookie(client)
