#!/usr/bin/env bash
# Scheduled run — used by LaunchAgent / cron
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs data

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if [[ -d .venv ]]; then
  source .venv/bin/activate
fi

# macOS has no flock(1) by default — use an atomic mkdir lock instead.
LOCK_DIR="$ROOT/data/agent.run.lockdir"
cleanup_lock() {
  rm -rf "$LOCK_DIR" 2>/dev/null || true
}

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo $$ > "$LOCK_DIR/pid"
    return 0
  fi
  # Clear stale lock if the previous PID is gone.
  local old_pid
  old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ -n "${old_pid:-}" ]] && ! kill -0 "$old_pid" 2>/dev/null; then
    rm -rf "$LOCK_DIR"
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      echo $$ > "$LOCK_DIR/pid"
      return 0
    fi
  fi
  return 1
}

if ! acquire_lock; then
  echo "=== LinkedIn agent skipped $(date -u +%Y-%m-%dT%H:%M:%SZ) — another run is already in progress ==="
  exit 0
fi
trap cleanup_lock EXIT

echo "=== LinkedIn agent scheduled run $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
python -m linkedin_agent run
