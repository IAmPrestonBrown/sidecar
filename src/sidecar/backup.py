"""Daily copies of every project folder."""

import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_BACKUP_ROOT = Path.home() / "Library" / "Application Support" / "Sidecar" / "backups"
KEEP_DAYS = 14
SKIP = shutil.ignore_patterns("exports", ".sidecar", "*.wav", "*.pcm", "*.tmp")


def backup_workspace(
    root: Path, dest_root: Path = DEFAULT_BACKUP_ROOT, today: date | None = None
) -> Path | None:
    """Copy every project in root to dest_root/<date>/ once per day.

    Returns the new backup folder, or None when today's backup already exists.
    Folders older than KEEP_DAYS are removed afterwards.
    """
    today = today or date.today()
    dest = dest_root / today.isoformat()
    if dest.exists():
        return None
    partial = dest_root / f".{today.isoformat()}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    for project in sorted(p for p in root.iterdir() if (p / "project.json").exists()):
        shutil.copytree(project, partial / project.name, ignore=SKIP)
    partial.rename(dest)
    prune(dest_root, today)
    log.info("Backed up projects to %s", dest)
    return dest


def prune(dest_root: Path, today: date) -> list[Path]:
    """Remove dated backup folders older than KEEP_DAYS."""
    cutoff = today - timedelta(days=KEEP_DAYS)
    removed = []
    for folder in dest_root.iterdir():
        try:
            day = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(folder)
            removed.append(folder)
    return removed
