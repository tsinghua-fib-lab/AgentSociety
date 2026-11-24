#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
EXP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${DAILY_MOBILITY_RUN_DIR:-$EXP/tmp/live/run}"
OUT_DIR="${DAILY_MOBILITY_OUT_DIR:-$EXP/tmp/live/plots}"
LOG_FILE="${DAILY_MOBILITY_LOG_FILE:-$RUN_DIR/output.log}"
PRESET="${DAILY_MOBILITY_PRESET:-benchmark}"
NUM_AGENTS="${DAILY_MOBILITY_NUM_AGENTS:-2}"
TICK_SEC="${DAILY_MOBILITY_TICK_SEC:-1800}"
MAX_TOOL_ROUNDS="${DAILY_MOBILITY_MAX_TOOL_ROUNDS:-6}"
RUN_TESTS="${DAILY_MOBILITY_RUN_TESTS:-1}"
CLEAN="${DAILY_MOBILITY_CLEAN:-1}"
PLOT_INTERVAL="${DAILY_MOBILITY_PLOT_INTERVAL:-5}"
DASHBOARD_PORT="${DAILY_MOBILITY_DASHBOARD_PORT:-8765}"
DASHBOARD_HOST="${DAILY_MOBILITY_DASHBOARD_HOST:-127.0.0.1}"
ENABLE_DASHBOARD="${DAILY_MOBILITY_ENABLE_DASHBOARD:-1}"
KEEP_DASHBOARD="${DAILY_MOBILITY_KEEP_DASHBOARD:-1}"
DASHBOARD_AGENT_ID="${DAILY_MOBILITY_DASHBOARD_AGENT_ID:-1}"
EXPERIMENT_ID="${DAILY_MOBILITY_EXPERIMENT_ID:-daily_mobility_live}"
FAIL_ON_GATE="${DAILY_MOBILITY_FAIL_ON_GATE:-1}"

cd "$ROOT"

echo "[daily-mobility] root: $ROOT"
echo "[daily-mobility] preset=$PRESET agents=$NUM_AGENTS tick=${TICK_SEC}s"
echo "[daily-mobility] run dir: $RUN_DIR"
echo "[daily-mobility] plots: $OUT_DIR"
echo "[daily-mobility] dashboard: http://${DASHBOARD_HOST}:${DASHBOARD_PORT}/ (下拉切换 Agent，默认 ${DASHBOARD_AGENT_ID})"

# A fresh run must never discard an earlier replay or a caller's files.
if [[ "$CLEAN" == "1" ]]; then
  shopt -s nullglob dotglob
  for dir in "$RUN_DIR" "$OUT_DIR"; do
    entries=("$dir"/*)
    if (( ${#entries[@]} )); then
      echo "Output directory contains files: $dir. Choose empty run and plot directories." >&2
      exit 1
    fi
  done
  shopt -u nullglob dotglob
fi

if [[ "$RUN_TESTS" == "1" ]]; then
  uv run pytest -c packages/agentsociety2/pyproject.toml \
    "$EXP/tests" \
    packages/agentsociety2/tests/test_mobility_regressions.py
fi

mkdir -p "$RUN_DIR" "$OUT_DIR"

DAILY_MOBILITY_INIT_DIR="$RUN_DIR" \
DAILY_MOBILITY_RUN_DIR="$RUN_DIR" \
DAILY_MOBILITY_PRESET="$PRESET" \
DAILY_MOBILITY_NUM_AGENTS="$NUM_AGENTS" \
DAILY_MOBILITY_TICK_SEC="$TICK_SEC" \
DAILY_MOBILITY_MAX_TOOL_ROUNDS="$MAX_TOOL_ROUNDS" \
  uv run python "$EXP/init/config_params.py"

uv run python "$EXP/tools/plot_live_daily_mobility.py" \
  --run-dir "$RUN_DIR" \
  --out-dir "$OUT_DIR" \
  --log-file "$LOG_FILE" \
  --watch \
  --interval "$PLOT_INTERVAL" &
PLOT_PID=$!

DASH_PID=""
if [[ "$ENABLE_DASHBOARD" == "1" ]]; then
  uv run python "$EXP/tools/serve_live_dashboard.py" \
    --run-dir "$RUN_DIR" \
    --log-file "$LOG_FILE" \
    --agent-id "$DASHBOARD_AGENT_ID" \
    --host "$DASHBOARD_HOST" \
    --port "$DASHBOARD_PORT" &
  DASH_PID=$!
  echo "$DASH_PID" > "$RUN_DIR/dashboard.pid"
  disown "$DASH_PID" 2>/dev/null || true
fi

cleanup() {
  kill "$PLOT_PID" 2>/dev/null || true
  if [[ "$KEEP_DASHBOARD" != "1" ]] && [[ -n "$DASH_PID" ]]; then
    kill "$DASH_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

uv run python -m agentsociety2.society.cli \
  --config "$RUN_DIR/init_config.json" \
  --steps "$RUN_DIR/steps.yaml" \
  --run-dir "$RUN_DIR" \
  --experiment-id "$EXPERIMENT_ID" \
  --log-level INFO \
  --log-file "$LOG_FILE"

uv run python "$EXP/tools/plot_live_daily_mobility.py" \
  --run-dir "$RUN_DIR" \
  --out-dir "$OUT_DIR" \
  --log-file "$LOG_FILE"

GATE_ARGS=()
if [[ "$FAIL_ON_GATE" == "1" ]]; then
  GATE_ARGS+=(--fail-on-gate)
fi

uv run python "$EXP/daily_mobility/tools/check_daily_mobility_run.py" \
  --run-dir "$RUN_DIR" \
  --out "$OUT_DIR/diagnostics.json" \
  "${GATE_ARGS[@]}"

if [[ -f "$RUN_DIR/mobility_metrics_export.json" ]]; then
  uv run python "$EXP/tools/eval_metrics.py" --run-dir "$RUN_DIR" --gt-dir "$EXP/data/groundtruth" --config "$RUN_DIR/init_config.json"
fi

echo "[daily-mobility] done"
echo "[daily-mobility] open plots in: $OUT_DIR"
if [[ "$ENABLE_DASHBOARD" == "1" ]] && [[ "$KEEP_DASHBOARD" == "1" ]] && [[ -n "$DASH_PID" ]]; then
  echo "[daily-mobility] web dashboard STILL RUNNING (pid=$DASH_PID): http://${DASHBOARD_HOST}:${DASHBOARD_PORT}/"
  echo "[daily-mobility] re-attach: bash $EXP/serve_dashboard.sh $RUN_DIR"
else
  echo "[daily-mobility] web dashboard: http://${DASHBOARD_HOST}:${DASHBOARD_PORT}/"
fi
echo "[daily-mobility] log file: $LOG_FILE"
