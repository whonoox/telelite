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


# ---- folders ----

FOLDER_VIEW = {
    "folders": [{"id": 2, "title": "Channels", "unread": 14}, {"id": 3, "title": "Job", "unread": 0}],
    "folder": {"id": 2, "title": "Channels"},
    "chats": [
        {"chat_id": -100123, "name": "News <b>", "unread_count": 3, "can_reply": False, "has_photo": False},
    ],
}


def test_chats_page_shows_folder_tabs_and_keeps_folder_in_links(client, session_token):
    token, session_string = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=FOLDER_VIEW) as mock_load:
        resp = client.get("/web/chats?folder=2")
    mock_load.assert_called_once_with(session_string, 2)
    html = resp.get_data(as_text=True)
    assert 'href="/web/chats?folder=3">Job</a>' in html
    assert 'class="tab on" href="/web/chats?folder=2">Channels <span class="n">14</span>' in html
    assert "folder=2" in html.split('class="chat unread"')[1].split(">")[0]
    assert "News &lt;b&gt;" in html  # still escaped


def test_chats_page_without_folder_loads_all_chats(client, session_token):
    token, session_string = session_token
    client.set_cookie("telelite_token", token)
    view = dict(FOLDER_VIEW, folder=None)
    with patch("telelite.web.load_chat_list", return_value=view) as mock_load:
        html = client.get("/web/chats").get_data(as_text=True)
    mock_load.assert_called_once_with(session_string, None)
    assert 'class="tab on" href="/web/chats">All</a>' in html


def test_conversation_back_link_returns_to_folder(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.get_messages", return_value=[{"id": 1, "out": True, "text": "yo"}]):
        html = client.get("/web/chats/5?name=Abebe&folder=3").get_data(as_text=True)
    assert 'href="/web/chats?folder=3">&laquo;</a>' in html
    assert '<input type="hidden" name="folder" value="3">' in html
    assert '<div class="msg out">yo</div>' in html


def test_reply_redirect_keeps_folder(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    page = client.get("/web/chats/5?name=Abebe&folder=3")
    csrf = page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
    with patch("telelite.web.send_message"):
        resp = client.post(
            "/web/chats/5/reply",
            data={"csrf_token": csrf, "text": "hi", "name": "Abebe", "can_reply": "1", "folder": "3"},
        )
    assert resp.status_code == 303
    assert "folder=3" in resp.headers["Location"]


# ---- placeholders / Saved Messages ----

def test_chats_page_uses_placeholder_and_saved_messages_icons(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    view = {"folders": [], "folder": None, "chats": [
        {"chat_id": 99, "name": "Saved Messages", "unread_count": 0, "can_reply": True,
         "has_photo": False, "is_self": True},
        {"chat_id": 10, "name": "abebe", "unread_count": 0, "can_reply": True, "has_photo": False},
        {"chat_id": 11, "name": "Концепты", "unread_count": 0, "can_reply": True, "has_photo": False},
        {"chat_id": 12, "name": "Photo", "unread_count": 0, "can_reply": True, "has_photo": True},
    ]}
    with patch("telelite.web.load_chat_list", return_value=view):
        html = client.get("/web/chats").get_data(as_text=True)
    assert 'src="/web/icons/saved.png"' in html
    assert 'src="/web/icons/3/A.png"' in html  # 10 % 7 == 3
    assert 'src="/web/icons/4/_.png"' in html  # no Latin letter
    assert 'src="/web/chats/12/avatar"' in html


def test_placeholder_icons_need_no_login_and_validate_input(client):
    resp = client.get("/web/icons/3/A.png")
    assert resp.status_code == 200 and resp.mimetype == "image/png"
    assert "public" in resp.headers["Cache-Control"]
    assert client.get("/web/icons/0/_.png").status_code == 200
    assert client.get("/web/icons/saved.png").status_code == 200
    assert client.get("/web/icons/7/A.png").status_code == 404
    assert client.get("/web/icons/3/AB.png").status_code == 404
    assert client.get("/web/icons/3/%D0%9A.png").status_code == 404  # Cyrillic
