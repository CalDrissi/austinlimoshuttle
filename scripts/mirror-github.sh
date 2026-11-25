#!/usr/bin/env bash
# Run on the VPS to back up a deployed commit without affecting deployment.
set -euo pipefail
cd /opt/austinlimoshuttle
commit="${1:-$(git rev-parse HEAD)}"
git rev-parse --verify "$commit^{commit}" >/dev/null
# Never overwrite remote history if a GitHub branch has advanced independently.
git push origin "$commit:refs/heads/trunk" "$commit:refs/heads/main"
