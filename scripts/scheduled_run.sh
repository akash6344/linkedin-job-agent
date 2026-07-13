#!/usr/bin/env bash
# Scheduled run — used by LaunchAgent / cron
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if [[ -d .venv ]]; then
  source .venv/bin/activate
fi

echo "=== LinkedIn agent scheduled run $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
python -m linkedin_agent run
