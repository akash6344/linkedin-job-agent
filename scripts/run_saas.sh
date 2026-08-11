#!/usr/bin/env bash
# Start LetItApply SaaS locally
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src"
exec python3 -m uvicorn jobsearch_saas.api.app:app --reload --app-dir src --host 127.0.0.1 --port "${PORT:-8000}"
