from flask import Flask, redirect, request, url_for
from flask_cors import CORS

from . import config, db
from .api import bp as api_bp
from .web import bp as web_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = config.FLASK_SECRET_KEY
    db.init_db()
    # Bearer-token JSON API needs to be reachable cross-origin from the
    # packaged KaiOS app (app://...). No cookies are involved here, so a
    # wildcard origin carries no CSRF/credential risk, unlike web_bp below
    # which stays same-origin only.
    CORS(
        api_bp,
        resources={r"/*": {"origins": "*"}},
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "OPTIONS"],
    )
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    @app.route("/")
    def index():
        token = request.cookies.get(config.COOKIE_NAME)
        if token and db.get_session(token):
            return redirect(url_for("web.chats"))
        return redirect(url_for("web.login_phone"))

    return app
