#!/usr/bin/env bash
# start-dev.sh — Launch a dev-flow phase as a background claude session
# Usage: start-dev.sh [--phase scaffold|autopilot|run|summarize] [--retry]

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SESSIONS_FILE="$PROJECT_DIR/.zac/sessions.json"

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
[ -z "$PHASE" ] && PHASE="scaffold"

# Validate phase
case "$PHASE" in
  scaffold|autopilot|run|summarize) ;;
  *) echo "ERROR: Unknown phase '$PHASE'"; exit 1 ;;
esac

# Ensure state file exists
mkdir -p "$(dirname "$SESSIONS_FILE")"
if [ ! -f "$SESSIONS_FILE" ]; then
  echo '{"workflow":{"current_phase":"","started_at":""},"sessions":{}}' > "$SESSIONS_FILE"
fi

# Build the skill prompt
if [ -n "$TARGET" ]; then
  PROMPT="/$PHASE $TARGET"
else
  PROMPT="/$PHASE"
fi

# Launch background session with ZAC_BG=1 to skip interactive prompts
OUTPUT=$(ZAC_BG=1 ZAC_PROJECT_DIR="$PROJECT_DIR" claude --permission-mode bypassPermissions --bg "$PROMPT" 2>&1)
SHORT_ID=$(echo "$OUTPUT" | grep -oP '[a-f0-9]{8}' | head -1)

if [ -z "$SHORT_ID" ]; then
  echo "ERROR: Failed to capture session ID from claude --bg"
  echo "$OUTPUT"
  exit 1
fi

# Calculate retry count
NOW=$(date -Iseconds)
if [ "$RETRY" = true ]; then
  # Find the previous session with the same task_type and inherit its retry_count + 1
  PREV_RETRY=$(jq -r "[.sessions | to_entries[] | select(.value.task_type == \"$PHASE\")] | .[-1].value.retry_count // 0" "$SESSIONS_FILE" 2>/dev/null || echo 0)
  RETRY_COUNT=$((PREV_RETRY + 1))
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

echo "Started $PHASE session: $SHORT_ID (retry: $RETRY_COUNT)"
