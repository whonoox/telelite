"""Telegram chat folders ("dialog filters"), applied locally.

Telegram only sends each folder's *rules*; every client works out which
chats belong to it. These functions do that over plain chat records built in
telegram_client._chat_record, so the rules are testable without a Telegram
connection.

A chat record is a dict with at least: chat_id, kind ("contact",
"non_contact", "bot", "group" or "broadcast"), unread (bool), muted (bool),
archived (bool), and date (datetime or None).
"""

from datetime import datetime, timezone

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


def in_folder(folder, chat):
    chat_id = chat["chat_id"]
    # Chats added to a folder by hand always belong to it; the category
    # flags and exclude_* options only apply to everything else.
    if chat_id in folder["pinned"] or chat_id in folder["include"]:
        return True
    if chat_id in folder["exclude"]:
        return False
    if folder["exclude_muted"] and chat["muted"]:
        return False
    if folder["exclude_read"] and not chat["unread"]:
        return False
    if folder["exclude_archived"] and chat["archived"]:
        return False
    return chat["kind"] in folder["kinds"]


def chats_in_folder(folder, chats):
    """The folder's chats in the order Telegram shows them: the folder's own
    pinned chats first (in their pinned order), then newest first."""
    members = [c for c in chats if in_folder(folder, c)]
    pinned_order = {chat_id: i for i, chat_id in enumerate(folder["pinned"])}
    pinned = sorted(
        (c for c in members if c["chat_id"] in pinned_order),
        key=lambda c: pinned_order[c["chat_id"]],
    )
    rest = sorted(
        (c for c in members if c["chat_id"] not in pinned_order),
        key=lambda c: c["date"] or _OLDEST,
        reverse=True,
    )
    return pinned + rest


def unread_chat_count(folder, chats):
    return sum(1 for c in chats if c["unread"] and in_folder(folder, c))
