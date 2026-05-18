#!/usr/bin/env bash
# stop-hook.sh — Handle Claude Code Stop/StopFailure events
# Called by Claude Code hooks with JSON on stdin

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SESSIONS_FILE="$PROJECT_DIR/.zac/sessions.json"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}"
LOG_DIR="$PROJECT_DIR/.omc/logs"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/stop-hook.log"

# Read stdin JSON from Claude Code
INPUT=$(cat)

# Extract fields
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
HOOK_EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // "Stop"')

if [ -z "$SESSION_ID" ]; then
  echo "$(date -Iseconds) ERROR: No session_id in hook input" >> "$LOG_FILE"
  exit 0
fi

# Check state file exists
if [ ! -f "$SESSIONS_FILE" ]; then
  echo "$(date -Iseconds) No sessions.json found, skipping" >> "$LOG_FILE"
  exit 0
fi

# Find matching session by prefix (short_id is 8 hex chars, full session_id is UUID)
SHORT_ID=$(jq -r --arg full "$SESSION_ID" '
  .sessions | keys[] | select($full | startswith(.))
' "$SESSIONS_FILE" | head -1)

if [ -z "$SHORT_ID" ]; then
  # Not a tracked session — ignore silently
  exit 0
fi

# Update full_session_id for debugging
jq --arg short "$SHORT_ID" --arg full "$SESSION_ID" \
   '.sessions[$short].full_session_id = $full' \
   "$SESSIONS_FILE" > "$SESSIONS_FILE.tmp" && mv "$SESSIONS_FILE.tmp" "$SESSIONS_FILE"

TASK_TYPE=$(jq -r ".sessions[\"$SHORT_ID\"].task_type" "$SESSIONS_FILE")

echo "$(date -Iseconds) $HOOK_EVENT: session=$SHORT_ID task=$TASK_TYPE" >> "$LOG_FILE"

# Handle StopFailure → retry current phase
if [ "$HOOK_EVENT" = "StopFailure" ]; then
  RETRY_COUNT=$(jq -r ".sessions[\"$SHORT_ID\"].retry_count" "$SESSIONS_FILE")
  if [ "$RETRY_COUNT" -lt 3 ]; then
    echo "$(date -Iseconds) Retrying $TASK_TYPE (attempt $((RETRY_COUNT + 1))/3)" >> "$LOG_FILE"
    "$PLUGIN_ROOT/scripts/start-dev.sh" --phase "$TASK_TYPE" --retry
  else
    echo "$(date -Iseconds) FAILED: $TASK_TYPE exceeded 3 retries, stopping workflow" >> "$LOG_FILE"
  fi
  exit 0
fi

# Normal Stop → state machine transition
case "$TASK_TYPE" in
  scaffold)
    echo "$(date -Iseconds) Transition: scaffold → autopilot" >> "$LOG_FILE"
    "$PLUGIN_ROOT/scripts/start-dev.sh" --phase autopilot
    ;;
  autopilot)
    echo "$(date -Iseconds) Transition: autopilot → run" >> "$LOG_FILE"
    "$PLUGIN_ROOT/scripts/start-dev.sh" --phase run
    ;;
  run)
    # Decision point: check if more F-Ns remain
    DECISION=$(claude --dangerously-skip-permissions -p "$(cat <<'PROMPT'
你是工作流调度器。读取以下文件判断开发状态：

1. docs/superpowers/state.md — 当前迭代信息
2. docs/superpowers/plans/*.md — 功能树和进度
3. docs/superpowers/items/*.md — 各功能点详细状态

判断规则（和 dev-loop Step 2 一致）：
- 扫描 items 文档，找第一个 **状态:** 待开始 的功能点
- 如果找到 → 输出 CONTINUE: <功能点名称>
- 如果没有待开始的功能点 → 输出 SUMMARIZE

只输出一行，格式严格为 CONTINUE: <名称> 或 SUMMARIZE
PROMPT
)")
    if echo "$DECISION" | grep -q "^SUMMARIZE"; then
      echo "$(date -Iseconds) Transition: run → summarize (no more F-Ns)" >> "$LOG_FILE"
      "$PLUGIN_ROOT/scripts/start-dev.sh" --phase summarize
    else
      FN_NAME=$(echo "$DECISION" | sed 's/^CONTINUE: //')
      echo "$(date -Iseconds) Transition: run → autopilot (next F-N: $FN_NAME)" >> "$LOG_FILE"
      "$PLUGIN_ROOT/scripts/start-dev.sh" --phase autopilot
    fi
    ;;
  summarize)
    echo "$(date -Iseconds) Workflow complete" >> "$LOG_FILE"
    ;;
  *)
    echo "$(date -Iseconds) Unknown task type: $TASK_TYPE" >> "$LOG_FILE"
    ;;
esac
