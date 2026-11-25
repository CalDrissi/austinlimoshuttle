// PM2 process definition for the host-run Next.js frontend.
//
// Backend + DB stay in Docker (docker-compose.prod.yml, still gated). Only the
// Next.js storefront runs on the host under pm2, so frontend deploys are
// gate-free and build-before-restart (see scripts/deploy-frontend.sh).
//
// USER: pm2 runs under the unprivileged `limoweb` system user (never root) —
// scripts/deploy-frontend.sh builds and reloads as limoweb, and the
// pm2-limoweb systemd unit resurrects this process list at boot.
//
// PORT/HOST: nginx (HestiaCP) reverse-proxies the public domain's "/" to
// 127.0.0.1:3001 (see /home/austin/conf/web/testmode.austinlimoshuttle.com/
// nginx.ssl.conf). PORT MUST stay 3001 to match that proxy target, otherwise
// the public site 502s. "-H 127.0.0.1" MUST stay: nginx proxies locally and
// the app must never listen on public interfaces. Both are also passed
// explicitly to `next start` as a belt-and-suspenders guard in case the env
// is dropped on --update-env.
//
// NEXT_PUBLIC_* are NOT set here: they are inlined into the client bundle at
// BUILD time by scripts/deploy-frontend.sh (sourced from the root .env), so
// they only need to be correct during `next build`, not at runtime.
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
  ],
}
