import hmac

from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from app import db, limiter
from app.models import DUMMY_HASH, Group, User, delete_user
from app.util import USERNAME_RE, clean, password_problem, safe_next

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("views.home"))
    if request.method == "POST":
        username = clean(request.form.get("username"), 32).lower()
        password = request.form.get("password", "")[:200]
        user = User.query.filter_by(username=username).first()
        if user:
            ok = user.check_password(password)
        else:
            check_password_hash(DUMMY_HASH, password)
            ok = False
        if ok:
            login_user(user, remember=True)
            return redirect(safe_next(url_for("views.home")))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("views.home"))
    groups = Group.query.order_by(Group.name).all()
    invite = current_app.config["INVITE_CODE"]
    first_user = User.query.count() == 0
    if request.method == "POST":
        name = clean(request.form.get("name"), 50)
        username = clean(request.form.get("username"), 32).lower()
        password = request.form.get("password", "")
        group_id = request.form.get("group_id", type=int)
        errors = []
        if invite and not hmac.compare_digest(request.form.get("invite", "").strip(), invite):
            errors.append("That invite code isn't right.")
        if not name:
            errors.append("Please enter your name.")
        if not USERNAME_RE.match(username):
            errors.append("Username must be 3-32 characters: letters, numbers, . _ -")
        problem = password_problem(password, username)
        if problem:
            errors.append(problem)
        if password != request.form.get("password2", ""):
            errors.append("Passwords don't match.")
        if group_id and not db.session.get(Group, group_id):
            group_id = None
        if not errors and User.query.filter_by(username=username).first():
            errors.append("That username is taken.")
        if not errors:
            user = User(name=name, username=username, group_id=group_id or None,
                        is_admin=User.query.count() == 0)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("That username is taken.")
            else:
                login_user(user, remember=True)
                if user.is_admin:
                    flash("Welcome! You're the admin. Add affiliations and a game night from the Admin page.", "ok")
                return redirect(url_for("views.home"))
        for e in errors:
            flash(e, "error")
    return render_template("register.html", groups=groups, needs_invite=bool(invite), first_user=first_user)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per hour", methods=["POST"])
def account():
    groups = Group.query.order_by(Group.name).all()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = clean(request.form.get("name"), 50)
            group_id = request.form.get("group_id", type=int)
            if not name:
                flash("Name can't be empty.", "error")
            else:
                current_user.name = name
                current_user.group_id = group_id if group_id and db.session.get(Group, group_id) else None
                db.session.commit()
                flash("Saved.", "ok")
        elif action == "password":
            if not current_user.check_password(request.form.get("current", "")):
                flash("Current password is wrong.", "error")
            else:
                new = request.form.get("password", "")
                problem = password_problem(new, current_user.username)
                if problem:
                    flash(problem, "error")
                elif new != request.form.get("password2", ""):
                    flash("Passwords don't match.", "error")
                else:
                    current_user.set_password(new)
                    db.session.commit()
                    login_user(current_user, remember=True)  # keep this session alive
                    flash("Password changed. Other devices were signed out.", "ok")
        elif action == "delete":
            if not current_user.check_password(request.form.get("current", "")):
                flash("Password is wrong; account not deleted.", "error")
            elif current_user.is_admin and User.query.filter_by(is_admin=True).count() == 1:
                flash("You're the only admin. Make someone else an admin first.", "error")
            else:
                user = current_user._get_current_object()
                logout_user()
                delete_user(user)
                db.session.commit()
                flash("Your account and data were deleted.", "ok")
                return redirect(url_for("auth.login"))
        return redirect(url_for("auth.account"))
    return render_template("account.html", groups=groups)
