#!/usr/bin/env bash
set -euo pipefail
UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}/com.linkedin.jobagent" 2>/dev/null || true
launchctl bootout "gui/${UID_NUM}/com.linkedin.jobagent.wake" 2>/dev/null || true
pkill -f "python -m linkedin_agent" 2>/dev/null || true
echo "LinkedIn agent stopped (scheduler + wake listener)."
