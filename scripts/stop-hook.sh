#!/usr/bin/env bash
# stop-hook.sh — Handle Claude Code Stop/StopFailure events
# Called by Claude Code hooks with JSON on stdin

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SESSIONS_FILE="$PROJECT_DIR/.zac/sessions.json"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}"
LOG_DIR="$PROJECT_DIR/.zac/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/stop-hook.log"

log() { echo "$(date -Iseconds) $*" >> "$LOG_FILE"; }

log "=== stop-hook.sh invoked ==="
log "PROJECT_DIR=$PROJECT_DIR"
log "CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR:-<not set>}"

# Read stdin JSON from Claude Code
INPUT=$(cat)
log "stdin input: $INPUT"

# Extract fields
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
HOOK_EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // "Stop"')

log "parsed: session_id=$SESSION_ID hook_event=$HOOK_EVENT"

if [ -z "$SESSION_ID" ]; then
  log "ERROR: No session_id in hook input"
  exit 0
fi

# Check state file exists
if [ ! -f "$SESSIONS_FILE" ]; then
  log "No sessions.json found at $SESSIONS_FILE, skipping"
  exit 0
fi

log "sessions.json content: $(cat "$SESSIONS_FILE")"

# Find matching session by prefix (short_id is 8 hex chars, full session_id is UUID)
SHORT_ID=$(jq -r --arg full "$SESSION_ID" '
  .sessions | keys[] | select($full | startswith(.))
' "$SESSIONS_FILE" | head -1)

if [ -z "$SHORT_ID" ]; then
  log "No matching session found for session_id=$SESSION_ID, ignoring"
  exit 0
fi

log "matched session: short_id=$SHORT_ID"

# Update full_session_id for debugging
jq --arg short "$SHORT_ID" --arg full "$SESSION_ID" \
   '.sessions[$short].full_session_id = $full' \
   "$SESSIONS_FILE" > "$SESSIONS_FILE.tmp" && mv "$SESSIONS_FILE.tmp" "$SESSIONS_FILE"

TASK_TYPE=$(jq -r ".sessions[\"$SHORT_ID\"].task_type" "$SESSIONS_FILE")
log "task_type=$TASK_TYPE"

# Handle StopFailure → retry current phase
if [ "$HOOK_EVENT" = "StopFailure" ]; then
  RETRY_COUNT=$(jq -r ".sessions[\"$SHORT_ID\"].retry_count" "$SESSIONS_FILE")
  log "StopFailure: retry_count=$RETRY_COUNT"
  if [ "$RETRY_COUNT" -lt 3 ]; then
    log "Retrying $TASK_TYPE (attempt $((RETRY_COUNT + 1))/3)"
    "$PLUGIN_ROOT/scripts/start-dev.sh" --phase "$TASK_TYPE" --retry
  else
    log "FAILED: $TASK_TYPE exceeded 3 retries, stopping workflow"
  fi
  exit 0
fi

# Helper: query current F-N from docs
query_next_fn() {
  log "query_next_fn: asking claude to find next F-N"
  DECISION=$(claude --permission-mode bypassPermissions -p "$(cat <<'PROMPT'
你是工作流调度器。读取以下文件判断开发状态：

1. docs/superpowers/state.md — 当前迭代信息
2. docs/superpowers/items/*.md — 各功能点详细状态

判断规则：
- 扫描 items 文档，找第一个 **状态:** 待开始 的功能点
- 如果找到 → 输出 CONTINUE: <功能点名称>
- 如果没有待开始的功能点 → 输出 SUMMARIZE

只输出一行，格式严格为 CONTINUE: <名称> 或 SUMMARIZE
PROMPT
)")
  log "query_next_fn result: $DECISION"
  echo "$DECISION"
}

# Normal Stop → state machine transition
case "$TASK_TYPE" in
  autopilot)
    FN_NAME=$(jq -r ".sessions[\"$SHORT_ID\"].target // \"\"" "$SESSIONS_FILE")
    log "Transition: autopilot → run (F-N: $FN_NAME)"
    "$PLUGIN_ROOT/scripts/start-dev.sh" --phase run --target "$FN_NAME"
    ;;
  run)
    DECISION=$(query_next_fn)
    if echo "$DECISION" | grep -q "^SUMMARIZE"; then
      log "Transition: run → summarize (no more F-Ns)"
      "$PLUGIN_ROOT/scripts/start-dev.sh" --phase summarize
    else
      FN_NAME=$(echo "$DECISION" | sed 's/^CONTINUE: //')
      log "Transition: run → autopilot (next F-N: $FN_NAME)"
      "$PLUGIN_ROOT/scripts/start-dev.sh" --phase autopilot --target "$FN_NAME"
    fi
    ;;
  summarize)
    log "Workflow complete"
    ;;
  *)
    log "Unknown task type: $TASK_TYPE"
    ;;
esac
