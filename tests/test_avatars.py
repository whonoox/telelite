import io
from unittest.mock import patch

from PIL import Image

from telelite import avatars


def _fake_photo_bytes(size=(200, 200), mode="RGB", color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_returns_none_and_caches_when_no_photo(app):
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = None
        assert avatars.get_avatar_thumbnail("session", 111, fmt="jpeg") is None
        assert avatars.get_avatar_thumbnail("session", 111, fmt="jpeg") is None
    # Second call must have hit the "no photo" cache, not Telegram again.
    assert mock_download.call_count == 1


def test_no_photo_result_shared_across_formats(app):
    """Confirming 'no photo' for jpeg shouldn't cost a second Telegram
    round-trip when png is requested for the same chat later."""
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = None
        avatars.get_avatar_thumbnail("session", 222, fmt="jpeg")
        avatars.get_avatar_thumbnail("session", 222, fmt="png")
    assert mock_download.call_count == 1


def test_downloads_resizes_and_caches_thumbnail(app):
    raw = _fake_photo_bytes()
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = raw
        thumb = avatars.get_avatar_thumbnail("session", 333, fmt="jpeg")
        assert thumb is not None
        assert thumb != raw  # actually resized, not passed through

        img = Image.open(io.BytesIO(thumb))
        assert img.format == "JPEG"
        assert max(img.size) <= avatars.THUMBNAIL_SIZE_PX

        # Second call is a cache hit -- no second Telegram round-trip.
        thumb_again = avatars.get_avatar_thumbnail("session", 333, fmt="jpeg")
        assert thumb_again == thumb
    assert mock_download.call_count == 1


def test_png_format_for_j2me(app):
    raw = _fake_photo_bytes()
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = raw
        thumb = avatars.get_avatar_thumbnail("session", 444, fmt="png")
    img = Image.open(io.BytesIO(thumb))
    assert img.format == "PNG"
