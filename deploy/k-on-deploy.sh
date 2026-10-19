#!/usr/bin/env bash
# Rolls out a release bundle (tar.gz on stdin) with automatic rollback.
# Installed as /usr/local/sbin/k-on-deploy; fed by /usr/local/sbin/k-on-pull, which downloads the bundle
# that CI publishes to the GitHub release "server-build".
#
# Bundle layout: backend/ (without tests), scripts/, frontend/dist/, deploy/
set -euo pipefail

APP=/opt/k-on-office
DATA=/var/lib/k-on-office
ENV_FILE=/etc/k-on-office.env
SERVICE=k-on-office
UV=/root/.local/bin/uv
INDEX=https://mirrors.aliyun.com/pypi/simple/
KEEP=5
TS=$(date +%Y%m%d-%H%M%S)
STAGE=$(mktemp -d /tmp/k-on-release.XXXXXX)
BACKUP_DIR=/root/backups/k-on-releases
CODE_BACKUP="$BACKUP_DIR/code-$TS.tgz"
DB_BACKUP="$DATA/backups/predeploy-$TS.sqlite3"

log() { echo "[k-on-deploy] $*"; }
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

exec 9>/run/k-on-deploy.lock
flock -n 9 || { log "another deployment is running"; exit 1; }

log "receiving bundle"
head -c 200000000 | tar -xzf - -C "$STAGE"
for f in backend/app/main.py backend/requirements.lock.txt backend/alembic.ini frontend/dist/index.html; do
  [ -f "$STAGE/$f" ] || { log "bundle is missing $f, nothing changed"; exit 1; }
done

log "backing up current code and database"
mkdir -p "$BACKUP_DIR" "$DATA/backups"
chown kon:kon "$DATA/backups"
chmod 750 "$DATA/backups"
tar -czf "$CODE_BACKUP" --exclude=backend/.venv -C "$APP" .
runuser -u kon -- "$APP/backend/.venv/bin/python" -c "
import sqlite3, sys
s = sqlite3.connect('$DATA/k-on.sqlite3'); d = sqlite3.connect('$DB_BACKUP'); s.backup(d); d.close(); s.close()"
chmod 640 "$DB_BACKUP"

rollback() {
  log "FAILED, rolling back code to $CODE_BACKUP"
  find "$APP" -mindepth 1 -maxdepth 1 ! -name backend -exec rm -rf {} +
  find "$APP/backend" -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +
  tar -xzf "$CODE_BACKUP" -C "$APP"
  if [ "${MIGRATED:-0}" = 1 ]; then
    log "restoring database from $DB_BACKUP"
    systemctl stop "$SERVICE"
    cp -p "$DB_BACKUP" "$DATA/k-on.sqlite3"
    rm -f "$DATA/k-on.sqlite3-wal" "$DATA/k-on.sqlite3-shm"
  fi
  systemctl restart "$SERVICE" || true
  exit 1
}
trap 'rollback' ERR

OLD_LOCK=$(sha256sum "$APP/backend/requirements.lock.txt" | cut -d' ' -f1)
log "syncing code"
rsync -a --delete --exclude 'backend/.venv' "$STAGE/" "$APP/"
chown -R root:root "$APP"
find "$APP" -path "$APP/backend/.venv" -prune -o -type d -exec chmod 755 {} + -o -type f -exec chmod 644 {} +

if [ "$(sha256sum "$APP/backend/requirements.lock.txt" | cut -d' ' -f1)" != "$OLD_LOCK" ]; then
  log "dependencies changed, installing"
  UV_DEFAULT_INDEX=$INDEX "$UV" pip install -q --python "$APP/backend/.venv/bin/python" -r "$APP/backend/requirements.lock.txt"
fi

log "migrating database"
MIGRATED=1  # from here on a failure also restores the pre-deploy database copy
(
  cd "$APP/backend"
  set -a; . "$ENV_FILE"; set +a
  runuser -u kon -- "$APP/backend/.venv/bin/python" -m alembic upgrade head
)

log "restarting service"
systemctl restart "$SERVICE"
for i in $(seq 1 30); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/api/health; then
    trap - ERR
    log "healthy after ${i}s, release $TS is live"
    ls -1t "$BACKUP_DIR"/code-*.tgz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
    ls -1t "$DATA"/backups/predeploy-*.sqlite3 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
    exit 0
  fi
  sleep 1
done
log "service did not become healthy in 30s"
rollback
