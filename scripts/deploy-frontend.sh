#!/usr/bin/env bash
#
# Gate-free frontend fast-deploy (host Next.js under pm2).
#
# The Next.js storefront no longer runs in Docker — it runs on the host via
# pm2 (see ecosystem.config.js). This script does a BUILD-BEFORE-RESTART deploy
# so the live pm2 process keeps serving the old build until the new one is
# compiled; only a successful build triggers the restart.
#
#   ssh root@<vps>  'bash /opt/austinlimoshuttle/scripts/deploy-frontend.sh'
#
# Backend + DB stay in Docker and go through the normal merge gate; this path
# is for frontend-only changes and is intentionally gate-free.
set -euo pipefail

APP_DIR=/opt/austinlimoshuttle
cd "$APP_DIR"

git pull origin main

# CRITICAL: NEXT_PUBLIC_* are inlined into the client bundle at BUILD time, so
# the host build MUST use the exact same values the Docker build used, sourced
# from the single source of truth (the git-ignored root .env). If they are
# wrong/missing the site silently points at the wrong API, so we fail loudly.
NEXT_PUBLIC_API_BASE_URL="$(grep -E '^NEXT_PUBLIC_API_BASE_URL=' .env | cut -d= -f2- || true)"
NEXT_PUBLIC_USE_MOCKS="$(grep -E '^NEXT_PUBLIC_USE_MOCKS=' .env | cut -d= -f2- || true)"
: "${NEXT_PUBLIC_API_BASE_URL:?NEXT_PUBLIC_API_BASE_URL missing from $APP_DIR/.env}"
export NEXT_PUBLIC_API_BASE_URL
export NEXT_PUBLIC_USE_MOCKS="${NEXT_PUBLIC_USE_MOCKS:-false}"
export NEXT_TELEMETRY_DISABLED=1

cd frontend
npm ci --prefer-offline
npm run build

# Build succeeded — swap the running process over to the new build.
pm2 restart limo-frontend --update-env
pm2 save

echo "deploy-frontend: limo-frontend restarted on the new build."
