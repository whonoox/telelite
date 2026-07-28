from flask import Flask, redirect, request, url_for
from flask_cors import CORS

from . import config, db
from .api import bp as api_bp
from .downloads import bp as downloads_bp
from .web import bp as web_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = config.FLASK_SECRET_KEY
    db.init_db()
    # Bearer-token JSON API needs to be reachable cross-origin from the
    # packaged KaiOS app (app://...). No cookies are involved here, so a
    # wildcard origin carries no CSRF/credential risk, unlike /web/* below
    # which stays same-origin only. Applied to `app` (a fresh instance per
    # create_app() call) rather than the api_bp blueprint object itself:
    # blueprints are module-level singletons, and Flask locks out further
    # setup calls (like the after_request hook CORS() installs) on a
    # blueprint once it's been registered on any app -- which breaks the
    # second create_app() call in the same process (e.g. under pytest).
    CORS(
        app,
        resources={r"/(?!web/).*": {"origins": "*"}},
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "OPTIONS"],
    )
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)
    app.register_blueprint(downloads_bp)

    @app.route("/")
    def index():
        token = request.cookies.get(config.COOKIE_NAME)
        if token and db.get_session(token):
            return redirect(url_for("web.chats"))
        return redirect(url_for("web.login_phone"))

    return app
