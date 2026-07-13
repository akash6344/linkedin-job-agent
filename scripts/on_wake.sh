#!/usr/bin/env bash
# Run agent on Mac wake — debounced so one wake = one run
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEBOUNCE_FILE="$ROOT/data/last_wake_run.ts"
MIN_GAP_SEC=90

mkdir -p "$ROOT/data" "$ROOT/logs"

now=$(date +%s)
if [[ -f "$DEBOUNCE_FILE" ]]; then
  last=$(cat "$DEBOUNCE_FILE" 2>/dev/null || echo 0)
  if (( now - last < MIN_GAP_SEC )); then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) wake run skipped (debounce)"
    exit 0
  fi
fi

echo "$now" > "$DEBOUNCE_FILE"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) wake run starting"
exec "$ROOT/scripts/scheduled_run.sh"
