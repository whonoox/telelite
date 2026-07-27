from flask import Flask

from . import config, db
from .api import bp as api_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = config.FLASK_SECRET_KEY
    db.init_db()
    app.register_blueprint(api_bp)
    return app
