#!/usr/bin/env bash
# Run on the Mac. Deploy the committed local HEAD directly to the server.
set -euo pipefail

if [ "$#" -ne 1 ] || [[ ! "$1" =~ ^(frontend|backend|all)$ ]]; then
  echo "Usage: $0 frontend|backend|all" >&2
  exit 2
fi
lane="$1"
repo="$(git rev-parse --show-toplevel)"
commit="$(git -C "$repo" rev-parse HEAD)"
host=root@209.145.59.30
key="$HOME/.ssh/limo_deploy"
export GIT_SSH_COMMAND="ssh -i $key -o BatchMode=yes"

git -C "$repo" push "$host:/opt/austinlimoshuttle" "$commit:refs/deploy/incoming"
ssh -i "$key" -o BatchMode=yes "$host" bash -s -- "$commit" "$lane" <<'REMOTE'
set -euo pipefail
commit="$1"
lane="$2"
cd /opt/austinlimoshuttle
# Serialize checkout and builds; refuse to deploy if another push overtook us.
exec 9>/tmp/austinlimoshuttle-deploy.lock
flock -x 9
[ "$(git rev-parse refs/deploy/incoming)" = "$commit" ] || { echo 'Deploy ref changed; retry deploy' >&2; exit 1; }
previous="$(git rev-parse HEAD)"
git checkout --detach "$commit"
[ "$(git rev-parse HEAD)" = "$commit" ]
if [ "$lane" = backend ] || [ "$lane" = all ]; then
  DEPLOY_PREVIOUS_COMMIT="$previous" bash scripts/deploy-backend.sh
fi
if [ "$lane" = frontend ] || [ "$lane" = all ]; then
  bash scripts/deploy-frontend.sh
fi
echo "Deployed $commit ($lane)"
# Backup is independent of the deploy result and runs after its lock is released.
nohup bash scripts/mirror-github.sh "$commit" </dev/null >>/tmp/austinlimoshuttle-mirror.log 2>&1 9>&- &
REMOTE

# Direct deploy verification marker.
