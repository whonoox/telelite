from flask import Flask, redirect, request, url_for

from . import config, db
from .api import bp as api_bp
from .web import bp as web_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = config.FLASK_SECRET_KEY
    db.init_db()
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    @app.route("/")
    def index():
        token = request.cookies.get(config.COOKIE_NAME)
        if token and db.get_session(token):
            return redirect(url_for("web.chats"))
        return redirect(url_for("web.login_phone"))

    return app
