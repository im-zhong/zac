#!/usr/bin/env bash
# start-dev.sh — Launch a dev-flow phase as a background claude session
# Usage: start-dev.sh [--phase scaffold|autopilot|run|summarize] [--target <F-N name>] [--retry]

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SESSIONS_FILE="$PROJECT_DIR/.zac/sessions.json"
LOG_DIR="$PROJECT_DIR/.zac/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/start-dev.log"

log() { echo "$(date -Iseconds) $*" >> "$LOG_FILE"; }

log "=== start-dev.sh invoked ==="
log "PROJECT_DIR=$PROJECT_DIR"
log "CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR:-<not set>}"
log "args: $*"

# Parse arguments
PHASE=""
TARGET=""
RETRY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase=*) PHASE="${1#--phase=}" ;;
    --phase)   PHASE="$2"; shift ;;
    --target=*) TARGET="${1#--target=}" ;;
    --target)   TARGET="$2"; shift ;;
    --retry)   RETRY=true ;;
    *)         echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

# Default phase
[ -z "$PHASE" ] && PHASE="autopilot"

# Validate phase
case "$PHASE" in
  autopilot|run|summarize) ;;
  *) echo "ERROR: Unknown phase '$PHASE'"; log "ERROR: Unknown phase '$PHASE'"; exit 1 ;;
esac

log "parsed: phase=$PHASE target=${TARGET:-<none>} retry=$RETRY"

# Ensure state file exists
mkdir -p "$(dirname "$SESSIONS_FILE")"
if [ ! -f "$SESSIONS_FILE" ]; then
  echo '{"workflow":{"current_phase":"","started_at":""},"sessions":{}}' > "$SESSIONS_FILE"
  log "created sessions.json at $SESSIONS_FILE"
else
  log "sessions.json already exists at $SESSIONS_FILE"
fi

# Build the prompt: skill name + target + background mode instructions
PROMPT="/$PHASE"
if [ -n "$TARGET" ]; then
  PROMPT="$PROMPT 实现 $TARGET"
else
  PROMPT="$PROMPT 读取 docs/superpowers/state.md 和 docs/superpowers/items/*.md，找到第一个状态为待开始的功能点并实现它"
fi
PROMPT="$PROMPT

你在后台模式运行。禁止使用 AskUserQuestion 工具。所有需要用户确认的决策，采用推荐默认值并继续执行。"

log "prompt: $PROMPT"

# Launch background session
log "launching: claude --permission-mode bypassPermissions --bg"
OUTPUT=$(claude --permission-mode bypassPermissions --bg "$PROMPT" 2>&1)
log "claude --bg output: $OUTPUT"

SHORT_ID=$(echo "$OUTPUT" | grep -oP '[a-f0-9]{8}' | head -1)

if [ -z "$SHORT_ID" ]; then
  log "ERROR: Failed to capture session ID from claude --bg"
  echo "ERROR: Failed to capture session ID from claude --bg"
  echo "$OUTPUT"
  exit 1
fi

log "captured session short_id: $SHORT_ID"

# Write current session id for reference
echo "$SHORT_ID" > "$PROJECT_DIR/.zac/current-session"

# Calculate retry count
NOW=$(date -Iseconds)
if [ "$RETRY" = true ]; then
  PREV_RETRY=$(jq -r "[.sessions | to_entries[] | select(.value.task_type == \"$PHASE\")] | .[-1].value.retry_count // 0" "$SESSIONS_FILE" 2>/dev/null || echo 0)
  RETRY_COUNT=$((PREV_RETRY + 1))
  log "retry mode: previous retry_count=$PREV_RETRY, new=$RETRY_COUNT"
else
  RETRY_COUNT=0
fi

# Record to sessions.json (atomic write via tmp file)
jq --arg short "$SHORT_ID" \
   --arg phase "$PHASE" \
   --arg now "$NOW" \
   --argjson retry "$RETRY_COUNT" \
   --arg target "$TARGET" \
   '.workflow.current_phase = $phase |
    .workflow.started_at = $now |
    .sessions[$short] = {
      task_type: $phase,
      started_at: $now,
      retry_count: $retry,
      target: $target,
      full_session_id: ""
    }' \
   "$SESSIONS_FILE" > "$SESSIONS_FILE.tmp" && mv "$SESSIONS_FILE.tmp" "$SESSIONS_FILE"

log "sessions.json updated: short_id=$SHORT_ID phase=$PHASE target=${TARGET:-<none>} retry=$RETRY_COUNT"
echo "Started $PHASE session: $SHORT_ID (retry: $RETRY_COUNT)"
