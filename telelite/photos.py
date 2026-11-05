"""Message photos for the browser UI, shrunk to fit a chat bubble on a
~240px feature-phone screen and to stay small over a slow connection."""

import io

from PIL import Image

from .telegram_client import download_message_photo

MAX_WIDTH_PX = 160
MAX_HEIGHT_PX = 200
JPEG_QUALITY = 60


def message_photo_jpeg(session_string, chat_id, message_id):
    """JPEG bytes of the message's photo, or None if it has none."""
    raw = download_message_photo(session_string, chat_id, message_id)
    if raw is None:
        return None
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((MAX_WIDTH_PX, MAX_HEIGHT_PX), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()
