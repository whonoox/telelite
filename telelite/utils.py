def parse_chat_id(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
