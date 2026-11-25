#!/usr/bin/env bash
#
# Gate-free backend fast-deploy (host gunicorn under pm2).
#
# The Django backend no longer runs in Docker — it runs on the host via
# gunicorn under pm2 as the unprivileged `limoweb` user (see
# ecosystem.config.js, app `limo-backend`), mirroring the frontend lane.
# Only MariaDB stays in Docker (limo-prod-db, reachable from the host on
# 127.0.0.1:3307 via docker-compose.db-hostport.yml).
#
#   ssh root@<vps> 'bash /opt/austinlimoshuttle/scripts/deploy-backend.sh'
#
# Semantics: any failure BEFORE the reload (pip, check, migrate,
# collectstatic) leaves the running app untouched — the live gunicorn keeps
# serving the old code. The reload itself is graceful (SIGHUP to the gunicorn
# master): old workers keep serving until the new workers have booted, so the
# cutover gap is zero. The post-reload smoke test failing means the NEW code
# is live and broken — this script exits 1 loudly so the deployer reverts
# (git revert + re-run this script).
set -euo pipefail

APP_DIR=/opt/austinlimoshuttle
SMOKE_HOST=testmode.austinlimoshuttle.com
cd "$APP_DIR"

BEFORE="$(git rev-parse HEAD)"
git pull origin main
AFTER="$(git rev-parse HEAD)"

# The pull runs as root; hand backend files back to limoweb (same pattern as
# deploy-frontend.sh) so collectstatic/media writes keep working.
chown -R limoweb:limoweb "$APP_DIR/backend"

# pip only when requirements changed — keeps the common deploy fast.
if ! git diff --quiet "$BEFORE" "$AFTER" -- backend/requirements/ 2>/dev/null; then
  echo "deploy-backend: requirements changed, installing"
  su - limoweb -s /bin/bash -c "cd '$APP_DIR/backend' \
    && .venv/bin/pip install --quiet -r requirements/prod.txt"
fi

# check → migrate → collectstatic, all against prod settings. A failure here
# aborts before the reload, so the live app is untouched.
su - limoweb -s /bin/bash -c "cd '$APP_DIR/backend' \
  && export DJANGO_SETTINGS_MODULE=config.settings.prod \
  && .venv/bin/python manage.py check \
  && .venv/bin/python manage.py migrate --no-input \
  && .venv/bin/python manage.py collectstatic --no-input"

# Graceful reload: SIGHUP makes the gunicorn master re-fork workers on the new
# code while old workers finish in-flight requests — no dropped connections.
su - limoweb -s /bin/bash -c "pm2 sendSignal SIGHUP limo-backend"

# Smoke: the API must answer 200 through the live port. Retry briefly while
# workers cycle, then fail LOUDLY — a non-200 here means the new code is live
# and broken, so revert and re-deploy.
sleep 3
for i in 1 2 3 4 5; do
  code="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Host: $SMOKE_HOST" -H 'X-Forwarded-Proto: https' \
    http://127.0.0.1:8001/api/vehicles/)" && [ "$code" = "200" ] && break
  sleep 2
done
if [ "${code:-}" != "200" ]; then
  echo "deploy-backend: SMOKE TEST FAILED — /api/vehicles/ returned ${code:-no-response}." >&2
  echo "deploy-backend: the new code is live and broken. git revert and re-run this script." >&2
  exit 1
fi

echo "deploy-backend: limo-backend reloaded on $(git rev-parse --short HEAD), smoke 200 (user: limoweb)."
