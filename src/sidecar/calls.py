"""Run the interview coach as a child process for one call at a time.

The coach keeps its own process so a problem in the engine or the app never
stops a recording. The engine starts it, reads the session folder and UI address
from its output, and imports the session into the project when it exits.
"""

import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sidecar import sessions
from sidecar.store import Project, StoreError

log = logging.getLogger(__name__)

SESSION_LINE = re.compile(r"^Session directory: (.+)$")
UI_LINE = re.compile(r"^UI: (http://127\.0\.0\.1:\d+/)$")
LOG_LINES = 40


class CallError(Exception):
    pass


@dataclass
class ActiveCall:
    slug: str
    person_id: str
    person_name: str
    process: subprocess.Popen[str]
    started_at: str
    state: str = "starting"  # starting, ready, ending, ended, failed
    url: str = ""
    session_dir: str = ""
    call_id: str = ""
    error: str = ""
    output: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_LINES))

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "started_at": self.started_at,
            "state": self.state,
            "url": self.url,
            "session_dir": self.session_dir,
            "call_id": self.call_id,
            "error": self.error,
            "output": list(self.output),
        }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def coach_command(
    project: Project, interviewee: str, org: str, minutes: int, notes: Path | None
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "coach.cli",
        "run",
        "--interviewee",
        interviewee,
        "--org",
        org,
        "--minutes",
        str(minutes),
        "--no-browser",
        "--brief",
        str(project.path / "brief.md"),
        "--sessions-dir",
        str(project.path / "calls"),
        "--port",
        str(free_port()),
        "--activity",
        project.meta.coach.activity,
    ]
    prompts = project.path / "coach-prompts"
    if prompts.is_dir():
        cmd += ["--prompts-dir", str(prompts)]
    for term in project.meta.coach.keyterms:
        cmd += ["--keyterm", term]
    if notes is not None:
        cmd += ["--notes", str(notes)]
    return cmd


class CallRunner:
    """Owns the single active call, if any."""

    def __init__(self, command: Callable[..., list[str]] = coach_command) -> None:
        self.command = command
        self.lock = threading.Lock()
        self.call: ActiveCall | None = None

    @property
    def live(self) -> bool:
        with self.lock:
            return self.call is not None and self.call.state in ("starting", "ready", "ending")

    def status(self) -> dict | None:
        with self.lock:
            return self.call.as_dict() if self.call else None

    def start(self, project: Project, person_id: str, minutes: int, notes: str) -> dict:
        with self.lock:
            if self.call and self.call.state in ("starting", "ready", "ending"):
                raise CallError(f"A call with {self.call.person_name} is already running")
            person = project.get("people", person_id)
            org = (
                project.get("organizations", person.organization_id)
                if person.organization_id
                else None
            )
            notes_path = None
            if notes.strip():
                notes_dir = project.path / "calls" / "notes"
                notes_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                notes_path = notes_dir / f"{stamp}.md"
                notes_path.write_text(notes)
            cmd = self.command(project, person.name, org.name if org else "", minutes, notes_path)
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            # A new session keeps signals sent to the engine away from the recording.
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                env=env,
                start_new_session=True,
            )
            self.call = ActiveCall(
                slug=project.meta.slug,
                person_id=person.id,
                person_name=person.name,
                process=process,
                started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            call = self.call
        threading.Thread(target=self._watch, args=(project, call), daemon=True).start()
        return call.as_dict()

    def end(self) -> dict:
        """Ask the coach to end the session the same way Ctrl-C does."""
        with self.lock:
            call = self.call
            if call is None or call.state not in ("starting", "ready"):
                raise CallError("No call is running")
            call.state = "ending"
            call.process.send_signal(signal.SIGINT)
            return call.as_dict()

    def _watch(self, project: Project, call: ActiveCall) -> None:
        assert call.process.stdout is not None
        for raw in call.process.stdout:
            line = raw.rstrip()
            with self.lock:
                call.output.append(line)
                if m := SESSION_LINE.match(line):
                    call.session_dir = m.group(1)
                elif m := UI_LINE.match(line):
                    call.url = m.group(1)
                    if call.state == "starting":
                        call.state = "ready"
        code = call.process.wait()
        imported = ""
        error = ""
        if call.session_dir:
            try:
                imported = sessions.import_session(
                    project, Path(call.session_dir), call.person_id
                ).id
            except StoreError as exc:
                error = str(exc)
                log.warning("Could not import %s: %s", call.session_dir, exc)
        with self.lock:
            call.call_id = imported
            if code != 0 and not call.url:
                call.state = "failed"
                call.error = error or (
                    call.output[-1] if call.output else f"Coach exited with {code}"
                )
            else:
                call.state = "ended"
                call.error = error
