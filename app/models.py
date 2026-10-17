import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from app import db


def utcnow():
    """Naive UTC; every timestamp in the database is UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Group(db.Model):
    """An 'how I know Zack' option, managed from the admin panel."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    # Rotated on password change so other logged-in sessions are invalidated.
    session_token = db.Column(db.String(32), nullable=False, default=lambda: secrets.token_hex(16))
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"))
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    group = db.relationship("Group")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method="scrypt")
        self.session_token = secrets.token_hex(16)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"{self.id}.{self.session_token}"


# Verified against when a username doesn't exist, so login timing doesn't
# reveal which usernames are registered.
DUMMY_HASH = generate_password_hash("not-a-real-password", method="scrypt")


class GameNight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)  # UTC
    location = db.Column(db.String(120), default="")
    notes = db.Column(db.String(500), default="")


class Rsvp(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "night_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    night_id = db.Column(db.Integer, db.ForeignKey("game_night.id"), nullable=False)
    going = db.Column(db.Boolean, nullable=False)

    user = db.relationship("User")


class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    min_players = db.Column(db.Integer, nullable=False, default=1)
    max_players = db.Column(db.Integer, nullable=False, default=4)
    game_type = db.Column(db.String(40), default="")
    genre = db.Column(db.String(40), default="")
    info = db.Column(db.String(500), default="")
    image = db.Column(db.String(64))
    suggested_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    suggester = db.relationship("User")
    owners = db.relationship("GameOwner", cascade="all, delete-orphan")


class GameOwner(db.Model):
    """'I have this game' - the suggester and anyone else can mark it."""

    __table_args__ = (UniqueConstraint("user_id", "game_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)

    user = db.relationship("User")


class GameVote(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "game_id", "night_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    night_id = db.Column(db.Integer, db.ForeignKey("game_night.id"), nullable=False)


class Food(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.String(300), default="")
    suggested_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    suggester = db.relationship("User")


class FoodVote(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "food_id", "night_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    food_id = db.Column(db.Integer, db.ForeignKey("food.id"), nullable=False)
    night_id = db.Column(db.Integer, db.ForeignKey("game_night.id"), nullable=False)


def delete_user(user):
    """Remove a member and everything tied to them.

    Games and food they suggested stay (the group still wants them) but lose
    the link to the person, so no name is left behind.
    """
    for model in (Rsvp, GameVote, FoodVote, GameOwner):
        model.query.filter_by(user_id=user.id).delete()
    Game.query.filter_by(suggested_by_id=user.id).update({"suggested_by_id": None})
    Food.query.filter_by(suggested_by_id=user.id).update({"suggested_by_id": None})
    db.session.delete(user)
