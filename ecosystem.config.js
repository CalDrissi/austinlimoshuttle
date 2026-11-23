// PM2 process definition for the host-run Next.js frontend.
//
// Backend + DB stay in Docker (docker-compose.prod.yml, still gated). Only the
// Next.js storefront runs on the host under pm2, so frontend deploys are
// gate-free and build-before-restart (see scripts/deploy-frontend.sh).
//
// PORT: nginx (HestiaCP) reverse-proxies the public domain's "/" to
// 127.0.0.1:3001 (see /home/austin/conf/web/testmode.austinlimoshuttle.com/
// nginx.ssl.conf). PORT MUST stay 3001 to match that proxy target, otherwise
// the public site 502s. "-p 3001" is also passed explicitly to `next start`
// as a belt-and-suspenders guard in case PORT is dropped on --update-env.
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
      args: 'start -- -p 3001',
      env: {
        NODE_ENV: 'production',
        PORT: '3001',
        NEXT_TELEMETRY_DISABLED: '1',
      },
      autorestart: true,
      max_restarts: 10,
      time: true,
    },
  ],
}
