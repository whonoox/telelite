import os

from dotenv import load_dotenv

load_dotenv()


def _require(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


TELEGRAM_API_ID = int(_require("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = _require("TELEGRAM_API_HASH")
MASTER_KEY = _require("MASTER_KEY").encode()
FLASK_SECRET_KEY = _require("FLASK_SECRET_KEY")
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "24"))
DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/telelite.db")
# When set, sessions live in a hosted Turso (libSQL) database instead of the
# local SQLite file above. Needed on hosts with no persistent disk (e.g.
# Vercel), where a local file would vanish whenever an instance scales down.
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
# Comma-separated Telegram user IDs allowed to log in. Empty means any
# Telegram account can use this server -- set it on a public deployment
# meant for yourself, so strangers can't sign in and share its caches.
TELEGRAM_ALLOWED_USER_IDS = frozenset(
    int(x) for x in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if x.strip()
)
PENDING_LOGIN_TTL_MINUTES = int(os.environ.get("PENDING_LOGIN_TTL_MINUTES", "10"))
COOKIE_NAME = "telelite_token"

# Where built client downloads (J2ME .jar/.jad, etc.) are served from. See
# SELF_HOSTING.md for how to build and drop them here.
DOWNLOADS_PATH = os.environ.get("DOWNLOADS_PATH", "data/downloads")

# Resized profile-photo thumbnails are cached to disk here so a chat list
# full of avatars doesn't mean a fresh Telegram round-trip per avatar on
# every page load. TTL trades a bit of staleness (a changed photo can take
# up to this long to show up) for far fewer Telegram requests.
AVATAR_CACHE_PATH = os.environ.get("AVATAR_CACHE_PATH", "data/avatar_cache")
AVATAR_CACHE_TTL_HOURS = int(os.environ.get("AVATAR_CACHE_TTL_HOURS", "24"))
