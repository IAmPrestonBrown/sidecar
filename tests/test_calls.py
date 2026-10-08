import json
import sys
import time

import pytest

from sidecar.calls import CallError, CallRunner, coach_command
from sidecar.store import Workspace

FAKE_COACH = """
import json, pathlib, signal, sys, time
folder = pathlib.Path(sys.argv[1])
folder.mkdir(parents=True)
(folder / "session.json").write_text(json.dumps({"interviewee": "Ana Ruiz", "duration_s": 60}))
(folder / "evidence.jsonl").write_text(json.dumps({"stance": "SUPPORTS", "hypotheses": ["H1"],
    "type": "BEHAVIOR", "note": "n", "quote": "q", "at": "00:10"}) + "\\n")
print(f"Session directory: {folder}", flush=True)
print("UI: http://127.0.0.1:9999/", flush=True)
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
time.sleep(30)
"""


def wait_for(runner: CallRunner, state: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = runner.status()
        if status and status["state"] == state:
            return status
        time.sleep(0.05)
    raise AssertionError(f"never reached {state}: {runner.status()}")


@pytest.fixture
def project(tmp_path):
    proj = Workspace(tmp_path / "projects").create_project("Calls")
    proj.create("hypotheses", {"code": "H1", "statement": "s"})
    return proj


def test_call_runs_ends_and_imports(project, tmp_path) -> None:
    person = project.create("people", {"name": "Ana Ruiz"})
    folder = tmp_path / "session"
    runner = CallRunner(lambda *_: [sys.executable, "-c", FAKE_COACH, str(folder)])
    runner.start(project, person.id, 30, "Ask about mornings")
    ready = wait_for(runner, "ready")
    assert ready["url"] == "http://127.0.0.1:9999/"
    assert ready["session_dir"] == str(folder)
    with pytest.raises(CallError, match="already running"):
        runner.start(project, person.id, 30, "")
    runner.end()
    ended = wait_for(runner, "ended")
    call = project.get("calls", ended["call_id"])
    assert call.person_id == person.id
    evidence = [e for e in project.all("evidence") if e.call_id == call.id]
    assert len(evidence) == 1
    assert evidence[0].review_status == "proposed"
    notes = list((project.path / "calls" / "notes").glob("*.md"))
    assert notes[0].read_text() == "Ask about mornings"


def test_coach_failure_is_reported(project) -> None:
    person = project.create("people", {"name": "Ana Ruiz"})
    script = "print('Preflight failed: no microphone'); raise SystemExit(1)"
    runner = CallRunner(lambda *_: [sys.executable, "-c", script])
    runner.start(project, person.id, 30, "")
    failed = wait_for(runner, "failed")
    assert "no microphone" in failed["error"]
    with pytest.raises(CallError, match="No call"):
        runner.end()


def test_coach_command_uses_project_files(project) -> None:
    (project.path / "coach-prompts").mkdir()
    project.meta.coach.keyterms = ["sourdough"]
    cmd = coach_command(project, "Ana Ruiz", "Sunrise Bakery", 30, None)
    assert cmd[cmd.index("--brief") + 1] == str(project.path / "brief.md")
    assert cmd[cmd.index("--sessions-dir") + 1] == str(project.path / "calls")
    assert cmd[cmd.index("--prompts-dir") + 1] == str(project.path / "coach-prompts")
    assert cmd[cmd.index("--keyterm") + 1] == "sourdough"
    assert "--no-browser" in cmd
    assert json.dumps(cmd)


def test_coach_run_overrides(tmp_path) -> None:
    from argparse import Namespace

    from coach.cli import with_run_overrides
    from coach.config import load_config

    cfg = load_config(config_path=tmp_path / "missing.toml")
    args = Namespace(
        brief=str(tmp_path / "brief.md"),
        prompts_dir=None,
        sessions_dir=str(tmp_path / "calls"),
        activity="active",
        keyterm=["sourdough"],
        port=9123,
    )
    out = with_run_overrides(cfg, args)
    assert out.brief_path == tmp_path / "brief.md"
    assert out.interviews_dir == tmp_path / "calls"
    assert out.prompts_dir == cfg.prompts_dir
    assert out.coach.live_activity == "active"
    assert "sourdough" in out.deepgram.keyterms
    assert out.server.port == 9123


def test_call_review_and_audio(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from sidecar.api import create_app

    ws = Workspace(tmp_path / "projects")
    project = ws.create_project("Review")
    folder = tmp_path / "session"
    folder.mkdir()
    (folder / "audio.wav").write_bytes(b"RIFF0000WAVEdata" + bytes(64))
    (folder / "session.json").write_text(json.dumps({"duration_s": 95}))
    (folder / "transcript_live.jsonl").write_text(
        json.dumps({"start": 1, "end": 2, "speaker_id": 0, "label": "THEM", "text": "live"}) + "\n"
    )
    (folder / "transcript.jsonl").write_text(
        json.dumps({"start": 3.5, "end": 5, "speaker_id": 1, "label": "ME", "text": "final"}) + "\n"
    )
    (folder / "marks.jsonl").write_text(
        json.dumps({"at": 60, "output": {"headline": "Tracker", "claim": "Keeps a sheet"}}) + "\n"
    )
    call = project.create("calls", {"session_dir": str(folder)})
    client = TestClient(create_app(ws, "t" * 32))
    base = f"/projects/review/calls/{call.id}"
    data = client.get(f"{base}/review", headers={"X-Sidecar-Token": "t" * 32}).json()
    assert data["transcript_source"] == "final"
    assert data["segments"] == [{"start": 3.5, "end": 5, "label": "ME", "text": "final"}]
    assert data["marks"][0]["headline"] == "Tracker"
    assert data["duration_s"] == 95
    assert client.get(f"{base}/audio").status_code == 401
    audio = client.get(f"{base}/audio", params={"token": "t" * 32}, headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206
    assert audio.content == b"RIFF"
