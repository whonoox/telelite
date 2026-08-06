import asyncio

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from . import config


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


def _has_photo(entity):
    # UserProfilePhotoEmpty/ChatPhotoEmpty (no photo set) carry no photo_id
    # field at all, unlike the real UserProfilePhoto/ChatPhoto variants --
    # checking for photo_id is a side-effect-free way to tell them apart
    # without an extra Telegram round-trip.
    photo = getattr(entity, "photo", None)
    return getattr(photo, "photo_id", None) is not None


async def _list_dialogs(client):
    dialogs = await client.get_dialogs(limit=50)
    # Data usage matters here (this is the payload every feature-phone client
    # fetches to render the chat list): no client renders a last-message
    # preview or its timestamp today, so they're left out entirely rather
    # than shipped as dead weight over a slow connection.
    return [
        {
            "chat_id": d.id,
            "name": d.name or getattr(d.entity, "title", None) or str(d.id),
            "unread_count": d.unread_count,
            # Broadcast channels don't let regular members post; private chats,
            # basic groups, and supergroups (megagroups) do. Only real
            # (non-megagroup) Channel entities carry `.broadcast`, so this
            # defaults to True (repliable) for every other dialog type.
            "can_reply": not getattr(d.entity, "broadcast", False),
            # Lets clients skip requesting an avatar for chats that don't
            # have one, instead of a guaranteed-404 round trip per chat.
            "has_photo": _has_photo(d.entity),
        }
        for d in dialogs
    ]


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
