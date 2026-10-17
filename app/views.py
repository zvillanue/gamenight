import re
from collections import defaultdict
from datetime import timedelta

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import db, limiter
from app.images import delete_game_image, save_game_image
from app.models import (Food, FoodVote, Game, GameNight, GameOwner, GameVote, Group, Rsvp, User,
                        utcnow)
from app.util import CAPACITY_TEXT, capacity_status, clean, safe_next

views_bp = Blueprint("views", __name__)

TOP_N = 5
# A night stays "next" for a few hours after it starts so the page still
# makes sense while everyone is playing.
GRACE = timedelta(hours=6)


def next_night():
    return (GameNight.query.filter(GameNight.starts_at > utcnow() - GRACE)
            .order_by(GameNight.starts_at).first())


def going_count(night):
    if not night:
        return 0
    return Rsvp.query.filter_by(night_id=night.id, going=True).count()


def matches(q, *fields):
    q = q.lower()
    return any(q in (f or "").lower() for f in fields)


def ranked_games(night, q=""):
    games = Game.query.options(selectinload(Game.owners).selectinload(GameOwner.user),
                               selectinload(Game.suggester)).all()
    counts = dict(db.session.query(GameVote.game_id, func.count()).filter_by(night_id=night.id)
                  .group_by(GameVote.game_id).all()) if night else {}
    mine = {v.game_id for v in GameVote.query.filter_by(night_id=night.id, user_id=current_user.id)} if night else set()
    n = going_count(night)
    rows = []
    for g in games:
        if q and not matches(q, g.name, g.game_type, g.genre, g.info):
            continue
        status = capacity_status(n, g.max_players)
        rows.append({"game": g, "votes": counts.get(g.id, 0), "voted": g.id in mine,
                     "status": status, "status_text": CAPACITY_TEXT[status],
                     "owners": sorted(o.user.name for o in g.owners),
                     "i_own": any(o.user_id == current_user.id for o in g.owners)})
    rows.sort(key=lambda r: (-r["votes"], r["game"].name.lower()))
    return rows


def ranked_food(night, q=""):
    foods = Food.query.options(selectinload(Food.suggester)).all()
    counts = dict(db.session.query(FoodVote.food_id, func.count()).filter_by(night_id=night.id)
                  .group_by(FoodVote.food_id).all()) if night else {}
    mine = {v.food_id for v in FoodVote.query.filter_by(night_id=night.id, user_id=current_user.id)} if night else set()
    rows = [{"food": f, "votes": counts.get(f.id, 0), "voted": f.id in mine}
            for f in foods if not q or matches(q, f.name, f.notes)]
    rows.sort(key=lambda r: (-r["votes"], r["food"].name.lower()))
    return rows


@views_bp.route("/")
@login_required
def home():
    night = next_night()
    by_group = defaultdict(list)
    my_rsvp = None
    if night:
        for r in Rsvp.query.options(selectinload(Rsvp.user).selectinload(User.group)) \
                .filter_by(night_id=night.id).all():
            if r.user_id == current_user.id:
                my_rsvp = r.going
            if r.going:
                by_group[r.user.group.name if r.user.group else "Other"].append(r.user.name)
    groups = sorted(((g, sorted(names)) for g, names in by_group.items()),
                    key=lambda kv: (-len(kv[1]), kv[0]))
    return render_template(
        "home.html", night=night, my_rsvp=my_rsvp, groups=groups,
        total_going=sum(len(n) for _, n in groups),
        games=ranked_games(night)[:TOP_N], foods=ranked_food(night)[:TOP_N])


@views_bp.route("/rsvp", methods=["POST"])
@login_required
def rsvp():
    night = next_night()
    if not night:
        flash("There's no game night scheduled yet.", "error")
        return redirect(url_for("views.home"))
    going = request.form.get("going") == "yes"
    row = Rsvp.query.filter_by(user_id=current_user.id, night_id=night.id).first()
    if row:
        row.going = going
    else:
        db.session.add(Rsvp(user_id=current_user.id, night_id=night.id, going=going))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return redirect(safe_next(url_for("views.home")))


# ---- games -----------------------------------------------------------------

def read_game_form():
    """Return (fields, error) from the add/edit game form."""
    name = clean(request.form.get("name"), 100)
    lo = request.form.get("min_players", type=int)
    hi = request.form.get("max_players", type=int)
    if not name:
        return None, "Give the game a name."
    if lo is None or hi is None or not (1 <= lo <= hi <= 99):
        return None, "Player count must be a range like 1 to 4."
    return {"name": name, "min_players": lo, "max_players": hi,
            "game_type": clean(request.form.get("game_type"), 40),
            "genre": clean(request.form.get("genre"), 40),
            "info": clean(request.form.get("info"), 500)}, None


@views_bp.route("/games")
@login_required
def games():
    q = clean(request.args.get("q"), 60)
    night = next_night()
    return render_template("games.html", night=night, q=q, games=ranked_games(night, q))


@views_bp.route("/games/add", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def game_add():
    fields, error = read_game_form()
    if not error and Game.query.filter(func.lower(Game.name) == fields["name"].lower()).first():
        error = "That game is already on the list - go vote for it!"
    image = None
    upload = request.files.get("image")
    if not error and upload and upload.filename:
        try:
            image = save_game_image(upload, current_app.config["UPLOAD_FOLDER"])
        except ValueError as e:
            error = str(e)
    if error:
        flash(error, "error")
        return redirect(url_for("views.games"))
    game = Game(**fields, image=image, suggested_by_id=current_user.id)
    db.session.add(game)
    db.session.flush()
    if request.form.get("has_it"):
        db.session.add(GameOwner(user_id=current_user.id, game_id=game.id))
    night = next_night()
    if night:
        db.session.add(GameVote(user_id=current_user.id, game_id=game.id, night_id=night.id))
    db.session.commit()
    flash(f"Added {game.name}.", "ok")
    return redirect(url_for("views.games"))


def editable_game(game_id):
    game = db.session.get(Game, game_id) or abort(404)
    if not (current_user.is_admin or game.suggested_by_id == current_user.id):
        abort(403)
    return game


@views_bp.route("/games/<int:game_id>/edit", methods=["GET", "POST"])
@login_required
def game_edit(game_id):
    game = editable_game(game_id)
    if request.method == "POST":
        fields, error = read_game_form()
        clash = fields and Game.query.filter(func.lower(Game.name) == fields["name"].lower(),
                                             Game.id != game.id).first()
        if clash:
            error = "Another game already has that name."
        new_image = None
        upload = request.files.get("image")
        if not error and upload and upload.filename:
            try:
                new_image = save_game_image(upload, current_app.config["UPLOAD_FOLDER"])
            except ValueError as e:
                error = str(e)
        if error:
            flash(error, "error")
        else:
            for k, v in fields.items():
                setattr(game, k, v)
            folder = current_app.config["UPLOAD_FOLDER"]
            if new_image or request.form.get("remove_image"):
                delete_game_image(game.image, folder)
                game.image = new_image
            db.session.commit()
            flash("Saved.", "ok")
            return redirect(url_for("views.games"))
    return render_template("game_edit.html", game=game)


@views_bp.route("/games/<int:game_id>/delete", methods=["POST"])
@login_required
def game_delete(game_id):
    game = editable_game(game_id)
    GameVote.query.filter_by(game_id=game.id).delete()
    delete_game_image(game.image, current_app.config["UPLOAD_FOLDER"])
    db.session.delete(game)
    db.session.commit()
    flash("Game removed.", "ok")
    return redirect(url_for("views.games"))


def toggle_vote(model, fk, item_id):
    night = next_night()
    if not night:
        flash("Voting opens once a game night is scheduled.", "error")
        return
    row = model.query.filter_by(user_id=current_user.id, night_id=night.id, **{fk: item_id}).first()
    if row:
        db.session.delete(row)
    else:
        db.session.add(model(user_id=current_user.id, night_id=night.id, **{fk: item_id}))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


@views_bp.route("/games/<int:game_id>/vote", methods=["POST"])
@login_required
def game_vote(game_id):
    db.session.get(Game, game_id) or abort(404)
    toggle_vote(GameVote, "game_id", game_id)
    return redirect(safe_next(url_for("views.games")))


@views_bp.route("/games/<int:game_id>/own", methods=["POST"])
@login_required
def game_own(game_id):
    db.session.get(Game, game_id) or abort(404)
    row = GameOwner.query.filter_by(user_id=current_user.id, game_id=game_id).first()
    if row:
        db.session.delete(row)
    else:
        db.session.add(GameOwner(user_id=current_user.id, game_id=game_id))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return redirect(safe_next(url_for("views.games")))


# ---- food ------------------------------------------------------------------

@views_bp.route("/food")
@login_required
def food():
    q = clean(request.args.get("q"), 60)
    night = next_night()
    return render_template("food.html", night=night, q=q, foods=ranked_food(night, q))


@views_bp.route("/food/add", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def food_add():
    name = clean(request.form.get("name"), 100)
    if not name:
        flash("Give the food option a name.", "error")
    elif Food.query.filter(func.lower(Food.name) == name.lower()).first():
        flash("That's already on the list - go vote for it!", "error")
    else:
        item = Food(name=name, notes=clean(request.form.get("notes"), 300),
                    suggested_by_id=current_user.id)
        db.session.add(item)
        db.session.flush()
        night = next_night()
        if night:
            db.session.add(FoodVote(user_id=current_user.id, food_id=item.id, night_id=night.id))
        db.session.commit()
        flash(f"Added {name}.", "ok")
    return redirect(url_for("views.food"))


@views_bp.route("/food/<int:food_id>/vote", methods=["POST"])
@login_required
def food_vote(food_id):
    db.session.get(Food, food_id) or abort(404)
    toggle_vote(FoodVote, "food_id", food_id)
    return redirect(safe_next(url_for("views.food")))


@views_bp.route("/food/<int:food_id>/delete", methods=["POST"])
@login_required
def food_delete(food_id):
    item = db.session.get(Food, food_id) or abort(404)
    if not (current_user.is_admin or item.suggested_by_id == current_user.id):
        abort(403)
    FoodVote.query.filter_by(food_id=item.id).delete()
    db.session.delete(item)
    db.session.commit()
    flash("Removed.", "ok")
    return redirect(url_for("views.food"))


# ---- uploaded photos (members only) ------------------------------------------

@views_bp.route("/img/<filename>")
@login_required
def game_image(filename):
    if not re.fullmatch(r"[0-9a-f]{32}\.jpg", filename):
        abort(404)
    resp = send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp
