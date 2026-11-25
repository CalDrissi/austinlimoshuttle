#!/usr/bin/env bash
#
# Install the reminder crons on the VPS host (booking + pickup).
#
# The backend runs on the host (gunicorn under pm2, no Docker — see
# scripts/deploy-backend.sh), so the crons call the management commands
# through the backend venv directly, as the limoweb user. Both commands
# dedupe via EmailLog, so running often is safe and running rarely means a
# booking entering its window never gets a reminder.
#
#   ssh root@<vps> 'bash /opt/austinlimoshuttle/scripts/install-reminder-cron.sh'
#
# Idempotent: each job is tagged with a marker comment and replaced, never
# duplicated, on re-run. Legacy `docker compose exec backend` reminder lines
# are removed too.
set -euo pipefail

APP_DIR=/opt/austinlimoshuttle
VENV_MANAGE="cd $APP_DIR/backend && DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py"

BOOKING_MARKER="# austinlimoshuttle:send_booking_reminders"
PICKUP_MARKER="# austinlimoshuttle:send_pickup_reminders"

BOOKING_JOB="*/15 * * * * su - limoweb -s /bin/bash -c '$VENV_MANAGE send_booking_reminders' >> /var/log/limo-sms-reminders.log 2>&1 $BOOKING_MARKER"
PICKUP_JOB="0 * * * * su - limoweb -s /bin/bash -c '$VENV_MANAGE send_pickup_reminders' >> /var/log/limo-pickup-reminders.log 2>&1 $PICKUP_MARKER"

# Replace any previously installed copy of these jobs (marker-tagged or legacy
# docker-based), keep everything else. `grep -v` exits 1 when it filters every
# line, which pipefail would turn into a bogus failure -- hence `|| true`.
current="$(crontab -l 2>/dev/null || true)"
{
  printf '%s\n' "$current" \
    | grep -vF "$BOOKING_MARKER" \
    | grep -vF "$PICKUP_MARKER" \
    | grep -v "send_booking_reminders" \
    | grep -v "send_pickup_reminders" || true
  echo "$BOOKING_JOB"
  echo "$PICKUP_JOB"
} | crontab -

echo "Installed reminder crons (host venv, user limoweb):"
crontab -l | grep -F "austinlimoshuttle:"
