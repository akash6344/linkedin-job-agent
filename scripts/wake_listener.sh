#!/usr/bin/env bash
# Background listener — triggers agent when Mac wakes from sleep
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ON_WAKE="$ROOT/scripts/on_wake.sh"
LOG="$ROOT/logs/wake.log"

mkdir -p "$ROOT/logs"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) wake listener started (pid $$)" >> "$LOG"

PREDICATE='process == "powerd" AND (eventMessage CONTAINS[c] "Wake reason" OR eventMessage CONTAINS[c] "DarkWake from")'

while true; do
  log stream --style syslog --predicate "$PREDICATE" 2>> "$LOG" | while read -r _; do
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) wake event detected" >> "$LOG"
    "$ON_WAKE" >> "$LOG" 2>&1 &
  done
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) log stream ended — restarting in 5s" >> "$LOG"
  sleep 5
done
