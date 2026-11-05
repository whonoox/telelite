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


def test_overview_shows_every_folder_as_a_foldable_section(client, session_token):
    token, session_string = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=SECTIONS) as mock_load:
        html = client.get("/web/chats").get_data(as_text=True)
    mock_load.assert_called_once_with(session_string)
    # No handheld stylesheet here, so Opera Mini folds each folder's links.
    assert '<style type="text/css" media="screen">' in html
    assert ('<div class="sec-h"><a name="s2" href="/web/chats?folder=2">Channels</a>'
            ' <span class="n">1</span></div>') in html
    assert '<div class="sec-h"><a name="s3" href="/web/chats?folder=3">Job</a></div>' in html
    assert html.count('<hr class="sec-end">') == 3
    assert "News &lt;b&gt;" in html  # still escaped
    # Sections are capped; the rest is one link away.
    assert html.count('class="chat') == 15 + 1
    assert 'href="/web/chats?folder=0">More in All chats' in html
    assert "More in Channels" not in html
    # Chats opened from the overview come back to the overview.
    assert "folder=" not in html.split('href="/web/chats/1?')[1].split('"')[0]


def test_overview_shortens_long_names_to_one_line(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    long_name = "Afriwork (Freelance Ethiopia)"
    view = [{"id": 0, "title": "All chats", "unread": 0, "total": 1, "chats": [_chat(7, long_name)]}]
    with patch("telelite.web.load_chat_list", return_value=view):
        overview = client.get("/web/chats").get_data(as_text=True)
        folder = client.get("/web/chats?folder=0").get_data(as_text=True)
    assert '<span class="name">Afriwork (Freelance...</span>' in overview
    assert "name=Afriwork+(Freelance+Ethiopia)" in overview  # full name in the chat
    assert f'<span class="name">{long_name}</span>' in folder


def test_folder_page_lists_one_section_and_keeps_folder_in_links(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=SECTIONS):
        html = client.get("/web/chats?folder=0").get_data(as_text=True)
    assert '<style type="text/css" media="screen,handheld">' in html
    assert html.count('class="chat') == 20
    assert 'href="/web/chats">&laquo;</a> All chats' in html
    assert "folder=0" in html.split('href="/web/chats/1?')[1].split('"')[0]


def test_unknown_folder_falls_back_to_overview(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.load_chat_list", return_value=SECTIONS):
        html = client.get("/web/chats?folder=404").get_data(as_text=True)
    assert '<a name="s0" href="/web/chats?folder=0">All chats</a>' in html


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


# ---- emoji (Opera Mini 4 blanks any text containing one) ----

def test_phone_text_drops_emoji():
    from telelite.utils import phone_text

    assert phone_text("Dagmawi Babi \U0001F1EA\U0001F1F9") == "Dagmawi Babi"
    assert phone_text("Luna's pathway \U0001F917") == "Luna's pathway"
    assert phone_text("\U0001F4E2 News  ❤️ now") == "News ❤ now"
    assert phone_text("a\U0001F468‍\U0001F4BBb") == "ab"
    assert phone_text("\U0001F525\U0001F525") == "[emoji]"
    assert phone_text("ሰላም") == "ሰላም"  # Ge'ez script stays
    assert phone_text("") == ""


def test_emoji_stripped_from_chat_list_but_kept_in_links(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    view = [{"id": 5, "title": "Fun \U0001F389", "unread": 0, "total": 1,
             "chats": [_chat(9, "Luna's pathway \U0001F917")]}]
    with patch("telelite.web.load_chat_list", return_value=view):
        html = client.get("/web/chats").get_data(as_text=True)
    assert '<span class="name">Luna&#39;s pathway</span>' in html
    assert ">Fun</a>" in html
    assert "%F0%9F%A4%97" in html  # the conversation still gets the real name


def test_emoji_stripped_from_conversation(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    msgs = [{"id": 1, "out": False, "text": "hi \U0001F44B"}, {"id": 2, "out": True, "text": "\U0001F525"}]
    with patch("telelite.web.get_messages", return_value=msgs):
        html = client.get("/web/chats/5?name=Luna \U0001F917").get_data(as_text=True)
    assert "&laquo;</a> Luna</div>" in html
    assert '<div class="msg">hi</div>' in html
    assert '<div class="msg out">[emoji]</div>' in html
