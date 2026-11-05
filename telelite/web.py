import hashlib
import hmac
import secrets
from functools import wraps

from flask import Blueprint, Response, abort, g, make_response, redirect, render_template, request, url_for

from . import config, crypto, db
from .avatars import (
    get_avatar_thumbnail,
    PLACEHOLDER_COLORS,
    placeholder_color,
    placeholder_letter,
    placeholder_png,
    saved_messages_png,
)
from .telegram_client import (
    TeleliteError,
    get_messages,
    load_chat_list,
    log_out,
    send_code,
    send_message,
    verify_code,
)
from .utils import cookie_is_secure, parse_chat_id

bp = Blueprint("web", __name__, url_prefix="/web")

MESSAGES_PER_PAGE = 20
# Chats per section on the all-folders overview. Every row has an avatar
# image that Opera's servers fetch up front, so the page stays light; the
# rest are one "More" link away.
OVERVIEW_SECTION_LIMIT = 15


def _csrf_token(session_token):
    return hmac.new(
        config.FLASK_SECRET_KEY.encode(), session_token.encode(), hashlib.sha256
    ).hexdigest()


def _check_csrf(session_token, submitted):
    return bool(submitted) and hmac.compare_digest(_csrf_token(session_token), submitted)


def _error_message(e):
    """Human message for a TeleliteError, with retry_after appended when present."""
    message = str(e)
    if e.retry_after:
        message = f"{message} (retry in {e.retry_after}s)"
    return message


def _can_reply():
    value = request.values.get("can_reply")
    return True if value is None else value == "1"


def _set_session_cookie(resp, token):
    # Feature-phone browsers routinely close/restart between visits; without
    # an explicit lifetime this is a "session cookie" that dies with them,
    # forcing a re-login even though the server-side session (see
    # db.get_session, which slides expires_at forward on every request) is
    # still perfectly valid. Re-set on every authenticated request so the
    # cookie's lifetime slides in lockstep with the server-side session.
    resp.set_cookie(
        config.COOKIE_NAME,
        token,
        max_age=config.SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="Lax",
        secure=cookie_is_secure(),
    )
    return resp


def require_web_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.cookies.get(config.COOKIE_NAME)
        session_row = db.get_session(token) if token else None
        if session_row is None:
            return redirect(url_for("web.login_phone", expired="1" if token else None))
        g.token = token
        g.telegram_user_id = session_row["telegram_user_id"]
        g.session_string = crypto.decrypt(session_row["encrypted_session"])
        g.csrf_token = _csrf_token(token)
        resp = make_response(fn(*args, **kwargs))
        return _set_session_cookie(resp, token)

    return wrapper


@bp.route("/login", methods=["GET"])
def login_phone():
    error = "Session expired, please log in again." if request.args.get("expired") else None
    return render_template("login_phone.html", error=error, phone_number="")


@bp.route("/login", methods=["POST"])
def login_submit():
    phone_number = (request.form.get("phone_number") or "").strip()
    if not phone_number:
        return render_template(
            "login_phone.html", error="Phone number is required.", phone_number=""
        )
    try:
        session_string, phone_code_hash = send_code(phone_number)
    except TeleliteError as e:
        return render_template("login_phone.html", error=_error_message(e), phone_number=phone_number)

    pending_id = secrets.token_urlsafe(16)
    db.create_pending_login(
        pending_id, phone_number, phone_code_hash, crypto.encrypt(session_string)
    )
    return render_template(
        "login_code.html", pending_id=pending_id, error=None, needs_password=False
    )


@bp.route("/login/verify", methods=["POST"])
def login_verify():
    pending_id = request.form.get("pending_id")
    code = (request.form.get("code") or "").strip()
    password = request.form.get("password")

    pending = db.get_pending_login(pending_id) if pending_id else None
    if pending is None:
        return render_template(
            "login_phone.html", error="Login expired, please start over.", phone_number=""
        )
    if not code:
        return render_template(
            "login_code.html",
            pending_id=pending_id,
            error="Code is required.",
            needs_password=password is not None,
        )

    session_string = crypto.decrypt(pending["encrypted_session"])
    try:
        new_session_string, telegram_user_id = verify_code(
            session_string, pending["phone_number"], pending["phone_code_hash"], code, password
        )
    except TeleliteError as e:
        return render_template(
            "login_code.html",
            pending_id=pending_id,
            error=_error_message(e),
            needs_password=(e.code == "needs_password"),
        )

    db.delete_pending_login(pending_id)
    token = secrets.token_urlsafe(32)
    db.create_session(
        token, telegram_user_id, pending["phone_number"], crypto.encrypt(new_session_string)
    )
    resp = redirect(url_for("web.chats"))
    return _set_session_cookie(resp, token)


@bp.route("/chats", methods=["GET"])
@require_web_auth
def chats():
    """Without ?folder: one page with "All chats" and every Telegram folder
    as a titled section of its first few chats. Opera Mini folds each run of
    links into a collapsible group, so sections open in place without a page
    load. With ?folder=<id>: that section's full list."""
    try:
        sections = load_chat_list(g.session_string)
        error = None
    except TeleliteError as e:
        sections = []
        error = _error_message(e)
    for section in sections:
        section["chats"] = [
            dict(c, placeholder=None if c["has_photo"] else _placeholder_url(c))
            for c in section["chats"]
        ]
    folder_id = _folder_id()
    current = next((s for s in sections if s["id"] == folder_id), None)
    return render_template(
        "chats.html",
        sections=sections,
        current=current,
        section_limit=OVERVIEW_SECTION_LIMIT,
        error=error,
        csrf_token=g.csrf_token,
    )


@bp.route("/chats/<chat_id>/avatar", methods=["GET"])
@require_web_auth
def avatar(chat_id):
    parsed_chat_id = parse_chat_id(chat_id)
    if parsed_chat_id is None:
        abort(404)
    try:
        thumbnail = get_avatar_thumbnail(
            g.session_string, g.telegram_user_id, parsed_chat_id, fmt="jpeg"
        )
    except TeleliteError:
        # Avatars are decorative -- a flaky/rate-limited fetch shouldn't
        # break the page, just fall back to no image for this chat.
        thumbnail = None
    if thumbnail is None:
        abort(404)
    resp = Response(thumbnail, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = f"private, max-age={config.AVATAR_CACHE_TTL_HOURS * 3600}"
    return resp


# Placeholder icons hold no user data (a color and a letter), so they need no
# login and can be cached by browsers and Opera's servers for a long time.
_PLACEHOLDER_CACHE = "public, max-age=31536000"


def _placeholder_url(chat):
    if chat.get("is_self"):
        return url_for("web.saved_messages_icon")
    letter = placeholder_letter(chat["name"]) or "_"
    return url_for(
        "web.avatar_placeholder", color=placeholder_color(chat["chat_id"]), letter=letter
    )


@bp.route("/icons/saved.png", methods=["GET"])
def saved_messages_icon():
    resp = Response(saved_messages_png(), mimetype="image/png")
    resp.headers["Cache-Control"] = _PLACEHOLDER_CACHE
    return resp


@bp.route("/icons/<int:color>/<letter>.png", methods=["GET"])
def avatar_placeholder(color, letter):
    if letter == "_":
        letter = ""
    valid_letter = letter == "" or (len(letter) == 1 and letter.isascii() and letter.isalnum())
    if color >= len(PLACEHOLDER_COLORS) or not valid_letter:
        abort(404)
    resp = Response(placeholder_png(color, letter.upper()), mimetype="image/png")
    resp.headers["Cache-Control"] = _PLACEHOLDER_CACHE
    return resp


def _chat_name(chat_id):
    return request.values.get("name") or f"Chat {chat_id}"


def _folder_id():
    """The chat-list folder the user came from, so "Back" returns to it."""
    return request.values.get("folder", type=int)


@bp.route("/chats/<chat_id>", methods=["GET"])
@require_web_auth
def conversation(chat_id):
    parsed_chat_id = parse_chat_id(chat_id)
    if parsed_chat_id is None:
        return redirect(url_for("web.chats"))

    before_id = request.args.get("before_id", type=int)
    try:
        msgs = get_messages(
            g.session_string, parsed_chat_id, before_id=before_id, limit=MESSAGES_PER_PAGE
        )
        error = None
    except TeleliteError as e:
        msgs = []
        error = _error_message(e)

    return render_template(
        "conversation.html",
        chat_id=parsed_chat_id,
        chat_name=_chat_name(parsed_chat_id),
        can_reply=_can_reply(),
        messages=msgs,
        error=error,
        has_more=len(msgs) == MESSAGES_PER_PAGE,
        oldest_id=msgs[0]["id"] if msgs else None,
        draft_text="",
        folder_id=_folder_id(),
        csrf_token=g.csrf_token,
    )


@bp.route("/chats/<chat_id>/reply", methods=["POST"])
@require_web_auth
def reply(chat_id):
    parsed_chat_id = parse_chat_id(chat_id)
    if parsed_chat_id is None:
        return redirect(url_for("web.chats"))

    chat_name = _chat_name(parsed_chat_id)
    can_reply = _can_reply()
    text = (request.form.get("text") or "").strip()

    def render_with_error(error_message):
        try:
            msgs = get_messages(g.session_string, parsed_chat_id, limit=MESSAGES_PER_PAGE)
        except TeleliteError:
            msgs = []
        return render_template(
            "conversation.html",
            chat_id=parsed_chat_id,
            chat_name=chat_name,
            can_reply=can_reply,
            messages=msgs,
            error=error_message,
            has_more=len(msgs) == MESSAGES_PER_PAGE,
            oldest_id=msgs[0]["id"] if msgs else None,
            draft_text=text,
            folder_id=_folder_id(),
            csrf_token=g.csrf_token,
        )

    if not _check_csrf(g.token, request.form.get("csrf_token")):
        return render_with_error("Security check failed, please try again.")
    if not can_reply:
        return render_with_error("This channel doesn't allow replies.")
    if not text:
        return render_with_error("Message text is required.")
    try:
        send_message(g.session_string, parsed_chat_id, text)
    except TeleliteError as e:
        return render_with_error(_error_message(e))

    return redirect(
        url_for(
            "web.conversation",
            chat_id=parsed_chat_id,
            name=chat_name,
            can_reply="1" if can_reply else "0",
            folder=_folder_id(),
        ),
        code=303,
    )


@bp.route("/logout", methods=["POST"])
@require_web_auth
def logout():
    if _check_csrf(g.token, request.form.get("csrf_token")):
        log_out(g.session_string)
        db.delete_session(g.token)
    resp = redirect(url_for("web.login_phone"))
    resp.delete_cookie(config.COOKIE_NAME, secure=cookie_is_secure())
    return resp
