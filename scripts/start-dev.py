#!/usr/bin/env python3
"""start-dev.py — Launch a dev-flow phase as a background claude session.

Usage:
    start-dev.py [--phase autopilot|run|summarize] [--target <F-N name>] [--retry]

Environment variables:
  CLAUDE_PROJECT_DIR  — user's project directory (e.g. /home/zhangzhong/src/zac).
                        .zac/logs/, .zac/sessions.json live here.
                        Falls back to os.getcwd() when called from skills
                        (only hooks guarantee this variable is set).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def log(msg: str) -> None:
    """Append timestamped message to .zac/logs/start-dev.log."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    log_dir = Path(project_dir) / ".zac" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().isoformat()
    with open(log_dir / "start-dev.log", "a") as f:
        f.write(f"{ts} {msg}\n")
    log_dir = Path(project_dir) / ".zac" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().isoformat()
    with open(log_dir / "start-dev.log", "a") as f:
        f.write(f"{ts} {msg}\n")


def read_sessions(project_dir: str) -> dict:
    """Read sessions.json; return empty structure if missing or corrupt."""
    path = Path(project_dir) / ".zac" / "sessions.json"
    if path.exists() and path.stat().st_size > 0:
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"workflow": {"current_phase": "", "started_at": ""}, "sessions": {}}


def write_sessions(project_dir: str, data: dict) -> None:
    """Atomic write via tmp+replace to avoid partial writes."""
    path = Path(project_dir) / ".zac" / "sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def extract_session_id(output: str) -> str | None:
    """Extract the 8-char session short ID from `claude --bg` output.

    Matches either "backgrounded · <hex8>" or "claude attach <hex8>".
    """
    match = re.search(r"backgrounded\s*[·•]\s*([a-f0-9]{8})\b", output)
    if match:
        return match.group(1)
    match = re.search(r"claude\s+attach\s+([a-f0-9]{8})\b", output)
    if match:
        return match.group(1)
    return None


def build_prompt(phase: str, target: str) -> str:
    """Build the prompt sent to the background claude session."""
    prompt = f"/{phase}"
    if target:
        prompt += f" 实现 {target}"
    else:
        prompt += " 读取 docs/superpowers/state.md 和 docs/superpowers/items/*.md，找到第一个状态为待开始的功能点并实现它"

    prompt += """

你在后台模式运行。禁止使用 AskUserQuestion 工具。所有需要用户确认的决策，采用推荐默认值并继续执行。
任务完成后，将当前 worktree 的改动合并回 main 分支并删除 worktree：
1. git add 并 commit 所有改动
2. git checkout main && git merge <当前分支>
3. 退出 worktree 并删除它"""
    return prompt


def launch_background_session(project_dir: str, prompt: str) -> str | None:
    """Launch claude --bg and return the short session ID, or None on failure.

    Returns None instead of calling sys.exit(1) because this script is invoked
    as a Claude Code hook side-effect — a non-zero exit code would influence the
    calling Claude session's behavior, which we must never do.
    """
    log("launching: claude --permission-mode bypassPermissions --bg")
    result = subprocess.run(
        ["claude", "--permission-mode", "bypassPermissions", "--bg", prompt],
        capture_output=True, text=True, cwd=project_dir,
    )
    output = result.stdout + result.stderr
    log(f"claude --bg output: {output}")

    short_id = extract_session_id(output)
    if not short_id:
        log("ERROR: Failed to capture session ID from claude --bg")
        print("ERROR: Failed to capture session ID from claude --bg", file=sys.stderr)
        print(output, file=sys.stderr)
        return None

    log(f"captured session short_id: {short_id}")
    return short_id


def calc_retry_count(data: dict, phase: str, is_retry: bool) -> int:
    """Calculate retry count: find the max existing retry_count for this phase and increment."""
    if not is_retry:
        return 0
    prev = 0
    for entry in data.get("sessions", {}).values():
        if entry.get("task_type") == phase:
            prev = max(prev, entry.get("retry_count", 0))
    log(f"retry mode: previous retry_count={prev}, new={prev + 1}")
    return prev + 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a dev-flow phase as a background claude session")
    parser.add_argument("--phase", choices=["autopilot", "run", "summarize"], default="autopilot")
    parser.add_argument("--target", default="")
    parser.add_argument("--retry", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Entry point: parse args → build prompt → launch session → record state."""
    log("=== start-dev.py invoked ===")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    log(f"PROJECT_DIR={project_dir}")

    args = parse_args()
    phase, target, retry = args.phase, args.target, args.retry
    log(f"parsed: phase={phase} target={target or '<none>'} retry={retry}")

    data = read_sessions(project_dir)
    log(f"sessions.json content: {json.dumps(data, ensure_ascii=False)}")

    prompt = build_prompt(phase, target)
    log(f"prompt: {prompt}")

    short_id = launch_background_session(project_dir, prompt)
    if not short_id:
        return

    now = datetime.now().astimezone().isoformat()
    retry_count = calc_retry_count(data, phase, retry)

    data["workflow"]["current_phase"] = phase
    data["workflow"]["started_at"] = now
    # Record session in sessions.json so stop-hook.py can match and transition it
    data["sessions"][short_id] = {
        "task_type": phase,
        "started_at": now,
        "retry_count": retry_count,
        "target": target,
    }
    write_sessions(project_dir, data)
    log(f"sessions.json after write: {json.dumps(data, ensure_ascii=False)}")

    print(f"Started {phase} session: {short_id} (retry: {retry_count})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {e}")
    # Always exit 0 — this script is a side-effect launcher and must never
    # influence the calling process's behavior.
