import io
import re

import pytest
from PIL import Image

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    app = create_app(TESTING=True, SECRET_KEY="test", WTF_CSRF_ENABLED=False,
                     SESSION_COOKIE_SECURE=False,
                     SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/t.db",
                     UPLOAD_FOLDER=str(tmp_path / "up"), INVITE_CODE="",
                     RATELIMIT_ENABLED=False)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username, name=None, group_id="", password="correct-horse-1"):
    return client.post("/register", data={
        "name": name or username.title(), "username": username, "password": password,
        "password2": password, "group_id": group_id}, follow_redirects=True)


def png_bytes(size=(20, 20)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return buf.getvalue()
