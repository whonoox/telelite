import pytest

from telelite import config, crypto, db
from telelite.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "test.db"))
    application = create_app()
    application.testing = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def session_token(app):
    """Creates a real session row and returns (token, session_string)."""
    token = "test-token-abc123"
    session_string = "fake-telethon-session-string"
    db.create_session(token, 999999, "+10000000000", crypto.encrypt(session_string))
    return token, session_string


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}
