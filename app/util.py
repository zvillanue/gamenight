import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import current_app, request

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")


def password_problem(password, username=""):
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if len(password) > 128:
        return "Password must be at most 128 characters."
    if username and password.lower() == username.lower():
        return "Password can't be the same as your username."
    return None


def safe_next(default="/"):
    """Return the form's 'next' target only if it is a local path."""
    target = request.form.get("next") or request.args.get("next") or ""
    parsed = urlparse(target)
    if target.startswith("/") and not target.startswith("//") and not parsed.netloc and "\\" not in target:
        return target
    return default


def capacity_status(going, max_players):
    """ok / warn (a few too many) / bad (way too many) for a game's range.

    1-4 with 6 people is 'warn'; 1-4 with 12 is 'bad'. The allowance is half
    the max, never less than two extra seats.
    """
    if going <= max_players:
        return "ok"
    if going <= max_players + max(2, math.ceil(max_players / 2)):
        return "warn"
    return "bad"


CAPACITY_TEXT = {
    "ok": "",
    "warn": "A bit crowded for this game",
    "bad": "Too many people for this game",
}


def local_dt(value, fmt="%A, %B %-d at %-I:%M %p"):
    if not value:
        return ""
    return value.replace(tzinfo=timezone.utc).astimezone(current_app.config["TZ"]).strftime(fmt)


def utc_iso(value):
    return value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_local_datetime(text):
    """Admin enters 'YYYY-MM-DDTHH:MM' in the app timezone; return naive UTC."""
    local = datetime.strptime(text, "%Y-%m-%dT%H:%M").replace(tzinfo=current_app.config["TZ"])
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def clean(text, limit):
    return " ".join((text or "").split())[:limit]
