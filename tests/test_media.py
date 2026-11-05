import io
from datetime import datetime, timezone
from unittest.mock import patch

from PIL import Image
from telethon.tl import types

from telelite import photos
from telelite.telegram_client import _media_label, _pick_photo_size

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
PEER = types.PeerUser(1)


def _msg(media=None, message="", action=None):
    if action:
        return types.MessageService(id=1, peer_id=PEER, date=NOW, action=action)
    return types.Message(id=1, peer_id=PEER, date=NOW, message=message, media=media)


def _photo(*sizes):
    return types.Photo(id=1, access_hash=1, file_reference=b"", date=NOW, sizes=list(sizes), dc_id=1)


def _doc(*attributes, mime="application/octet-stream"):
    return types.MessageMediaDocument(document=types.Document(
        id=1, access_hash=1, file_reference=b"", date=NOW, mime_type=mime, size=1,
        dc_id=1, attributes=list(attributes)))


def _video(**kw):
    return types.DocumentAttributeVideo(duration=1, w=1, h=1, **kw)


def test_media_labels():
    assert _media_label(_msg(message="hi")) is None
    assert _media_label(_msg(types.MessageMediaPhoto(photo=_photo()))) == "photo"
    assert _media_label(_msg(_doc(types.DocumentAttributeSticker(alt="x", stickerset=types.InputStickerSetEmpty())))) == "sticker"
    assert _media_label(_msg(_doc(_video(), types.DocumentAttributeAnimated(), mime="video/mp4"))) == "gif"
    assert _media_label(_msg(_doc(_video(round_message=True), mime="video/mp4"))) == "video message"
    assert _media_label(_msg(_doc(_video(), mime="video/mp4"))) == "video"
    assert _media_label(_msg(_doc(types.DocumentAttributeAudio(duration=1, voice=True), mime="audio/ogg"))) == "voice"
    assert _media_label(_msg(_doc(types.DocumentAttributeAudio(duration=1), mime="audio/mpeg"))) == "audio"
    assert _media_label(_msg(_doc(types.DocumentAttributeFilename("a.pdf")))) == "file"
    assert _media_label(_msg(types.MessageMediaGeo(geo=types.GeoPointEmpty()))) == "location"
    assert _media_label(_msg(action=types.MessageActionPinMessage())) == "service message"


def test_link_preview_is_not_an_attachment():
    preview = types.MessageMediaWebPage(webpage=types.WebPageEmpty(id=1))
    assert _media_label(_msg(preview, message="see https://x.org")) is None


def test_pick_photo_size_prefers_smallest_big_enough():
    small = types.PhotoSize(type="s", w=90, h=60, size=1)
    medium = types.PhotoSize(type="m", w=320, h=213, size=1)
    large = types.PhotoSize(type="x", w=800, h=533, size=1)
    stripped = types.PhotoStrippedSize(type="i", bytes=b"")
    assert _pick_photo_size(_photo(stripped, large, small, medium)) is medium
    assert _pick_photo_size(_photo(small)) is small


def test_message_photo_is_shrunk_to_fit_a_bubble():
    raw = io.BytesIO()
    Image.new("RGB", (800, 600), "red").save(raw, format="JPEG")
    with patch("telelite.photos.download_message_photo", return_value=raw.getvalue()):
        jpeg = photos.message_photo_jpeg("s", 5, 9)
    assert Image.open(io.BytesIO(jpeg)).size == (160, 120)
    with patch("telelite.photos.download_message_photo", return_value=None):
        assert photos.message_photo_jpeg("s", 5, 9) is None


MESSAGES = [
    {"id": 1, "out": False, "text": "", "media": "photo"},
    {"id": 2, "out": True, "text": "look", "media": "photo"},
    {"id": 3, "out": False, "text": "", "media": "sticker"},
    {"id": 4, "out": False, "text": "cool clip", "media": "video"},
    {"id": 5, "out": False, "text": "plain", "media": None},
]


def test_conversation_shows_photos_and_labels_other_media(client, session_token):
    token, _ = session_token
    client.set_cookie("telelite_token", token)
    with patch("telelite.web.get_messages", return_value=MESSAGES):
        html = client.get("/web/chats/5?name=Abebe").get_data(as_text=True)
    assert '<div class="msg"><img src="/web/chats/5/photos/1.jpg" alt="[photo]"></div>' in html
    assert '<img src="/web/chats/5/photos/2.jpg" alt="[photo]"><br>look</div>' in html
    assert '<div class="msg"><span class="media">[sticker]</span></div>' in html
    assert '<span class="media">[video]</span> cool clip</div>' in html
    assert '<div class="msg">plain</div>' in html


def test_photo_route(client, session_token):
    token, session_string = session_token
    with patch("telelite.web.message_photo_jpeg", return_value=b"jpegbytes") as mock_photo:
        assert client.get("/web/chats/5/photos/9.jpg").status_code == 302  # login first
        client.set_cookie("telelite_token", token)
        resp = client.get("/web/chats/5/photos/9.jpg")
    mock_photo.assert_called_once_with(session_string, 5, 9)
    assert resp.data == b"jpegbytes" and resp.mimetype == "image/jpeg"
    assert resp.headers["Cache-Control"].startswith("private")
    with patch("telelite.web.message_photo_jpeg", return_value=None):
        assert client.get("/web/chats/5/photos/9.jpg").status_code == 404


def test_api_messages_label_media_in_text(client, session_token):
    token, _ = session_token
    with patch("telelite.api.get_messages", return_value=MESSAGES):
        data = client.get("/chats/5/messages", headers={"Authorization": f"Bearer {token}"}).get_json()
    assert [m["text"] for m in data["messages"]] == ["[photo]", "look", "[sticker]", "cool clip", "plain"]
