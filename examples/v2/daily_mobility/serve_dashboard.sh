#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
EXP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${1:-${DAILY_MOBILITY_RUN_DIR:-$EXP/tmp/live/run}}"
DASHBOARD_PORT="${DAILY_MOBILITY_DASHBOARD_PORT:-8765}"
DASHBOARD_HOST="${DAILY_MOBILITY_DASHBOARD_HOST:-127.0.0.1}"
DASHBOARD_AGENT_ID="${DAILY_MOBILITY_DASHBOARD_AGENT_ID:-1}"

if [[ ! -d "$RUN_DIR" ]]; then
  echo "run dir not found: $RUN_DIR" >&2
  exit 1
fi

RUN_DIR="$(cd "$RUN_DIR" && pwd)"
if [[ -f "$RUN_DIR/dashboard.pid" ]]; then
  old_pid="$(cat "$RUN_DIR/dashboard.pid" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "dashboard already running pid=$old_pid · http://${DASHBOARD_HOST}:${DASHBOARD_PORT}/"
    exit 0
  fi
fi

LOG_FILE="${DAILY_MOBILITY_LOG_FILE:-$RUN_DIR/output.log}"
cd "$ROOT"
nohup uv run python "$EXP/tools/serve_live_dashboard.py" \
  --run-dir "$RUN_DIR" \
  --log-file "$LOG_FILE" \
  --agent-id "$DASHBOARD_AGENT_ID" \
  --host "$DASHBOARD_HOST" \
  --port "$DASHBOARD_PORT" \
  > "$RUN_DIR/dashboard.log" 2>&1 &
echo $! > "$RUN_DIR/dashboard.pid"
echo "dashboard pid=$(cat "$RUN_DIR/dashboard.pid") · http://${DASHBOARD_HOST}:${DASHBOARD_PORT}/ · run-dir=$RUN_DIR"
