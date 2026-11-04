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
