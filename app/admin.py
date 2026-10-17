from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import db, limiter
from app.models import FoodVote, GameNight, GameVote, Group, Rsvp, User, delete_user
from app.util import clean, parse_local_datetime, password_problem

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@admin_bp.route("/")
@admin_required
def panel():
    return render_template(
        "admin.html",
        nights=GameNight.query.order_by(GameNight.starts_at.desc()).all(),
        groups=Group.query.order_by(Group.name).all(),
        group_sizes=dict(db.session.query(User.group_id, func.count()).group_by(User.group_id).all()),
        users=User.query.order_by(func.lower(User.name)).all())


def done(message=None, kind="ok"):
    if message:
        flash(message, kind)
    return redirect(url_for("admin.panel"))


@admin_bp.route("/nights/add", methods=["POST"])
@admin_required
def night_add():
    try:
        starts = parse_local_datetime(request.form.get("starts_at", ""))
    except ValueError:
        return done("Pick a valid date and time.", "error")
    db.session.add(GameNight(starts_at=starts, location=clean(request.form.get("location"), 120),
                             notes=clean(request.form.get("notes"), 500)))
    db.session.commit()
    return done("Game night scheduled.")


@admin_bp.route("/nights/<int:night_id>/delete", methods=["POST"])
@admin_required
def night_delete(night_id):
    night = db.session.get(GameNight, night_id) or abort(404)
    for model in (Rsvp, GameVote, FoodVote):
        model.query.filter_by(night_id=night.id).delete()
    db.session.delete(night)
    db.session.commit()
    return done("Game night deleted along with its RSVPs and votes.")


@admin_bp.route("/groups/add", methods=["POST"])
@admin_required
def group_add():
    name = clean(request.form.get("name"), 60)
    if not name:
        return done("Enter a name.", "error")
    db.session.add(Group(name=name))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return done("That affiliation already exists.", "error")
    return done("Affiliation added.")


@admin_bp.route("/groups/<int:group_id>/delete", methods=["POST"])
@admin_required
def group_delete(group_id):
    group = db.session.get(Group, group_id) or abort(404)
    User.query.filter_by(group_id=group.id).update({"group_id": None})
    db.session.delete(group)
    db.session.commit()
    return done("Affiliation removed; those members now show as Other.")


@admin_bp.route("/users/<int:user_id>/password", methods=["POST"])
@admin_required
@limiter.limit("20 per hour")
def user_password(user_id):
    user = db.session.get(User, user_id) or abort(404)
    pw = request.form.get("password", "")
    problem = password_problem(pw, user.username)
    if problem:
        return done(problem, "error")
    user.set_password(pw)
    db.session.commit()
    return done(f"Password reset for {user.name}. Tell them privately and ask them to change it.")


@admin_bp.route("/users/<int:user_id>/admin", methods=["POST"])
@admin_required
def user_toggle_admin(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.is_admin and User.query.filter_by(is_admin=True).count() == 1:
        return done("There must be at least one admin.", "error")
    user.is_admin = not user.is_admin
    db.session.commit()
    return done(f"{user.name} is {'now' if user.is_admin else 'no longer'} an admin.")


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        return done("Delete your own account from the Account page.", "error")
    delete_user(user)
    db.session.commit()
    return done("Member deleted.")
