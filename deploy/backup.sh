#!/usr/bin/env bash
# Nightly backup of the Game Night database and photos.
# Uses SQLite's online .backup (safe while the app is running), keeps 14 days.
# crontab:  45 3 * * * ~/docker/gamenight/deploy/backup.sh >> ~/gamenight-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
dest="${BACKUP_DIR:-$HOME/backups/gamenight}"
stamp="$(date +%F)"
umask 077
mkdir -p "$dest"
sqlite3 instance/gamenight.db ".backup '$dest/gamenight-$stamp.db'"
[ "$(sqlite3 "$dest/gamenight-$stamp.db" 'PRAGMA integrity_check;')" = ok ] || { echo "integrity check FAILED" >&2; exit 1; }
tar -czf "$dest/uploads-$stamp.tar.gz" -C instance uploads 2>/dev/null || true
find "$dest" -type f \( -name 'gamenight-*.db' -o -name 'uploads-*.tar.gz' \) -mtime +14 -delete
echo "$(date -Is) backup ok: $dest/gamenight-$stamp.db"
