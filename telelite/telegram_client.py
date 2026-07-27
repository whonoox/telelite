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
        StringSession(session_string), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH
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


async def _list_dialogs(client):
    dialogs = await client.get_dialogs(limit=50)
    return [
        {
            "chat_id": d.id,
            "name": d.name or getattr(d.entity, "title", None) or str(d.id),
            "unread_count": d.unread_count,
            "last_message": d.message.text if d.message else None,
            "last_message_date": d.date.isoformat() if d.date else None,
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
    return [
        {
            "id": m.id,
            "out": bool(m.out),
            "sender_id": m.sender_id,
            "text": m.message or "",
            "date": m.date.isoformat() if m.date else None,
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
