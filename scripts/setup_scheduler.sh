#!/usr/bin/env bash
# Install scheduler — every 30 minutes (default) + run on Mac wake
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SCRIPT="$ROOT/scripts/scheduled_run.sh"
WAKE_SCRIPT="$ROOT/scripts/wake_listener.sh"
LOG="$ROOT/logs/cron.log"
WAKE_LOG="$ROOT/logs/wake.log"
LABEL="com.linkedin.jobagent"
WAKE_LABEL="com.linkedin.jobagent.wake"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
WAKE_PLIST="$HOME/Library/LaunchAgents/${WAKE_LABEL}.plist"

# Prefer SCHEDULE_INTERVAL_SEC from env, else from .env, else 30 minutes
if [[ -z "${SCHEDULE_INTERVAL_SEC:-}" && -f "$ROOT/.env" ]]; then
  INTERVAL_FROM_ENV="$(grep -E '^SCHEDULE_INTERVAL_SEC=' "$ROOT/.env" | tail -1 | cut -d= -f2- | tr -d '[:space:]"'"'" || true)"
  if [[ -n "${INTERVAL_FROM_ENV:-}" ]]; then
    SCHEDULE_INTERVAL_SEC="$INTERVAL_FROM_ENV"
  fi
fi
INTERVAL_SEC="${SCHEDULE_INTERVAL_SEC:-1800}"

chmod +x "$RUN_SCRIPT" "$ROOT/scripts/run.sh" "$ROOT/scripts/on_wake.sh" "$WAKE_SCRIPT"
mkdir -p "$ROOT/logs" "$ROOT/data"

echo "LinkedIn Job Agent Scheduler"
echo "============================"
echo "Every $(( INTERVAL_SEC / 60 )) minutes: $RUN_SCRIPT"
echo "On Mac wake:   $ROOT/scripts/on_wake.sh"
echo "Log:           $LOG"
echo "Wake log:      $WAKE_LOG"
echo ""

if [[ "$(uname -s)" == "Darwin" ]]; then
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${RUN_SCRIPT}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT}</string>
    <key>StartInterval</key>
    <integer>${INTERVAL_SEC}</integer>
    <key>StandardOutPath</key>
    <string>${LOG}</string>
    <key>StandardErrorPath</key>
    <string>${LOG}</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

  cat > "$WAKE_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${WAKE_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${WAKE_SCRIPT}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT}</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${WAKE_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${WAKE_LOG}</string>
</dict>
</plist>
EOF

  UID_NUM="$(id -u)"
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  launchctl bootout "gui/${UID_NUM}/${WAKE_LABEL}" 2>/dev/null || true
  launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
  launchctl bootstrap "gui/${UID_NUM}" "$WAKE_PLIST"
  launchctl enable "gui/${UID_NUM}/${LABEL}"
  launchctl enable "gui/${UID_NUM}/${WAKE_LABEL}"

  echo "Installed:"
  echo "  • Every $(( INTERVAL_SEC / 60 )) minutes — ${LABEL} (runs immediately now)"
  echo "  • On wake from sleep — ${WAKE_LABEL}"
  echo ""
  echo "  bash scripts/stop.sh   — pause"
  echo "  bash scripts/start.sh  — resume"
  echo "  tail -f ${LOG}"
else
  # Every 30 minutes
  CRON_LINE="*/30 * * * * ${RUN_SCRIPT}"
  EXISTING=$(crontab -l 2>/dev/null || true)
  FILTERED=$(echo "$EXISTING" | grep -vF "linkedin-job-agent" | grep -vF "linkedin_agent" || true)
  {
    echo "$FILTERED"
    echo ""
    echo "# LinkedIn job agent — every 30 minutes"
    echo "$CRON_LINE"
  } | crontab -
  echo "Cron installed: $CRON_LINE"
fi
