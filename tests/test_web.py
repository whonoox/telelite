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

def _chat(chat_id, name, unread=0, **extra):
    return dict(chat_id=chat_id, name=name, unread_count=unread, can_reply=True, has_photo=False, **extra)


SECTIONS = [
    {"id": 0, "title": "All chats", "unread": 1, "total": 20,
     "chats": [_chat(i, f"Chat {i}", unread=(3 if i == 1 else 0)) for i in range(1, 21)]},
    {"id": 2, "title": "Channels", "unread": 1, "total": 1, "chats": [_chat(-100123, "News <b>", unread=3)]},
    {"id": 3, "title": "Job", "unread": 0, "total": 0, "chats": []},
]


def test_chats_page_lists_folders_with_all_chats_open(client, session_token):
    token, session_string = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=SECTIONS) as mock_load:
        html = client.get("/web/chats").get_data(as_text=True)
    mock_load.assert_called_once_with(session_string)
    # Every folder is a navigable heading; the open one closes it again.
    assert ('<a class="sec-h open" name="s0" href="/web/chats?folder=-1#s0">'
            '<span class="tog">-</span> All chats <span class="n">1</span></a>') in html
    assert ('<a class="sec-h" name="s2" href="/web/chats?folder=2#s2">'
            '<span class="tog">+</span> Channels <span class="n">1</span></a>') in html
    assert 'href="/web/chats?folder=3#s3"><span class="tog">+</span> Job</a>' in html
    # Only the open folder's chats are on the page, and they remember it.
    assert html.count('class="chat') == 20
    assert "News" not in html
    assert "folder=0" in html.split('href="/web/chats/1?')[1].split('"')[0]


def test_folder_param_opens_that_folder(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=SECTIONS):
        html = client.get("/web/chats?folder=2").get_data(as_text=True)
    assert html.count('class="chat') == 1
    assert "News &lt;b&gt;" in html  # still escaped
    assert '<a class="sec-h open" name="s2" href="/web/chats?folder=-1#s2">' in html
    assert '<a class="sec-h" name="s0" href="/web/chats?folder=0#s0">' in html


def test_all_folders_can_be_closed(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=SECTIONS):
        for folder in ("-1", "404"):
            html = client.get(f"/web/chats?folder={folder}").get_data(as_text=True)
            assert 'class="chat' not in html
            assert "sec-h open" not in html
            assert html.count('class="sec-h"') == 3


def test_empty_open_folder_says_so(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=SECTIONS):
        html = client.get("/web/chats?folder=3").get_data(as_text=True)
    assert "No chats here." in html


def test_conversation_back_link_returns_to_folder(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.get_messages", return_value=[{"id": 1, "out": True, "text": "yo"}]):
        html = client.get("/web/chats/5?name=Abebe&folder=3").get_data(as_text=True)
    assert 'href="/web/chats?folder=3#s3">&laquo;</a>' in html
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
    view = [{"id": 0, "title": "All chats", "unread": 0, "total": 4, "chats": [
        {"chat_id": 99, "name": "Saved Messages", "unread_count": 0, "can_reply": True,
         "has_photo": False, "is_self": True},
        {"chat_id": 10, "name": "abebe", "unread_count": 0, "can_reply": True, "has_photo": False},
        {"chat_id": 11, "name": "Концепты", "unread_count": 0, "can_reply": True, "has_photo": False},
        {"chat_id": 12, "name": "Photo", "unread_count": 0, "can_reply": True, "has_photo": True},
    ]}]
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
