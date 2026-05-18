"""Tests for stop-hook.py — all session states and transition paths.

Real session_id format: UUID v4 (e.g. f1804cc4-8a07-46a6-87f8-1d691dd06206)
claude --bg short_id: first 8 hex chars of the UUID (e.g. f1804cc4)
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "stop-hook.py"
_spec = importlib.util.spec_from_file_location("stop_hook", _SCRIPT)
stop_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stop_hook)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION_AUTOPILOT = {
    "uuid": "f1804cc4-8a07-46a6-87f8-1d691dd06206",
    "short_id": "f1804cc4",
}
SESSION_RUN = {
    "uuid": "30862053-a1b2-c3d4-e5f6-789012345678",
    "short_id": "30862053",
}
SESSION_SUMMARIZE = {
    "uuid": "aabb1122-3344-5566-7788-99aabbccdd00",
    "short_id": "aabb1122",
}
SESSION_ORPHAN = {
    "uuid": "deadbeef-0000-1111-2222-333344445555",
    "short_id": "deadbeef",
}


def make_hook_input(
    session_id: str = SESSION_AUTOPILOT["uuid"],
    hook_event_name: str = "Stop",
    stop_hook_active: bool = False,
    last_assistant_message: str = "Done.",
    **extra,
) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": f"/home/zhangzhong/.claude/projects/-home-zhangzhong-src-zac/{session_id}.jsonl",
        "cwd": "/home/zhangzhong/src/zac",
        "permission_mode": "bypassPermissions",
        "effort": {"level": "high"},
        "hook_event_name": hook_event_name,
        "stop_hook_active": stop_hook_active,
        "last_assistant_message": last_assistant_message,
        **extra,
    }


def make_sessions(
    short_id: str = SESSION_AUTOPILOT["short_id"],
    task_type: str = "autopilot",
    target: str = "F-01-用户认证",
    retry_count: int = 0,
    workflow_phase: str = "autopilot",
) -> dict:
    return {
        "workflow": {
            "current_phase": workflow_phase,
            "started_at": "2026-05-18T10:00:00+08:00",
        },
        "sessions": {
            short_id: {
                "task_type": task_type,
                "started_at": "2026-05-18T10:00:00+08:00",
                "retry_count": retry_count,
                "target": target,
            }
        },
    }


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / ".zac").mkdir()
    return str(tmp_path)


def write_sessions_file(project_dir: str, data: dict) -> None:
    p = Path(project_dir) / ".zac" / "sessions.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInvalidInput:
    def test_invalid_json_exits_gracefully(self, project_dir):
        with patch("sys.stdin", MagicMock(read=lambda: "not-json{{{")):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                stop_hook.main()

    def test_missing_session_id_exits_gracefully(self, project_dir):
        payload = make_hook_input(session_id="")
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                stop_hook.main()


# ---------------------------------------------------------------------------
# Sessions file missing / corrupt
# ---------------------------------------------------------------------------

class TestNoSessionsFile:
    def test_no_sessions_json_skips(self, project_dir):
        payload = make_hook_input()
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                stop_hook.main()

    def test_corrupt_sessions_json_skips(self, project_dir):
        (Path(project_dir) / ".zac" / "sessions.json").write_text("NOT JSON!!!")
        payload = make_hook_input()
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                stop_hook.main()


# ---------------------------------------------------------------------------
# Session not found
# ---------------------------------------------------------------------------

class TestSessionNotFound:
    def test_unknown_uuid_ignored(self, project_dir):
        write_sessions_file(project_dir, make_sessions())
        payload = make_hook_input(session_id=SESSION_ORPHAN["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()


# ---------------------------------------------------------------------------
# stop_hook_active=True (re-entrant guard)
# ---------------------------------------------------------------------------

class TestStopHookActive:
    @pytest.mark.parametrize("task_type", ["autopilot", "run", "summarize"])
    def test_reentrant_stop_skips_transition(self, project_dir, task_type):
        session = {
            "autopilot": SESSION_AUTOPILOT,
            "run": SESSION_RUN,
            "summarize": SESSION_SUMMARIZE,
        }[task_type]
        write_sessions_file(project_dir, make_sessions(
            short_id=session["short_id"], task_type=task_type,
        ))
        payload = make_hook_input(session_id=session["uuid"], stop_hook_active=True)
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()

    def test_stopfailure_with_stop_hook_active_still_skips(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run", retry_count=0,
        ))
        payload = make_hook_input(
            session_id=SESSION_RUN["uuid"],
            hook_event_name="StopFailure",
            stop_hook_active=True,
        )
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()


# ---------------------------------------------------------------------------
# StopFailure → retry
# ---------------------------------------------------------------------------

class TestStopFailure:
    def test_retries_run_under_limit(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run", retry_count=0,
        ))
        payload = make_hook_input(session_id=SESSION_RUN["uuid"], hook_event_name="StopFailure")
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_called_once_with(project_dir, "run", "F-01-用户认证")

    def test_retries_autopilot(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_AUTOPILOT["short_id"],
            task_type="autopilot",
            target="F-03-支付集成",
            retry_count=1,
        ))
        payload = make_hook_input(
            session_id=SESSION_AUTOPILOT["uuid"],
            hook_event_name="StopFailure",
        )
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_called_once_with(project_dir, "autopilot", "F-03-支付集成")

    def test_retries_at_count_2(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run", retry_count=2,
        ))
        payload = make_hook_input(session_id=SESSION_RUN["uuid"], hook_event_name="StopFailure")
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_called_once()

    def test_stops_at_max_retries(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run", retry_count=3,
        ))
        payload = make_hook_input(session_id=SESSION_RUN["uuid"], hook_event_name="StopFailure")
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()

    def test_does_not_query_next_fn(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run", retry_count=0,
        ))
        payload = make_hook_input(session_id=SESSION_RUN["uuid"], hook_event_name="StopFailure")
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "query_next_fn") as mock:
                    stop_hook.main()
                    mock.assert_not_called()

    def test_stopfailure_with_stop_hook_active_still_skips(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run", retry_count=0,
        ))
        payload = make_hook_input(
            session_id=SESSION_RUN["uuid"],
            hook_event_name="StopFailure",
            stop_hook_active=True,
        )
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()


# ---------------------------------------------------------------------------
# Normal Stop — autopilot → run
# ---------------------------------------------------------------------------

class TestAutopilotTransition:
    def test_autopilot_transitions_to_run(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_AUTOPILOT["short_id"],
            task_type="autopilot",
            target="F-02-数据模型",
        ))
        payload = make_hook_input(session_id=SESSION_AUTOPILOT["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_called_once_with(project_dir, "run", "F-02-数据模型")


# ---------------------------------------------------------------------------
# Normal Stop — run → (autopilot | summarize)
# ---------------------------------------------------------------------------

class TestRunTransition:
    def test_to_summarize_when_no_more_fns(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run",
        ))
        payload = make_hook_input(session_id=SESSION_RUN["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "query_next_fn", return_value="SUMMARIZE"):
                    with patch.object(stop_hook, "start_next_phase") as mock:
                        stop_hook.main()
                        mock.assert_called_once_with(project_dir, "summarize")

    def test_to_autopilot_when_next_fn_exists(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run",
        ))
        payload = make_hook_input(session_id=SESSION_RUN["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "query_next_fn", return_value="CONTINUE: F-03-支付集成"):
                    with patch.object(stop_hook, "start_next_phase") as mock:
                        stop_hook.main()
                        mock.assert_called_once_with(project_dir, "autopilot", "F-03-支付集成")

    def test_unexpected_decision_defaults_to_summarize(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_RUN["short_id"], task_type="run",
        ))
        payload = make_hook_input(session_id=SESSION_RUN["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "query_next_fn", return_value="I DON'T KNOW"):
                    with patch.object(stop_hook, "start_next_phase") as mock:
                        stop_hook.main()
                        mock.assert_called_once_with(project_dir, "summarize")


# ---------------------------------------------------------------------------
# Normal Stop — summarize → done
# ---------------------------------------------------------------------------

class TestSummarizeTransition:
    def test_summarize_ends_workflow(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_SUMMARIZE["short_id"], task_type="summarize",
        ))
        payload = make_hook_input(session_id=SESSION_SUMMARIZE["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown task_type
# ---------------------------------------------------------------------------

class TestUnknownTaskType:
    def test_unknown_task_type_no_action(self, project_dir):
        write_sessions_file(project_dir, make_sessions(
            short_id=SESSION_AUTOPILOT["short_id"], task_type="deployment",
        ))
        payload = make_hook_input(session_id=SESSION_AUTOPILOT["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()


# ---------------------------------------------------------------------------
# Session matching — UUID prefix to short_id
# ---------------------------------------------------------------------------

class TestSessionMatching:
    def test_uuid_prefix_matches_short_id(self, project_dir):
        write_sessions_file(project_dir, make_sessions())
        payload = make_hook_input()
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_called_once()

    def test_no_match_returns_none(self, project_dir):
        write_sessions_file(project_dir, make_sessions())
        payload = make_hook_input(session_id=SESSION_ORPHAN["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "start_next_phase") as mock:
                    stop_hook.main()
                    mock.assert_not_called()


# ---------------------------------------------------------------------------
# Multiple sessions
# ---------------------------------------------------------------------------

class TestMultipleSessions:
    def test_correct_uuid_matched_among_many(self, project_dir):
        sessions = {
            "workflow": {"current_phase": "run", "started_at": "2026-05-18T10:00:00"},
            "sessions": {
                SESSION_AUTOPILOT["short_id"]: {
                    "task_type": "autopilot",
                    "started_at": "2026-05-18T09:00:00",
                    "retry_count": 0,
                    "target": "F-01",
                },
                SESSION_RUN["short_id"]: {
                    "task_type": "run",
                    "started_at": "2026-05-18T10:00:00",
                    "retry_count": 0,
                    "target": "F-02",
                },
                SESSION_SUMMARIZE["short_id"]: {
                    "task_type": "summarize",
                    "started_at": "2026-05-18T11:00:00",
                    "retry_count": 0,
                    "target": "",
                },
            },
        }
        write_sessions_file(project_dir, sessions)
        payload = make_hook_input(session_id=SESSION_RUN["uuid"])
        with patch("sys.stdin", MagicMock(read=lambda: json.dumps(payload))):
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": project_dir}):
                with patch.object(stop_hook, "query_next_fn", return_value="SUMMARIZE"):
                    with patch.object(stop_hook, "start_next_phase") as mock:
                        stop_hook.main()
                        mock.assert_called_once_with(project_dir, "summarize")


# ---------------------------------------------------------------------------
# find_session unit tests
# ---------------------------------------------------------------------------

class TestFindSession:
    def test_uuid_prefix_matches_key(self):
        data = make_sessions(short_id=SESSION_AUTOPILOT["short_id"])
        short_id, entry = stop_hook.find_session(data, SESSION_AUTOPILOT["uuid"])
        assert short_id == SESSION_AUTOPILOT["short_id"]
        assert entry["task_type"] == "autopilot"

    def test_no_match_returns_none(self):
        data = make_sessions(short_id=SESSION_AUTOPILOT["short_id"])
        short_id, entry = stop_hook.find_session(data, SESSION_ORPHAN["uuid"])
        assert short_id is None
        assert entry is None

    def test_short_session_id(self):
        data = {"sessions": {"abc": {"task_type": "run"}}}
        short_id, entry = stop_hook.find_session(data, "abc")
        assert short_id == "abc"


# ---------------------------------------------------------------------------
# read_sessions / write_sessions
# ---------------------------------------------------------------------------

class TestSessionsIO:
    def test_read_missing_file(self, project_dir):
        assert stop_hook.read_sessions(project_dir) is None

    def test_read_corrupt_file(self, project_dir):
        (Path(project_dir) / ".zac" / "sessions.json").write_text("}broken{")
        assert stop_hook.read_sessions(project_dir) is None

    def test_write_then_read_roundtrip(self, project_dir):
        data = make_sessions()
        stop_hook.write_sessions(project_dir, data)
        assert stop_hook.read_sessions(project_dir) == data

    def test_write_creates_directory(self, tmp_path):
        project_dir = str(tmp_path / "new-project")
        data = make_sessions()
        stop_hook.write_sessions(project_dir, data)
        assert stop_hook.read_sessions(project_dir) == data
