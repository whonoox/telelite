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


def _extract_pending_id(resp):
    # login_code.html renders `pending_id` into a hidden input.
    body = resp.get_data(as_text=True)
    marker = 'name="pending_id" value="'
    start = body.index(marker) + len(marker)
    end = body.index('"', start)
    return body[start:end]
