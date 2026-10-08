"""Project folders: JSON collections on disk, written atomically."""

import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sidecar.models import COLLECTIONS, ProjectMeta, Record, new_id, now_iso

log = logging.getLogger(__name__)

DEFAULT_ROOT = Path.home() / "Documents" / "Sidecar"
BACKUP_DIR = ".sidecar"
TEXT_DOCS = {"brief": "brief.md", "outreach_brief": "outreach_brief.md"}

README = """# {name}

This folder is a Sidecar project. Every file is plain JSON or Markdown and can be
read, copied, or shared without the app.

| File | Contents |
|---|---|
| project.json | Project name and settings |
| brief.md | Research brief: purpose, hypotheses, rules. The live coach reads it. |
| outreach_brief.md | Who to contact and how to write to them. The email writer reads it. |
| hypotheses.json | Hypotheses (problem, solution) and the competing explanation |
| organizations.json | Organizations, tracked globally to avoid contacting coworkers |
| people.json | People, their research notes, sources, and outreach stage |
| interviews.json | Proposed and confirmed interview times, and outcomes |
| evidence.json | Evidence items, each linked to hypotheses with a stance |
| messages.json | Every drafted, approved, and sent email |
| waves.json | Outreach batches |
| calls.json | Index of recorded calls; audio and transcripts live in calls/ |
| research_runs.json | Prospect research runs |
| activity.jsonl | Append-only log of every change |
| exports/ | One-file exports (JSON and Markdown) for use in other tools |
| .sidecar/ | Previous version of each file, kept for recovery |

Evidence fields: `type` is behavior, incident, opinion, capability_claim, artifact,
segment, or secondhand. `basis` is statement (what the person said), observed (what
the researcher saw), artifact (a document or screen), or interpretation (the researcher's
reading).
Only accepted evidence (`review_status: accepted`) counts toward a hypothesis.
"""


class StoreError(Exception):
    """A request the store cannot satisfy."""


class NotFoundError(StoreError):
    """The requested project or record does not exist."""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "project"


def atomic_write(path: Path, text: str) -> None:
    """Write text to path through a temp file, keeping the old file as .bak."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    if path.exists():
        backup_dir = path.parent / BACKUP_DIR
        backup_dir.mkdir(exist_ok=True)
        shutil.copy2(path, backup_dir / (path.name + ".bak"))
    os.replace(tmp, path)


class Collection:
    """One JSON array file loaded into memory, keyed by record id."""

    def __init__(self, path: Path, model: type[Record], prefix: str) -> None:
        self.path = path
        self.model = model
        self.prefix = prefix
        self.items: dict[str, Record] = {}
        self._mtime: float | None = None
        self.load()

    def load(self) -> None:
        self.items = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
            for obj in raw:
                try:
                    rec = self.model.model_validate(obj)
                except ValidationError as exc:
                    log.warning("Skipping invalid record in %s: %s", self.path.name, exc)
                    continue
                self.items[rec.id] = rec
            self._mtime = self.path.stat().st_mtime
        else:
            self._mtime = None

    def refresh_if_changed(self) -> bool:
        """Reload when the file was edited outside the engine."""
        mtime = self.path.stat().st_mtime if self.path.exists() else None
        if mtime != self._mtime:
            log.info("%s changed on disk; reloading", self.path.name)
            self.load()
            return True
        return False

    def save(self) -> None:
        data = [rec.model_dump(mode="json") for rec in self.items.values()]
        atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        self._mtime = self.path.stat().st_mtime


class Project:
    """One project folder. All mutations go through this class."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.meta_path = path / "project.json"
        if not self.meta_path.exists():
            raise NotFoundError(f"No project at {path}")
        self._meta_mtime = 0
        self._meta = self._read_meta()
        self.collections = {
            name: Collection(path / f"{name}.json", model, prefix)
            for name, (model, prefix) in COLLECTIONS.items()
        }

    def _read_meta(self) -> ProjectMeta:
        self._meta_mtime = self.meta_path.stat().st_mtime_ns
        return ProjectMeta.model_validate_json(self.meta_path.read_text(encoding="utf-8"))

    @property
    def meta(self) -> ProjectMeta:
        """Project settings, reloaded when project.json changes on disk."""
        with self.lock:
            if self.meta_path.stat().st_mtime_ns != self._meta_mtime:
                self._meta = self._read_meta()
            return self._meta

    @meta.setter
    def meta(self, value: ProjectMeta) -> None:
        with self.lock:
            self._meta = value

    @property
    def slug(self) -> str:
        return self.meta.slug

    def collection(self, name: str) -> Collection:
        coll = self.collections.get(name)
        if coll is None:
            raise NotFoundError(f"Unknown collection {name!r}")
        coll.refresh_if_changed()
        return coll

    def all(self, name: str) -> list[Record]:
        with self.lock:
            return list(self.collection(name).items.values())

    def get(self, name: str, record_id: str) -> Record:
        with self.lock:
            rec = self.collection(name).items.get(record_id)
            if rec is None:
                raise NotFoundError(f"No {name} record {record_id}")
            return rec

    def create(self, name: str, data: dict[str, Any], actor: str = "user") -> Record:
        with self.lock:
            coll = self.collection(name)
            payload = {k: v for k, v in data.items() if k not in ("created_at", "updated_at")}
            payload["id"] = payload.get("id") or new_id(coll.prefix)
            if payload["id"] in coll.items:
                raise StoreError(f"{name} record {payload['id']} already exists")
            rec = coll.model.model_validate(payload)
            coll.items[rec.id] = rec
            coll.save()
            self.log_activity("create", name, rec.id, actor)
            return rec

    def update(
        self, name: str, record_id: str, patch: dict[str, Any], actor: str = "user"
    ) -> Record:
        with self.lock:
            coll = self.collection(name)
            old = coll.items.get(record_id)
            if old is None:
                raise NotFoundError(f"No {name} record {record_id}")
            merged = old.model_dump(mode="json")
            for key, value in patch.items():
                if key in ("id", "created_at"):
                    continue
                merged[key] = value
            merged["updated_at"] = now_iso()
            rec = coll.model.model_validate(merged)
            coll.items[record_id] = rec
            coll.save()
            changed = sorted(k for k in patch if k not in ("id", "created_at", "updated_at"))
            self.log_activity("update", name, record_id, actor, fields=changed)
            return rec

    def delete(self, name: str, record_id: str, actor: str = "user") -> None:
        with self.lock:
            coll = self.collection(name)
            if coll.items.pop(record_id, None) is None:
                raise NotFoundError(f"No {name} record {record_id}")
            coll.save()
            self.log_activity("delete", name, record_id, actor)

    def read_doc(self, doc: str) -> str:
        path = self.path / TEXT_DOCS[doc]
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def write_doc(self, doc: str, text: str) -> None:
        with self.lock:
            atomic_write(self.path / TEXT_DOCS[doc], text)
            self.log_activity("update", doc, "", "user")

    def save_meta(self) -> None:
        with self.lock:
            atomic_write(self.meta_path, self._meta.model_dump_json(indent=2) + "\n")
            self._meta_mtime = self.meta_path.stat().st_mtime_ns
            self.log_activity("update", "project", "", "user")

    def log_activity(
        self, action: str, collection: str, record_id: str, actor: str, **extra: Any
    ) -> None:
        line = {
            "at": now_iso(),
            "actor": actor,
            "action": action,
            "collection": collection,
            "id": record_id,
            **extra,
        }
        with open(self.path / "activity.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


class Workspace:
    """The root folder that holds project folders."""

    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._projects: dict[str, Project] = {}
        self._lock = threading.Lock()

    def slugs(self) -> list[str]:
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and (p / "project.json").exists()
        )

    def project(self, slug: str) -> Project:
        with self._lock:
            proj = self._projects.get(slug)
            if proj is None:
                path = self.root / slug
                if not (path / "project.json").exists():
                    raise NotFoundError(f"No project {slug!r}")
                proj = Project(path)
                self._projects[slug] = proj
            return proj

    def create_project(self, name: str, slug: str = "") -> Project:
        slug = slug or slugify(name)
        path = self.root / slug
        if (path / "project.json").exists():
            raise StoreError(f"Project {slug!r} already exists")
        (path / "calls").mkdir(parents=True, exist_ok=True)
        (path / "exports").mkdir(exist_ok=True)
        meta = ProjectMeta(name=name, slug=slug)
        atomic_write(path / "project.json", meta.model_dump_json(indent=2) + "\n")
        atomic_write(path / "README.md", README.format(name=name))
        for coll in COLLECTIONS:
            atomic_write(path / f"{coll}.json", "[]\n")
        for doc in TEXT_DOCS.values():
            if not (path / doc).exists():
                atomic_write(path / doc, "")
        return self.project(slug)
