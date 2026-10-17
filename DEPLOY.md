# Deploying Game Night on the shared VPS

Several sites share one VPS through **one reverse proxy (Caddy)**, which routes by
hostname: `obsidiandevices.com` -> the store, `gamenight.<your domain>` -> this app.
Both apps listen only on Docker networks / `127.0.0.1`; only Caddy is public on 80/443.
This builds on `obsidian-store/DEPLOY-VPS.md`, which already runs Caddy.

> **Domain:** `zacknet.com` is registered to someone else (Spaceship reports it taken), so you
> can't point it anywhere. Your Spaceship account owns `thezacknet.com`, which the examples
> below use. Swap in whatever you end up with, including in the store's `deploy/Caddyfile`.

## 1. DNS (Spaceship)

Add an A record: host `gamenight`, value `40.160.149.103`, TTL 300. (Don't touch the
Proton MX/SPF/DKIM records.) Check: `dig +short gamenight.thezacknet.com`.

## 2. Get the code on the VPS

```sh
cd ~/docker
# same read-only deploy-key approach as the store (DEPLOY-VPS.md step 5), key named gamenight_deploy
git clone git@github.com:zvillanue/gamenight.git
cd gamenight
cp .env.example .env && chmod 600 .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # paste as SECRET_KEY
# also set INVITE_CODE to something friends can type
mkdir -p instance/uploads && sudo chown -R 1000:1000 instance
```

## 3. Start the app (before touching Caddy)

```sh
docker network create obsidian-shared 2>/dev/null || true   # already exists if the store runs
docker compose up --build -d
curl -sI http://127.0.0.1:5001/login | head -1                # HTTP/1.1 200 OK
```

## 4. Update the store's Caddy

On the obsidian-store branch, `deploy/Caddyfile` gains a `gamenight...` block and
`docker-compose.proxy.yml` joins Caddy to `obsidian-shared`. After merging:

```sh
cd ~/docker/obsidian-store && git pull
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d
docker compose logs -f caddy      # watch it fetch the gamenight certificate
```

The store keeps running; Caddy only restarts. Check `https://obsidiandevices.com` still works
**and** `https://gamenight.thezacknet.com` loads with a valid certificate.

## 5. First account = admin

**Register your account first, before sharing the URL.** Then in Admin: add the "how do you
know Zack" options (Work, Church...), and schedule the next game night. Then share the invite code.

## 6. Backups

```sh
sudo apt install -y sqlite3
crontab -e
45 3 * * * ~/docker/gamenight/deploy/backup.sh >> ~/gamenight-backup.log 2>&1
```

Same warning as the store: a backup on the same VPS isn't enough. Copy `~/backups/gamenight/`
to another machine (rsync over Tailscale). Restore test: stop the app, copy a `.db` over
`instance/gamenight.db`, start it, log in.

## Operations

- Update: `git pull && docker compose up --build -d`
- Locked out of the admin account: `docker compose exec gamenight flask --app wsgi set-password <username>`
- Logs: `docker compose logs -f gamenight`
- Nothing else should be published: only `127.0.0.1:5001`. Don't add public `ports:`
  (Docker bypasses `ufw`).
