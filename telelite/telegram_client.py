import asyncio
from datetime import datetime, timezone

from telethon import TelegramClient, utils
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl import functions, types
from telethon.tl.custom import Dialog

from . import config
from . import folders as folder_rules
from .utils import is_allowed_user


class TeleliteError(Exception):
    """Raised for any Telegram-related failure the API layer should turn
    into a clean JSON error instead of a stack trace."""

    def __init__(self, message, code="telegram_error", retry_after=None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def _run(coro):
    return asyncio.run(coro)


def _new_client(session_string=""):
    return TelegramClient(
        StringSession(session_string),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
        # Each API call is one synchronous request/response cycle. Telethon's
        # default (60s) silently sleeps through short flood-waits instead of
        # raising, which would freeze the request instead of surfacing a
        # proper "please wait" error via our FloodWaitError handling.
        flood_sleep_threshold=0,
    )


async def _with_client(session_string, fn):
    client = _new_client(session_string)
    await client.connect()
    try:
        return await fn(client)
    finally:
        await client.disconnect()


async def _send_code(phone_number):
    client = _new_client()
    await client.connect()
    try:
        result = await client.send_code_request(phone_number)
        return client.session.save(), result.phone_code_hash
    finally:
        await client.disconnect()


def send_code(phone_number):
    try:
        return _run(_send_code(phone_number))
    except FloodWaitError as e:
        raise TeleliteError(
            "Too many attempts, please wait before retrying.",
            code="flood_wait",
            retry_after=e.seconds,
        )
    except PhoneNumberInvalidError:
        raise TeleliteError("That phone number looks invalid.", code="invalid_phone")


async def _verify_code(session_string, phone_number, phone_code_hash, code, password):
    client = _new_client(session_string)
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                raise
            await client.sign_in(password=password)
        me = await client.get_me()
        if not is_allowed_user(me.id):
            # Revoke the authorization we just created so a rejected login
            # doesn't leave a live session on that account.
            try:
                await client.log_out()
            except Exception:
                pass
            raise TeleliteError(
                "This Telegram account isn't allowed on this TeleLite server.",
                code="account_not_allowed",
            )
        return client.session.save(), me.id
    finally:
        await client.disconnect()


def verify_code(session_string, phone_number, phone_code_hash, code, password=None):
    try:
        return _run(_verify_code(session_string, phone_number, phone_code_hash, code, password))
    except SessionPasswordNeededError:
        raise TeleliteError(
            "This account has 2FA enabled, a password is required.", code="needs_password"
        )
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        raise TeleliteError("That code is invalid or expired.", code="invalid_code")
    except FloodWaitError as e:
        raise TeleliteError(
            "Too many attempts, please wait before retrying.",
            code="flood_wait",
            retry_after=e.seconds,
        )


async def _resolve_entity(client, chat_id):
    """Resolve a bare integer chat_id to an input entity. Each API request
    reconnects with a fresh in-memory session, so the entity cache built up
    during a prior /chats call (which is what gives Telethon the access_hash
    it needs for channels/users) doesn't carry over. Fall back to refreshing
    the dialog list, which repopulates that cache, before giving up."""
    try:
        return await client.get_input_entity(chat_id)
    except ValueError:
        await client.get_dialogs(limit=100)
        return await client.get_input_entity(chat_id)


async def _resolve_full_entity(client, chat_id):
    """download_profile_photo needs the *full* entity, not an input entity
    -- the photo data only lives on the full one. Same fresh-connection
    cache-miss problem as _resolve_entity: refresh the dialog list once
    before giving up."""
    try:
        return await client.get_entity(chat_id)
    except ValueError:
        await client.get_dialogs(limit=100)
        return await client.get_entity(chat_id)


async def _download_avatar(client, chat_id):
    entity = await _resolve_full_entity(client, chat_id)
    return await client.download_profile_photo(entity, file=bytes, download_big=False)


def download_avatar(session_string, chat_id):
    """Raw profile-photo bytes for chat_id (Telegram serves these as JPEG),
    or None if the chat has no photo. Callers own resizing/caching -- this
    always hits Telegram."""
    try:
        return _run(_with_client(session_string, lambda c: _download_avatar(c, chat_id)))
    except FloodWaitError as e:
        raise TeleliteError(
            "Rate limited by Telegram, please wait.", code="flood_wait", retry_after=e.seconds
        )
    except TeleliteError:
        raise
    except Exception as e:
        raise TeleliteError(f"Could not load avatar: {e}")


async def _download_avatars(client, chat_ids):
    """Raw profile-photo bytes for several chats on one connection.
    Returns {chat_id: bytes|None}; None means "verified no photo". Chats
    that errored, or that were never reached because a flood_wait stopped
    the batch early, are absent from the dict."""
    result = {}
    for chat_id in chat_ids:
        try:
            entity = await _resolve_full_entity(client, chat_id)
            result[chat_id] = await client.download_profile_photo(
                entity, file=bytes, download_big=False
            )
        except ValueError:
            result[chat_id] = None
        except FloodWaitError:
            # Rate-limited right now; further requests on this connection
            # would keep hitting the same limit, so stop and return what
            # we already have. The first _resolve_full_entity cache-miss
            # repopulates the entity cache (get_dialogs), so the rest of
            # the batch costs only one photo call each.
            break
        except Exception:
            # One bad chat shouldn't sink the whole batch.
            continue
    return result


def download_avatars(session_string, chat_ids):
    """Batch version of download_avatar: ONE Telegram connection for the
    whole batch, instead of one full MTProto handshake per chat (a cold
    cache of ~30 avatars used to mean ~30 sequential handshakes)."""
    try:
        return _run(_with_client(session_string, lambda c: _download_avatars(c, chat_ids)))
    except TeleliteError:
        raise
    except Exception as e:
        raise TeleliteError(f"Could not load avatars: {e}")


def _has_photo(entity):
    # UserProfilePhotoEmpty/ChatPhotoEmpty (no photo set) carry no photo_id
    # field at all, unlike the real UserProfilePhoto/ChatPhoto variants --
    # checking for photo_id is a side-effect-free way to tell them apart
    # without an extra Telegram round-trip.
    photo = getattr(entity, "photo", None)
    return getattr(photo, "photo_id", None) is not None


def _dialog_summary(d):
    # Data usage matters here (this is the payload every feature-phone client
    # fetches to render the chat list): no client renders a last-message
    # preview or its timestamp today, so they're left out entirely rather
    # than shipped as dead weight over a slow connection.
    if getattr(d.entity, "is_self", False):
        # Telegram shows the chat with yourself as "Saved Messages" with a
        # bookmark icon, not under your own name and profile photo.
        return {
            "chat_id": d.id,
            "name": "Saved Messages",
            "unread_count": d.unread_count,
            "can_reply": True,
            "has_photo": False,
            "is_self": True,
        }
    return {
        "chat_id": d.id,
        "name": d.name or getattr(d.entity, "title", None) or str(d.id),
        "unread_count": d.unread_count,
        # Broadcast channels don't let regular members post; private chats,
        # basic groups, and supergroups (megagroups) do. Only real
        # (non-megagroup) Channel entities carry `.broadcast`, so this
        # defaults to True (repliable) for every other dialog type.
        # Creators/owners and admins with posting rights can post on broadcast channels.
        "can_reply": (
            not getattr(d.entity, "broadcast", False)
            or getattr(d.entity, "creator", False)
            or getattr(getattr(d.entity, "admin_rights", None), "post_messages", False)
        ),
        # Lets clients skip requesting an avatar for chats that don't
        # have one, instead of a guaranteed-404 round trip per chat.
        "has_photo": _has_photo(d.entity),
    }


async def _list_dialogs(client):
    dialogs = await client.get_dialogs(limit=50)
    return [_dialog_summary(d) for d in dialogs]


def list_dialogs(session_string):
    try:
        return _run(_with_client(session_string, _list_dialogs))
    except FloodWaitError as e:
        raise TeleliteError(
            "Rate limited by Telegram, please wait.", code="flood_wait", retry_after=e.seconds
        )
    except TeleliteError:
        raise
    except Exception as e:
        raise TeleliteError(f"Could not load chats: {e}")


# How many recent chats the browser chat list scans to fill folders.
# Telegram sends folder *rules*, not folder contents, so category folders
# ("Channels", "Unread") are filled from this window; chats added to a
# folder by hand are looked up directly even when they're older.
FOLDER_SCAN_LIMIT = 100
CHAT_LIST_LIMIT = 50
# Telegram folder ids start at 2, so 0 is free to mean "All chats".
ALL_CHATS_ID = 0


def _chat_record(d):
    entity = d.entity
    if isinstance(entity, types.User):
        if entity.bot:
            kind = "bot"
        elif entity.contact or entity.is_self:
            kind = "contact"
        else:
            kind = "non_contact"
    elif d.is_group:
        kind = "group"
    else:
        kind = "broadcast"
    mute_until = getattr(d.dialog.notify_settings, "mute_until", None)
    record = _dialog_summary(d)
    record.update(
        kind=kind,
        unread=bool(d.unread_count or d.dialog.unread_mark),
        muted=bool(mute_until and mute_until > datetime.now(timezone.utc)),
        archived=d.archived,
        date=d.date,
    )
    return record


def _peer_id(input_peer, self_id):
    if isinstance(input_peer, types.InputPeerSelf):
        return self_id
    try:
        return utils.get_peer_id(input_peer)
    except TypeError:
        return None


def _folder_spec(f, self_id):
    def ids(peers):
        return [pid for pid in (_peer_id(p, self_id) for p in peers) if pid is not None]

    is_chatlist = isinstance(f, types.DialogFilterChatlist)
    kinds = set()
    if not is_chatlist:
        for flag, kind in (
            ("contacts", "contact"),
            ("non_contacts", "non_contact"),
            ("bots", "bot"),
            ("groups", "group"),
            ("broadcasts", "broadcast"),
        ):
            if getattr(f, flag):
                kinds.add(kind)
    return {
        "id": f.id,
        "title": f.title,
        "pinned": ids(f.pinned_peers),
        "include": ids(f.include_peers),
        "exclude": [] if is_chatlist else ids(f.exclude_peers),
        "kinds": kinds,
        "exclude_muted": not is_chatlist and bool(f.exclude_muted),
        "exclude_read": not is_chatlist and bool(f.exclude_read),
        "exclude_archived": not is_chatlist and bool(f.exclude_archived),
        # peer id -> InputPeer, for looking up hand-picked chats directly
        "inputs": {
            _peer_id(p, self_id): p for p in list(f.pinned_peers) + list(f.include_peers)
        },
    }


async def _peer_dialogs(client, input_peers):
    """Dialogs for specific chats, for folder members outside the scanned
    window of recent chats."""
    found = []
    for i in range(0, len(input_peers), 100):
        res = await client(
            functions.messages.GetPeerDialogsRequest(
                peers=[types.InputDialogPeer(peer=p) for p in input_peers[i : i + 100]]
            )
        )
        entities = {utils.get_peer_id(e): e for e in list(res.users) + list(res.chats)}
        messages = {
            (utils.get_peer_id(m.peer_id), m.id): m
            for m in res.messages
            if getattr(m, "peer_id", None) is not None
        }
        for dialog in res.dialogs:
            if not isinstance(dialog, types.Dialog):
                continue
            peer_id = utils.get_peer_id(dialog.peer)
            if peer_id not in entities:
                continue
            message = messages.get((peer_id, dialog.top_message))
            found.append(Dialog(client, dialog, entities, message))
    return found


async def _load_chat_list(client):
    # Folders are an extra on top of the chat list: if Telegram rejects
    # either folder request, show the plain list rather than an error page.
    # (A dead session still surfaces, from get_dialogs below.)
    try:
        result = await client(functions.messages.GetDialogFiltersRequest())
        self_id = await client.get_peer_id("me")
        folders = [
            _folder_spec(f, self_id)
            for f in getattr(result, "filters", result)
            if isinstance(f, (types.DialogFilter, types.DialogFilterChatlist))
        ]
    except RPCError:
        folders = []

    dialogs = await client.get_dialogs(limit=FOLDER_SCAN_LIMIT)
    seen = {d.id for d in dialogs}
    missing = {}
    for folder in folders:
        for peer_id, input_peer in folder["inputs"].items():
            if peer_id is not None and peer_id not in seen:
                missing[peer_id] = input_peer
    try:
        extra = await _peer_dialogs(client, list(missing.values())) if missing else []
    except RPCError:
        extra = []  # folders just miss their older hand-picked chats this time

    scanned = [_chat_record(d) for d in dialogs]
    everything = scanned + [_chat_record(d) for d in extra if d.id not in seen]

    sections = [_section(ALL_CHATS_ID, "All chats", scanned)]
    for f in folders:
        sections.append(_section(f["id"], f["title"], folder_rules.chats_in_folder(f, everything)))
    return sections


def _section(section_id, title, chats):
    return {
        "id": section_id,
        "title": title,
        "unread": sum(1 for c in chats if c["unread"]),
        "total": len(chats),
        "chats": chats[:CHAT_LIST_LIMIT],
    }


def load_chat_list(session_string):
    """Chat list for the browser client, as sections: "All chats" (id
    ALL_CHATS_ID) followed by each of the user's Telegram folders in their
    Telegram order. Each has a title, unread-chat count, total chat count and
    up to CHAT_LIST_LIMIT chats."""
    try:
        return _run(_with_client(session_string, _load_chat_list))
    except FloodWaitError as e:
        raise TeleliteError(
            "Rate limited by Telegram, please wait.", code="flood_wait", retry_after=e.seconds
        )
    except TeleliteError:
        raise
    except Exception as e:
        raise TeleliteError(f"Could not load chats: {e}")


async def _get_messages(client, chat_id, before_id, limit):
    entity = await _resolve_entity(client, chat_id)
    kwargs = {"limit": limit}
    if before_id:
        kwargs["max_id"] = before_id
    messages = list(await client.get_messages(entity, **kwargs))
    messages.reverse()  # oldest -> newest, per v1 conversation-view spec
    # sender_id and date aren't rendered by any client (v1 conversation view
    # only shows out/text) -- left out of the payload rather than shipped
    # as dead weight over a slow connection.
    return [
        {
            "id": m.id,
            "out": bool(m.out),
            "text": m.message or "[non-text message]",
        }
        for m in messages
    ]


def get_messages(session_string, chat_id, before_id=None, limit=20):
    try:
        return _run(
            _with_client(session_string, lambda c: _get_messages(c, chat_id, before_id, limit))
        )
    except FloodWaitError as e:
        raise TeleliteError(
            "Rate limited by Telegram, please wait.", code="flood_wait", retry_after=e.seconds
        )
    except TeleliteError:
        raise
    except Exception as e:
        raise TeleliteError(f"Could not load messages: {e}")


async def _send_message(client, chat_id, text):
    entity = await _resolve_entity(client, chat_id)
    m = await client.send_message(entity, text)
    return {"id": m.id, "date": m.date.isoformat() if m.date else None}


def send_message(session_string, chat_id, text):
    try:
        return _run(_with_client(session_string, lambda c: _send_message(c, chat_id, text)))
    except FloodWaitError as e:
        raise TeleliteError(
            "Rate limited by Telegram, please wait.", code="flood_wait", retry_after=e.seconds
        )
    except TeleliteError:
        raise
    except Exception as e:
        raise TeleliteError(f"Could not send message: {e}")


async def _log_out(client):
    await client.log_out()


def log_out(session_string):
    """Best-effort revoke on Telegram's side. Callers must delete the local
    session row regardless of whether this succeeds — that's what actually
    protects a user on a borrowed device."""
    try:
        _run(_with_client(session_string, _log_out))
    except Exception:
        pass
