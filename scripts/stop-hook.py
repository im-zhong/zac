#!/usr/bin/env python3
"""stop-hook.py — Handle Claude Code Stop/StopFailure events.

Called by Claude Code hooks with JSON on stdin. Implements the workflow
state machine: autopilot → run → (autopilot | summarize) → done.

Environment variables:
  CLAUDE_PROJECT_DIR  — user's project directory (e.g. /home/zhangzhong/src/zac).
                        .zac/logs/, .zac/sessions.json live here.
  CLAUDE_PLUGIN_ROOT  — plugin install directory, used to locate start-dev.py.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SESSIONS_KEY = "sessions"


def log(msg: str) -> None:
    """Append timestamped message to .zac/logs/stop-hook.log."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir:
        return
    log_dir = Path(project_dir) / ".zac" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().isoformat()
    with open(log_dir / "stop-hook.log", "a") as f:
        f.write(f"{ts} {msg}\n")


def read_sessions(project_dir: str) -> dict | None:
    """Read sessions.json; return None if missing or corrupt."""
    path = Path(project_dir) / ".zac" / "sessions.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_sessions(project_dir: str, data: dict) -> None:
    """Atomic write via tmp+replace to avoid partial writes."""
    path = Path(project_dir) / ".zac" / "sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def find_session(data: dict, session_id: str) -> tuple[str | None, dict | None]:
    """Match a hook's session_id (full UUID) to a sessions.json entry.

    Claude Code sends the full UUID (e.g. f1804cc4-8a07-46a6-87f8-1d691dd06206),
    but sessions.json keys are the 8-char short ID from `claude --bg` output
    (e.g. f1804cc4). We match by taking the first 8 chars of the UUID.
    """
    sessions = data.get(SESSIONS_KEY, {})
    prefix = session_id[:8] if len(session_id) >= 8 else session_id
    if prefix in sessions:
        return prefix, sessions[prefix]
    return None, None


def query_next_fn(project_dir: str) -> str:
    """Ask claude to determine the next F-N item from docs.

    Returns "CONTINUE: <name>" if a pending F-N exists, "SUMMARIZE" otherwise.
    On any error, defaults to "SUMMARIZE" to avoid infinite loops.
    """
    log("query_next_fn: asking claude to find next F-N")
    prompt = """你是工作流调度器。读取以下文件判断开发状态：

1. docs/superpowers/state.md — 当前迭代信息
2. docs/superpowers/items/*.md — 各功能点详细状态

判断规则：
- 扫描 items 文档，找第一个 **状态:** 待开始 的功能点
- 如果找到 → 输出 CONTINUE: <功能点名称>
- 如果没有待开始的功能点 → 输出 SUMMARIZE

只输出一行，格式严格为 CONTINUE: <名称> 或 SUMMARIZE"""
    try:
        result = subprocess.run(
            ["claude", "--permission-mode", "bypassPermissions", "-p", prompt],
            capture_output=True, text=True, cwd=project_dir, timeout=120,
        )
        decision = result.stdout.strip()
        log(f"query_next_fn result: {decision}")
        return decision
    except Exception as e:
        log(f"query_next_fn error: {e}")
        return "SUMMARIZE"


def start_next_phase(project_dir: str, phase: str, target: str = "") -> None:
    """Launch the next workflow phase via start-dev.py as a foreground subprocess."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", str(Path(__file__).resolve().parent.parent))
    script = Path(plugin_root) / "scripts" / "start-dev.py"
    args = [sys.executable, str(script), "--phase", phase]
    if target:
        args += ["--target", target]
    log(f"Launching next phase: {' '.join(args)}")
    try:
        subprocess.run(args, cwd=project_dir, check=False)
    except Exception as e:
        log(f"Failed to launch next phase: {e}")


def handle_stop_failure(project_dir: str, entry: dict) -> None:
    """StopFailure: retry the same phase up to 3 times, then give up."""
    task_type = entry.get("task_type", "")
    retry_count = entry.get("retry_count", 0)
    log(f"StopFailure: retry_count={retry_count}")
    if retry_count < 3:
        log(f"Retrying {task_type} (attempt {retry_count + 1}/3)")
        start_next_phase(project_dir, task_type, entry.get("target", ""))
    else:
        log(f"FAILED: {task_type} exceeded 3 retries, stopping workflow")


def handle_normal_stop(project_dir: str, entry: dict) -> None:
    """Normal Stop: advance the workflow state machine.

    autopilot → run (same target)
    run       → autopilot (next F-N) or summarize (no more F-Ns)
    summarize → done (workflow complete)
    """
    task_type = entry.get("task_type", "")
    target = entry.get("target", "")

    if task_type == "autopilot":
        log(f"Transition: autopilot → run (F-N: {target})")
        start_next_phase(project_dir, "run", target)

    elif task_type == "run":
        decision = query_next_fn(project_dir)
        if decision.startswith("CONTINUE:"):
            fn_name = decision[len("CONTINUE:"):].strip()
            log(f"Transition: run → autopilot (next F-N: {fn_name})")
            start_next_phase(project_dir, "autopilot", fn_name)
        else:
            if not decision.startswith("SUMMARIZE"):
                log(f"Unexpected query_next_fn result: {decision}, defaulting to summarize")
            log("Transition: run → summarize (no more F-Ns)")
            start_next_phase(project_dir, "summarize")

    elif task_type == "summarize":
        log("Workflow complete")

    else:
        log(f"Unknown task type: {task_type}")


def main() -> None:
    """Entry point: read hook JSON from stdin, dispatch to handler.

    Flow: parse stdin → find session → guard re-entrancy → handle event.
    """
    log("=== stop-hook.py invoked ===")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir:
        print("stop-hook.py: CLAUDE_PROJECT_DIR not set, not running under Claude Code hooks", file=sys.stderr)
        return
    log(f"PROJECT_DIR={project_dir}")

    # Parse hook input from Claude Code (JSON on stdin)
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        log(f"ERROR: Invalid JSON on stdin: {e}")
        return

    log(f"stdin input: {json.dumps(input_data, ensure_ascii=False)}")

    session_id = input_data.get("session_id", "")
    hook_event = input_data.get("hook_event_name", "Stop")
    stop_hook_active = input_data.get("stop_hook_active", False)

    log(f"parsed: session_id={session_id} hook_event={hook_event} stop_hook_active={stop_hook_active}")

    if not session_id:
        log("ERROR: No session_id in hook input")
        return

    # Load sessions state — if missing, this hook isn't for our workflow
    data = read_sessions(project_dir)
    if data is None:
        log("No sessions.json found, skipping")
        return

    log(f"sessions.json content: {json.dumps(data, ensure_ascii=False)}")

    # Find the session that matches the hook's session_id
    short_id, entry = find_session(data, session_id)
    if short_id is None:
        log(f"No matching session found for session_id={session_id}, ignoring")
        return

    log(f"matched session: short_id={short_id}")

    # Re-entrancy guard: if a previous stop hook already caused Claude to
    # continue, stop_hook_active is True — skip to avoid double-advancing
    if stop_hook_active:
        log("stop_hook_active=True, skipping transition to avoid double-advance")
        return

    if hook_event == "StopFailure":
        handle_stop_failure(project_dir, entry)
    else:
        handle_normal_stop(project_dir, entry)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {e}")
    # Always exit 0 — this hook is a side-effect only (spawns new claude
    # instances) and must never influence the calling session's behavior.
