from . import config


def is_allowed_user(telegram_user_id):
    allowed = config.TELEGRAM_ALLOWED_USER_IDS
    return not allowed or telegram_user_id in allowed


def parse_chat_id(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
