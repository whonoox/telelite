import io
import os
import time

from PIL import Image

from . import config
from .telegram_client import download_avatar, download_avatars

# Small enough for a feature-phone screen and connection: this is a chat-list
# icon meant to be recognizable next to a name, not a photo viewer. J2ME will
# ask for "png" (MIDP 2.0 only *mandates* PNG decoding; JPEG support varies
# by device), the browser client gets "jpeg" (smaller for photographic
# content, and every browser we target decodes it fine).
THUMBNAIL_SIZE_PX = 48
JPEG_QUALITY = 70

_PIL_FORMATS = {"jpeg": "JPEG", "png": "PNG"}


def _cache_dir():
    path = os.path.abspath(config.AVATAR_CACHE_PATH)
    os.makedirs(path, exist_ok=True)
    return path


def _thumbnail_path(chat_id, fmt):
    return os.path.join(_cache_dir(), f"{chat_id}.{fmt}")


def _no_photo_marker_path(chat_id):
    # Shared across formats: once we know a chat has no photo, don't spend
    # a second Telegram round-trip finding that out again for another
    # format (e.g. browser asks for jpeg, then J2ME later asks for png).
    return os.path.join(_cache_dir(), f"{chat_id}.nophoto")


def _is_fresh(path):
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < config.AVATAR_CACHE_TTL_HOURS


def _resize(raw_bytes, pil_fmt):
    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert("RGB" if pil_fmt == "JPEG" else "RGBA")
    img.thumbnail((THUMBNAIL_SIZE_PX, THUMBNAIL_SIZE_PX), Image.LANCZOS)
    out = io.BytesIO()
    if pil_fmt == "JPEG":
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    else:
        img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _has_fresh_no_photo_marker(chat_id):
    return _is_fresh(_no_photo_marker_path(chat_id))


def _read_fresh_thumbnail(chat_id, fmt):
    path = _thumbnail_path(chat_id, fmt)
    if not _is_fresh(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def _write_thumbnail(chat_id, fmt, thumbnail):
    with open(_thumbnail_path(chat_id, fmt), "wb") as f:
        f.write(thumbnail)


def _write_no_photo_marker(chat_id):
    open(_no_photo_marker_path(chat_id), "wb").close()


def get_avatar_thumbnail(session_string, chat_id, fmt="jpeg"):
    """Returns thumbnail bytes for chat_id in the given format ('jpeg' or
    'png'), or None if the chat has no profile photo. Disk-cached for
    AVATAR_CACHE_TTL_HOURS. Raises TeleliteError on a Telegram-side failure
    (cache misses only -- a fresh/cached hit never touches the network)."""
    pil_fmt = _PIL_FORMATS[fmt]
    if _has_fresh_no_photo_marker(chat_id):
        return None
    cached = _read_fresh_thumbnail(chat_id, fmt)
    if cached is not None:
        return cached

    raw = download_avatar(session_string, chat_id)
    if raw is None:
        _write_no_photo_marker(chat_id)
        return None

    thumbnail = _resize(raw, pil_fmt)
    _write_thumbnail(chat_id, fmt, thumbnail)
    return thumbnail


def get_avatar_thumbnails(session_string, chat_ids, fmt="jpeg"):
    """Batch form of get_avatar_thumbnail for /chats/avatars. All cache
    misses are fetched over a SINGLE Telegram connection, then resized and
    cached. Returns {chat_id: thumbnail_bytes|None}. A chat is None when it
    has no photo OR when its fetch was skipped/failed this round; skipped
    chats are deliberately left uncached so a wrong "no photo" fact is never
    persisted for the cache TTL."""
    pil_fmt = _PIL_FORMATS[fmt]
    result = {chat_id: None for chat_id in chat_ids}
    misses = []
    for chat_id in chat_ids:
        if _has_fresh_no_photo_marker(chat_id):
            continue
        cached = _read_fresh_thumbnail(chat_id, fmt)
        if cached is not None:
            result[chat_id] = cached
        else:
            misses.append(chat_id)

    if misses:
        fetched = download_avatars(session_string, misses)
        for chat_id in misses:
            if chat_id not in fetched:
                continue
            raw = fetched[chat_id]
            if raw is None:
                _write_no_photo_marker(chat_id)
                result[chat_id] = None
            else:
                thumbnail = _resize(raw, pil_fmt)
                _write_thumbnail(chat_id, fmt, thumbnail)
                result[chat_id] = thumbnail
    return result
