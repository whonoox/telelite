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
PENDING_LOGIN_TTL_MINUTES = int(os.environ.get("PENDING_LOGIN_TTL_MINUTES", "10"))
COOKIE_NAME = "telelite_token"

# Where built client downloads (J2ME .jar/.jad, etc.) are served from. See
# SELF_HOSTING.md for how to build and drop them here.
DOWNLOADS_PATH = os.environ.get("DOWNLOADS_PATH", "data/downloads")
