import secrets
import struct
from functools import wraps

from flask import Blueprint, Response, g, jsonify, request

from . import config, crypto, db
from .avatars import get_avatar_thumbnail, get_avatar_thumbnails
from .telegram_client import (
    TeleliteError,
    get_messages,
    list_dialogs,
    log_out,
    send_code,
    send_message,
    verify_code,
)
from .utils import parse_chat_id

bp = Blueprint("api", __name__)

COOKIE_NAME = config.COOKIE_NAME

# Matches the dialog cap in telegram_client._list_dialogs -- a batch can
# never need to cover more chats than a single /chats response can return.
MAX_BATCH_AVATAR_IDS = 50


def _get_token():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):]
    return request.cookies.get(COOKIE_NAME)


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _get_token()
        if not token:
            return jsonify(error="not_authenticated"), 401
        session_row = db.get_session(token)
        if session_row is None:
            return jsonify(error="session_expired"), 401
        g.token = token
        g.telegram_user_id = session_row["telegram_user_id"]
        g.session_string = crypto.decrypt(session_row["encrypted_session"])
        return fn(*args, **kwargs)

    return wrapper


def _error_response(e: TeleliteError):
    status = 429 if e.code == "flood_wait" else 400
    return jsonify(error=e.code, message=str(e), retry_after=e.retry_after), status


@bp.before_app_request
def _purge():
    # Cheap enough at this scale to run on every request; keeps the DB tidy
    # without needing a separate scheduled job.
    db.purge_expired()


@bp.route("/login/request", methods=["POST"])
def login_request():
    data = request.get_json(silent=True) or {}
    phone_number = data.get("phone_number")
    if not phone_number:
        return jsonify(error="invalid_request", message="phone_number is required"), 400
    try:
        session_string, phone_code_hash = send_code(phone_number)
    except TeleliteError as e:
        return _error_response(e)
    pending_id = secrets.token_urlsafe(16)
    db.create_pending_login(
        pending_id, phone_number, phone_code_hash, crypto.encrypt(session_string)
    )
    return jsonify(pending_id=pending_id)


@bp.route("/login/verify", methods=["POST"])
def login_verify():
    data = request.get_json(silent=True) or {}
    pending_id = data.get("pending_id")
    code = data.get("code")
    password = data.get("password")
    if not pending_id or not code:
        return jsonify(error="invalid_request", message="pending_id and code are required"), 400

    pending = db.get_pending_login(pending_id)
    if pending is None:
        return jsonify(
            error="login_expired", message="Login request expired, please start over."
        ), 400

    session_string = crypto.decrypt(pending["encrypted_session"])
    try:
        new_session_string, telegram_user_id = verify_code(
            session_string, pending["phone_number"], pending["phone_code_hash"], code, password
        )
    except TeleliteError as e:
        return _error_response(e)

    db.delete_pending_login(pending_id)
    token = secrets.token_urlsafe(32)
    db.create_session(
        token, telegram_user_id, pending["phone_number"], crypto.encrypt(new_session_string)
    )
    resp = jsonify(token=token)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="Lax")
    return resp


@bp.route("/chats", methods=["GET"])
@require_auth
def chats():
    try:
        dialogs = list_dialogs(g.session_string)
    except TeleliteError as e:
        return _error_response(e)
    return jsonify(chats=dialogs)


@bp.route("/chats/<chat_id>/avatar", methods=["GET"])
@require_auth
def get_chat_avatar(chat_id):
    parsed_chat_id = parse_chat_id(chat_id)
    if parsed_chat_id is None:
        return jsonify(error="invalid_request", message="chat_id must be an integer"), 400
    fmt = "png" if request.args.get("fmt") == "png" else "jpeg"
    try:
        thumbnail = get_avatar_thumbnail(
            g.session_string, g.telegram_user_id, parsed_chat_id, fmt=fmt
        )
    except TeleliteError as e:
        return _error_response(e)
    if thumbnail is None:
        return jsonify(error="not_found", message="No profile photo for this chat."), 404
    resp = Response(thumbnail, mimetype=f"image/{fmt}")
    resp.headers["Cache-Control"] = f"private, max-age={config.AVATAR_CACHE_TTL_HOURS * 3600}"
    return resp


@bp.route("/chats/avatars", methods=["GET"])
@require_auth
def get_chat_avatars_batch():
    """One-request batch avatar fetch for clients where a per-chat round
    trip is too costly (J2ME over GPRS -- up to 50 chats would mean up to
    50 separate requests just to open the chat list). Response is a
    minimal binary framing, not JSON, since it's a batch of images: for
    each requested id in order, a flag byte (0 = no photo) optionally
    followed by a 4-byte big-endian length and that many image bytes."""
    fmt = "png" if request.args.get("fmt") == "png" else "jpeg"
    ids_param = request.args.get("ids", "")
    chat_ids = []
    for raw in ids_param.split(","):
        raw = raw.strip()
        if not raw:
            continue
        parsed = parse_chat_id(raw)
        if parsed is None:
            return jsonify(error="invalid_request", message="ids must be a comma-separated list of integers"), 400
        chat_ids.append(parsed)
    if not chat_ids:
        return jsonify(error="invalid_request", message="ids is required"), 400
    if len(chat_ids) > MAX_BATCH_AVATAR_IDS:
        return jsonify(
            error="invalid_request",
            message=f"too many ids (max {MAX_BATCH_AVATAR_IDS})",
        ), 400

    try:
        thumbnails = get_avatar_thumbnails(
            g.session_string, g.telegram_user_id, chat_ids, fmt=fmt
        )
    except TeleliteError:
        # A total batch failure shouldn't break the chat list -- no icon
        # for anyone this round (same graceful-degradation spirit as the
        # single-avatar path).
        thumbnails = {}
    chunks = []
    for chat_id in chat_ids:
        thumbnail = thumbnails.get(chat_id)
        if thumbnail is None:
            chunks.append(b"\x00")
        else:
            chunks.append(b"\x01" + struct.pack(">I", len(thumbnail)) + thumbnail)

    resp = Response(b"".join(chunks), mimetype="application/octet-stream")
    resp.headers["Cache-Control"] = f"private, max-age={config.AVATAR_CACHE_TTL_HOURS * 3600}"
    return resp


@bp.route("/chats/<chat_id>/messages", methods=["GET"])
@require_auth
def get_chat_messages(chat_id):
    parsed_chat_id = parse_chat_id(chat_id)
    if parsed_chat_id is None:
        return jsonify(error="invalid_request", message="chat_id must be an integer"), 400
    before_id = request.args.get("before_id", type=int)
    limit = max(1, min(request.args.get("limit", default=20, type=int), 50))
    try:
        msgs = get_messages(g.session_string, parsed_chat_id, before_id=before_id, limit=limit)
    except TeleliteError as e:
        return _error_response(e)
    return jsonify(messages=msgs)


@bp.route("/chats/<chat_id>/messages", methods=["POST"])
@require_auth
def post_chat_message(chat_id):
    parsed_chat_id = parse_chat_id(chat_id)
    if parsed_chat_id is None:
        return jsonify(error="invalid_request", message="chat_id must be an integer"), 400
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(error="invalid_request", message="text is required"), 400
    try:
        sent = send_message(g.session_string, parsed_chat_id, text)
    except TeleliteError as e:
        return _error_response(e)
    return jsonify(message=sent)


@bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    log_out(g.session_string)
    db.delete_session(g.token)
    resp = jsonify(ok=True)
    resp.delete_cookie(COOKIE_NAME)
    return resp
