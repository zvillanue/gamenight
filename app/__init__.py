import os
from zoneinfo import ZoneInfo

import click
from flask import Flask, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    # WAL lets readers and the single writer coexist; the busy timeout stops
    # two simultaneous votes from failing with "database is locked".
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


CSP = (
    "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def create_app(config_class=Config, **overrides):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.config.update(overrides)

    if not app.config["SECRET_KEY"] or app.config["SECRET_KEY"].startswith("change-me"):
        if app.config["DEBUG"] or app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "dev-only-insecure-key"
        else:
            raise RuntimeError("SECRET_KEY must be set to a long random value (see .env.example).")

    # Caddy (or any reverse proxy) is the only thing that reaches us, so trust
    # exactly one hop of X-Forwarded-* for the real client IP and https scheme.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.config["TZ"] = ZoneInfo(app.config["APP_TIMEZONE"])

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app import models
    from app.admin import admin_bp
    from app.auth import auth_bp
    from app.views import views_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(admin_bp)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            uid, token = user_id.split(".", 1)
            user = db.session.get(models.User, int(uid))
        except (ValueError, AttributeError):
            return None
        if user and user.session_token == token:
            return user
        return None

    from app.util import local_dt, utc_iso

    app.jinja_env.filters["local_dt"] = local_dt
    app.jinja_env.filters["utc_iso"] = utc_iso

    @app.after_request
    def security_headers(response):
        h = response.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "same-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.is_secure:
            h["Strict-Transport-Security"] = "max-age=31536000"
        if response.mimetype == "text/html":
            h["Cache-Control"] = "no-store"
        return response

    def error_page(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(_e):
        return error_page(400, "Request failed", "Your session may have expired. Go back, reload the page and try again.")

    @app.errorhandler(403)
    def forbidden(_e):
        return error_page(403, "Not allowed", "You don't have permission to do that.")

    @app.errorhandler(404)
    def not_found(_e):
        return error_page(404, "Not found", "That page doesn't exist.")

    @app.errorhandler(413)
    def too_large(_e):
        return error_page(413, "File too large", "Images can be at most 6 MB.")

    @app.errorhandler(429)
    def rate_limited(_e):
        return error_page(429, "Slow down", "Too many attempts. Wait a few minutes and try again.")

    @app.errorhandler(500)
    def server_error(_e):
        db.session.rollback()
        return error_page(500, "Something broke", "That wasn't your fault. Try again in a moment.")

    @app.cli.command("set-password")
    @click.argument("username")
    def set_password(username):
        """Reset a member's password from the server (admin lockout recovery)."""
        user = models.User.query.filter_by(username=username.lower()).first()
        if not user:
            raise click.ClickException("No such user.")
        pw = click.prompt("New password", hide_input=True, confirmation_prompt=True)
        from app.util import password_problem

        problem = password_problem(pw, user.username)
        if problem:
            raise click.ClickException(problem)
        user.set_password(pw)
        db.session.commit()
        click.echo("Password updated; the user's other sessions were signed out.")

    with app.app_context():
        db.create_all()

    return app
