"""Engine process entry point. The desktop shell starts and stops it."""

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn

from sidecar.api import create_app
from sidecar.backup import backup_workspace
from sidecar.calls import CallRunner
from sidecar.gmail import Gmail
from sidecar.mail import Mailer
from sidecar.store import DEFAULT_ROOT, Workspace

log = logging.getLogger("sidecar.engine")
PARENT_POLL_S = 1.0
BACKUP_CHECK_S = 3600.0


def watch_parent(parent_pid: int) -> None:
    """Exit when the parent process is gone so the engine never outlives the app."""
    while True:
        time.sleep(PARENT_POLL_S)
        if os.getppid() != parent_pid:
            log.warning("Parent process exited; stopping engine")
            os._exit(0)


def run_backups(root: Path) -> None:
    """Make the daily backup now if missing, then check again every hour."""
    while True:
        try:
            backup_workspace(root)
        except OSError:
            log.exception("Daily backup failed")
        time.sleep(BACKUP_CHECK_S)


def watch_stdin() -> None:
    """Exit when stdin closes. The shell holds the pipe open while it runs."""
    while sys.stdin.read(1024):
        pass
    log.warning("stdin closed; stopping engine")
    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(prog="sidecar-engine")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", default=os.environ.get("SIDECAR_ROOT", str(DEFAULT_ROOT)))
    parser.add_argument("--watch-stdin", action="store_true", help="exit when stdin closes")
    args = parser.parse_args()

    token = os.environ.get("SIDECAR_TOKEN", "")
    if len(token) < 16:
        sys.exit("SIDECAR_TOKEN must be set to a random value of at least 16 characters")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    threading.Thread(target=watch_parent, args=(os.getppid(),), daemon=True).start()
    if args.watch_stdin:
        threading.Thread(target=watch_stdin, daemon=True).start()

    root = Path(args.root)
    threading.Thread(target=run_backups, args=(root,), daemon=True).start()
    workspace = Workspace(root)
    calls = CallRunner()
    gmail = Gmail(opener=lambda url: subprocess.run(["open", url], check=False, timeout=10))
    mailer = Mailer(workspace, gmail, call_live=lambda: calls.live)
    threading.Thread(target=mailer.run, args=(threading.Event(),), daemon=True).start()
    app = create_app(workspace, token, calls, gmail, mailer)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
