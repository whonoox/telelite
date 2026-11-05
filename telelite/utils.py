import re

from flask import request

from . import config


def cookie_is_secure():
    """Mark the session cookie Secure whenever the client reached us over
    HTTPS -- directly, or via a TLS-terminating proxy like Vercel's, which
    talks plain HTTP to the app and reports the original scheme in
    X-Forwarded-Proto. Plain-HTTP setups (local dev, a LAN box for feature
    phones) still get a working cookie. A client faking the header only
    changes the flag on its own response."""
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    return request.is_secure or forwarded == "https"


def is_allowed_user(telegram_user_id):
    allowed = config.TELEGRAM_ALLOWED_USER_IDS
    return not allowed or telegram_user_id in allowed


def parse_chat_id(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# Zero-width joiner, text/emoji variation selectors and the keycap mark:
# invisible glue that only means something next to an emoji.
_EMOJI_GLUE = {"\u200d", "\ufe0e", "\ufe0f", "\u20e3"}


def phone_text(text):
    """Text Opera Mini 4 can show. It runs as a J2ME app that can't draw
    characters outside the Basic Multilingual Plane -- most emoji -- and one
    of them leaves the whole name or message blank, so they're dropped. Text
    that was only emoji becomes "[emoji]" rather than nothing."""
    if not text:
        return text
    kept = "".join(c for c in text if ord(c) <= 0xFFFF and c not in _EMOJI_GLUE)
    kept = re.sub(r"[ \t]{2,}", " ", kept).strip()
    return kept or "[emoji]"
