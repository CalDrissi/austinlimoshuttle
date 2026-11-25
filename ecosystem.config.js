// PM2 process definitions for the host-run app: Next.js frontend + Django
// backend (gunicorn). Both deploy through gate-free fast-lane scripts
// (scripts/deploy-frontend.sh / scripts/deploy-backend.sh); only MariaDB
// stays in Docker (limo-prod-db, published to the host on 127.0.0.1:3307 via
// docker-compose.db-hostport.yml).
//
// USER: pm2 runs under the unprivileged `limoweb` system user (never root) —
// the deploy scripts build/migrate and reload as limoweb, and the
// pm2-limoweb systemd unit resurrects this process list at boot.
//
// PORTS/HOST: nginx (HestiaCP) reverse-proxies the public domain — "/" to
// 127.0.0.1:3001 (Next.js) and /api/ /dashboard/ /admin/ /driver/ /accounts/
// /static/ /media/ to 127.0.0.1:8001 (gunicorn; WhiteNoise serves /static,
// Django serves /media). See /home/austin/conf/web/
// testmode.austinlimoshuttle.com/nginx.ssl.conf. Ports 3001/8001 MUST stay as
// they are to match those proxy targets, and both apps MUST bind 127.0.0.1
// only: nginx proxies locally and nothing may listen on public interfaces.
//
// Frontend NEXT_PUBLIC_* are NOT set here: they are inlined into the client
// bundle at BUILD time by scripts/deploy-frontend.sh (sourced from the root
// .env). Backend secrets are NOT set here either: django-environ reads the
// git-ignored backend/.env (DB on 127.0.0.1:3307, host static/media paths).
module.exports = {
  apps: [
    {
      name: 'limo-frontend',
      cwd: '/opt/austinlimoshuttle/frontend',
      script: 'npm',
      args: 'start -- -p 3001 -H 127.0.0.1',
      env: {
        NODE_ENV: 'production',
        PORT: '3001',
        HOST: '127.0.0.1',
        NEXT_TELEMETRY_DISABLED: '1',
      },
      autorestart: true,
      max_restarts: 10,
      time: true,
    },
    {
      // Mirrors the old container command (3 workers, 60s timeout). Reloaded
      // gracefully by scripts/deploy-backend.sh via `pm2 sendSignal SIGHUP`
      // (gunicorn master re-forks workers on new code, zero dropped requests)
      // — a plain `pm2 reload` would hard-restart the master instead.
      name: 'limo-backend',
      cwd: '/opt/austinlimoshuttle/backend',
      script: '/opt/austinlimoshuttle/backend/.venv/bin/gunicorn',
      args: 'config.wsgi:application --bind 127.0.0.1:8001 --workers 3 --timeout 60 --access-logfile - --error-logfile -',
      interpreter: 'none',
      env: {
        DJANGO_SETTINGS_MODULE: 'config.settings.prod',
      },
      autorestart: true,
      max_restarts: 10,
      time: true,
    },
  ],
}
