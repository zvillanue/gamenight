# Game Night

A small private web app for organising game nights with friends.

- Login first; accounts collect only **name, username, password, and how you know Zack**
- Countdown to the next game night, with Going / Can't make it
- Home page shows who's coming, grouped by affiliation (hover a group to see names)
- Members suggest games (players range, type, genre, info, photo, "I have it") and food
- Everyone votes on games and food for the upcoming night; top 5 shown, search for the rest
- Game cards turn **yellow** when attendance is a little over the max players and **red** when it's well over
- Admin panel (the first account to register): game nights, affiliation options, members, password resets

Stack: Flask, SQLite, Gunicorn, Redis (rate limits), behind Caddy. Same conventions as `obsidian-store`.

## Develop

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
FLASK_DEBUG=1 .venv/bin/flask --app wsgi run
.venv/bin/pytest
```

## Security notes

- Passwords hashed with scrypt; changing one signs out every other session
- CSRF tokens on every form; strict CSP (no inline script/style); `HttpOnly`/`Secure`/`SameSite` cookies
- Login and registration rate-limited; generic login errors; constant-ish timing for unknown usernames
- Optional `INVITE_CODE` so only people you give it to can register
- Uploaded photos are validated, re-encoded to JPEG (strips EXIF/GPS), renamed randomly, and only served to logged-in members
- Members can delete their own account and data; deleted members' suggestions stay, without their name
- Nightly integrity-checked backups (`deploy/backup.sh`)

Deployment: see [DEPLOY.md](DEPLOY.md).
