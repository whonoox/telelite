import io
import os
from unittest.mock import patch

import pytest
from PIL import Image

from telelite import avatars


def _fake_photo_bytes(size=(200, 200), mode="RGB", color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_returns_none_and_caches_when_no_photo(app):
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = None
        assert avatars.get_avatar_thumbnail("session", 1, 111, fmt="jpeg") is None
        assert avatars.get_avatar_thumbnail("session", 1, 111, fmt="jpeg") is None
    # Second call must have hit the "no photo" cache, not Telegram again.
    assert mock_download.call_count == 1


def test_no_photo_result_shared_across_formats(app):
    """Confirming 'no photo' for jpeg shouldn't cost a second Telegram
    round-trip when png is requested for the same chat later."""
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = None
        avatars.get_avatar_thumbnail("session", 1, 222, fmt="jpeg")
        avatars.get_avatar_thumbnail("session", 1, 222, fmt="png")
    assert mock_download.call_count == 1


def test_downloads_resizes_and_caches_thumbnail(app):
    raw = _fake_photo_bytes()
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = raw
        thumb = avatars.get_avatar_thumbnail("session", 1, 333, fmt="jpeg")
        assert thumb is not None
        assert thumb != raw  # actually resized, not passed through

        img = Image.open(io.BytesIO(thumb))
        assert img.format == "JPEG"
        assert max(img.size) <= avatars.THUMBNAIL_SIZE_PX

        # Second call is a cache hit -- no second Telegram round-trip.
        thumb_again = avatars.get_avatar_thumbnail("session", 1, 333, fmt="jpeg")
        assert thumb_again == thumb
    assert mock_download.call_count == 1


def test_png_format_for_j2me(app):
    raw = _fake_photo_bytes()
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = raw
        thumb = avatars.get_avatar_thumbnail("session", 1, 444, fmt="png")
    img = Image.open(io.BytesIO(thumb))
    assert img.format == "PNG"


# ---- batch form (used by /chats/avatars for J2ME) ----


def test_batch_fetches_all_misses_with_single_connection(app):
    raw = _fake_photo_bytes()
    with patch("telelite.avatars.download_avatars") as mock_downloads:
        mock_downloads.return_value = {1: raw, 2: raw, 3: raw}
        result = avatars.get_avatar_thumbnails("session", 1, [1, 2, 3], fmt="jpeg")
    assert set(result) == {1, 2, 3}
    # The whole point of the batch endpoint: one download call (one Telegram
    # connection) for N cold-cache avatars, not N connections.
    mock_downloads.assert_called_once_with("session", [1, 2, 3])


def test_batch_only_fetches_cache_misses(app):
    # Pre-warm: chat 1 has a cached thumbnail, chat 2 is a known no-photo.
    avatars._write_thumbnail(1, 1, "jpeg", b"cached-thumb")
    avatars._write_no_photo_marker(1, 2)
    with patch("telelite.avatars.download_avatars") as mock_downloads:
        mock_downloads.return_value = {3: _fake_photo_bytes()}
        result = avatars.get_avatar_thumbnails("session", 1, [1, 2, 3], fmt="jpeg")
    assert result[1] == b"cached-thumb"
    assert result[2] is None
    assert result[3] is not None
    mock_downloads.assert_called_once_with("session", [3])


def test_batch_writes_marker_only_for_verified_no_photo(app):
    with patch("telelite.avatars.download_avatars") as mock_downloads:
        # Chats 1 and 2 were never reached (flood_wait stopped the batch
        # early), so they're absent from the fetch result. Only chat 3 was
        # verified as having no photo.
        mock_downloads.return_value = {3: None}
        result = avatars.get_avatar_thumbnails("session", 1, [1, 2, 3], fmt="jpeg")
    assert result == {1: None, 2: None, 3: None}
    # A "no photo" fact must only be cached for the chat we actually verified.
    assert os.path.exists(avatars._no_photo_marker_path(1, 3))
    assert not os.path.exists(avatars._no_photo_marker_path(1, 1))
    assert not os.path.exists(avatars._no_photo_marker_path(1, 2))


def test_batch_png_resize_and_cache(app):
    raw = _fake_photo_bytes()
    with patch("telelite.avatars.download_avatars") as mock_downloads:
        mock_downloads.return_value = {5: raw}
        thumb = avatars.get_avatar_thumbnails("session", 1, [5], fmt="png")[5]
        assert thumb is not None
        img = Image.open(io.BytesIO(thumb))
        assert img.format == "PNG"
        assert max(img.size) <= avatars.THUMBNAIL_SIZE_PX

        # Second call is a cache hit -- no second Telegram batch.
        again = avatars.get_avatar_thumbnails("session", 1, [5], fmt="png")[5]
        assert again == thumb
    mock_downloads.assert_called_once_with("session", [5])


def test_cache_is_not_shared_between_accounts(app):
    # Account 1's cached view of chat 7 must not be served to account 2,
    # which may not be allowed to see that photo at all.
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.return_value = _fake_photo_bytes()
        assert avatars.get_avatar_thumbnail("session-1", 1, 7, fmt="jpeg") is not None
    with patch("telelite.avatars.download_avatar") as mock_download:
        mock_download.side_effect = ValueError("not accessible")
        with pytest.raises(ValueError):
            avatars.get_avatar_thumbnail("session-2", 2, 7, fmt="jpeg")
    with patch("telelite.avatars.download_avatars") as mock_downloads:
        mock_downloads.return_value = {}
        assert avatars.get_avatar_thumbnails("session-2", 2, [7], fmt="jpeg") == {7: None}
    mock_downloads.assert_called_once_with("session-2", [7])
