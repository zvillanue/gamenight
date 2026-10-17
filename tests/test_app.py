import io
from datetime import timedelta

from app import db
from app.models import Game, GameNight, Group, Rsvp, User, utcnow
from app.util import capacity_status, safe_next
from tests.conftest import png_bytes, register


def make_night(app, days=3):
    with app.app_context():
        n = GameNight(starts_at=utcnow() + timedelta(days=days))
        db.session.add(n)
        db.session.commit()
        return n.id


def test_first_user_is_admin_second_is_not(app, client):
    register(client, "zack")
    other = app.test_client()
    register(other, "friend")
    with app.app_context():
        assert User.query.filter_by(username="zack").one().is_admin
        assert not User.query.filter_by(username="friend").one().is_admin
    assert other.get("/admin/").status_code == 403
    assert client.get("/admin/").status_code == 200


def test_login_required_and_redirect(client):
    r = client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_password_stored_hashed_and_rules(app, client):
    register(client, "zack", password="short")
    with app.app_context():
        assert User.query.count() == 0
    register(client, "zack", password="correct-horse-1")
    with app.app_context():
        u = User.query.one()
        assert "correct-horse-1" not in u.password_hash and u.check_password("correct-horse-1")


def test_login_wrong_password_generic(client):
    register(client, "zack")
    client.post("/logout")
    r = client.post("/login", data={"username": "zack", "password": "nope"})
    assert b"Wrong username or password" in r.data
    r = client.post("/login", data={"username": "ghost", "password": "nope"})
    assert b"Wrong username or password" in r.data


def test_invite_code_enforced(app):
    app.config["INVITE_CODE"] = "letmein"
    c = app.test_client()
    register(c, "zack")
    with app.app_context():
        assert User.query.count() == 0
    c.post("/register", data={"name": "Z", "username": "zack", "password": "correct-horse-1",
                              "password2": "correct-horse-1", "invite": "letmein"})
    with app.app_context():
        assert User.query.count() == 1


def test_capacity_colors():
    assert capacity_status(4, 4) == "ok"
    assert capacity_status(6, 4) == "warn"
    assert capacity_status(12, 4) == "bad"
    assert capacity_status(7, 4) == "bad"


def test_safe_next(app):
    with app.test_request_context("/?next=//evil.com"):
        assert safe_next("/x") == "/x"
    with app.test_request_context("/?next=https://evil.com"):
        assert safe_next("/x") == "/x"
    with app.test_request_context("/?next=/games?q=a"):
        assert safe_next("/x") == "/games?q=a"


def test_rsvp_groups_and_colors(app, client):
    register(client, "zack")
    with app.app_context():
        work = Group(name="Work")
        db.session.add(work)
        db.session.commit()
        gid = work.id
    night = make_night(app)
    for i in range(6):
        c = app.test_client()
        register(c, f"player{i}", name=f"Player{i}", group_id=str(gid))
        c.post("/rsvp", data={"going": "yes"})
    client.post("/games/add", data={"name": "Small Game", "min_players": 1, "max_players": 4})
    client.post("/games/add", data={"name": "Big Game", "min_players": 2, "max_players": 12})
    page = client.get("/").get_data(as_text=True)
    assert "6</strong> Work" in page and "Player3" in page
    assert 'game warn' in page and 'game ok' in page
    with app.app_context():
        assert Rsvp.query.filter_by(night_id=night, going=True).count() == 6


def test_vote_toggle_and_ranking(app, client):
    register(client, "zack")
    make_night(app)
    client.post("/games/add", data={"name": "Alpha", "min_players": 1, "max_players": 4})
    client.post("/games/add", data={"name": "Beta", "min_players": 1, "max_players": 4})
    other = app.test_client()
    register(other, "friend")
    with app.app_context():
        beta = Game.query.filter_by(name="Beta").one().id
    other.post(f"/games/{beta}/vote")
    other.post(f"/games/{beta}/vote")  # toggle off
    other.post(f"/games/{beta}/vote")  # toggle on
    html = other.get("/games").get_data(as_text=True)
    assert html.index("Beta") < html.index("Alpha") or html.count("2 votes") == 2


def test_add_game_records_suggester_and_ownership(app, client):
    register(client, "zack", name="Zack")
    client.post("/games/add", data={"name": "Catan", "min_players": 3, "max_players": 4, "has_it": "on"})
    html = client.get("/games").get_data(as_text=True)
    assert "Suggested by Zack" in html and "Owned by Zack" in html


def test_bad_player_range_rejected(app, client):
    register(client, "zack")
    client.post("/games/add", data={"name": "Bad", "min_players": 5, "max_players": 2})
    with app.app_context():
        assert Game.query.count() == 0


def test_only_owner_or_admin_edits_game(app, client):
    register(client, "zack")
    friend = app.test_client()
    register(friend, "friend")
    friend.post("/games/add", data={"name": "Mine", "min_players": 1, "max_players": 2})
    third = app.test_client()
    register(third, "third")
    with app.app_context():
        gid = Game.query.one().id
    assert third.post(f"/games/{gid}/delete").status_code == 403
    assert friend.get(f"/games/{gid}/edit").status_code == 200
    assert client.post(f"/games/{gid}/delete").status_code == 302  # admin


def test_image_upload_reencoded_and_junk_rejected(app, client):
    register(client, "zack")
    r = client.post("/games/add", data={"name": "Pic", "min_players": 1, "max_players": 2,
                                        "image": (io.BytesIO(png_bytes()), "x.png")},
                    content_type="multipart/form-data")
    with app.app_context():
        g = Game.query.one()
        assert g.image and g.image.endswith(".jpg") and len(g.image) == 36
        name = g.image
    assert client.get(f"/img/{name}").mimetype == "image/jpeg"
    client.post("/games/add", data={"name": "Evil", "min_players": 1, "max_players": 2,
                                    "image": (io.BytesIO(b"<script>alert(1)</script>"), "x.png")},
                content_type="multipart/form-data")
    with app.app_context():
        assert Game.query.count() == 1
    assert client.get("/img/../config.py").status_code == 404


def test_xss_escaped(app, client):
    register(client, "zack")
    client.post("/games/add", data={"name": "<script>x</script>", "min_players": 1, "max_players": 2})
    assert b"<script>x</script>" not in client.get("/games").data


def test_password_change_signs_out_other_sessions(app):
    a, b = app.test_client(), app.test_client()
    register(a, "zack")
    b.post("/login", data={"username": "zack", "password": "correct-horse-1"})
    assert b.get("/").status_code == 200
    a.post("/account", data={"action": "password", "current": "correct-horse-1",
                             "password": "another-long-pass", "password2": "another-long-pass"})
    assert b.get("/").status_code == 302
    assert a.get("/").status_code == 200


def test_delete_account_anonymises_suggestions(app, client):
    register(client, "zack")
    f = app.test_client()
    register(f, "friend", name="Friend")
    f.post("/games/add", data={"name": "Keep", "min_players": 1, "max_players": 2, "has_it": "on"})
    f.post("/account", data={"action": "delete", "current": "correct-horse-1"})
    with app.app_context():
        assert User.query.filter_by(username="friend").first() is None
        assert Game.query.one().suggested_by_id is None
    html = client.get("/games").get_data(as_text=True)
    assert "Friend" not in html and "former member" in html


def test_admin_cannot_remove_last_admin(app, client):
    register(client, "zack")
    with app.app_context():
        uid = User.query.one().id
    client.post(f"/admin/users/{uid}/admin")
    with app.app_context():
        assert User.query.one().is_admin


def test_security_headers(client):
    r = client.get("/login")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"
