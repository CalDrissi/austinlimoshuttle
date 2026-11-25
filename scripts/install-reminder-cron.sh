#!/usr/bin/env bash
#
# Install the hourly pickup-reminder cron on the VPS host.
#
# The backend runs in Docker with no worker process, so reminders depend on a
# host cron calling the management command inside the container. Hourly, not
# daily: the command only mails bookings entering the 24h window that have not
# already been reminded (EmailLog dedupe), so running often is safe and running
# rarely means a booking made 20 hours ahead never gets one.
#
#   ssh root@<vps> 'bash /opt/austinlimoshuttle/scripts/install-reminder-cron.sh'
#
# Idempotent: the job is tagged with a marker comment and replaced, never
# duplicated, on re-run.
set -euo pipefail

APP_DIR=/opt/austinlimoshuttle
MARKER="# austinlimoshuttle:send_pickup_reminders"
LOG=/var/log/limo-pickup-reminders.log

JOB="0 * * * * cd $APP_DIR && docker compose -f docker-compose.prod.yml exec -T backend python manage.py send_pickup_reminders >> $LOG 2>&1 $MARKER"

# Replace any previously installed copy of this job, keep everything else.
# `grep -v` exits 1 when it filters every line (a crontab holding only our
# job), which pipefail would turn into a bogus failure -- hence `|| true`.
current="$(crontab -l 2>/dev/null || true)"
{ printf '%s\n' "$current" | grep -vF "$MARKER" || true; echo "$JOB"; } | crontab -

echo "Installed hourly pickup-reminder cron:"
crontab -l | grep -F "$MARKER"
