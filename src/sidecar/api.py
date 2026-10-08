"""HTTP API the desktop UI talks to. Bound to 127.0.0.1 and token protected."""

import hmac
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from sidecar import __version__, csv_import, outreach, sessions
from sidecar.export import export_project, tallies
from sidecar.models import COLLECTIONS, ProjectMeta
from sidecar.store import TEXT_DOCS, NotFoundError, Project, StoreError, Workspace

TOKEN_HEADER = "X-Sidecar-Token"
UI_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]
OPEN_STAGES = {"interested", "scheduling", "confirmed"}


class DocBody(BaseModel):
    text: str


class NewProject(BaseModel):
    name: str


class DraftRequest(BaseModel):
    person_ids: list[str]
    wave_id: str = ""


class ApproveRequest(BaseModel):
    ids: list[str]
    confirm_inferred: bool = False


class IdsRequest(BaseModel):
    ids: list[str]


class CsvRequest(BaseModel):
    csv: str
    mapping: dict[str, str] | None = None


class SessionRequest(BaseModel):
    path: str
    person_id: str = ""


def birth_time(path: Path) -> float:
    """File creation time where the platform records it, else modification time."""
    st = path.stat()
    return getattr(st, "st_birthtime", st.st_mtime)


def create_app(workspace: Workspace, token: str) -> FastAPI:
    app = FastAPI(title="Sidecar engine", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=UI_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def check_token(request: Request) -> None:
        given = request.headers.get(TOKEN_HEADER, "")
        if not hmac.compare_digest(given, token):
            raise HTTPException(status_code=401, detail="Bad or missing token")

    def project(slug: str) -> Project:
        return workspace.project(slug)

    def collection_name(name: str) -> str:
        if name not in COLLECTIONS:
            raise HTTPException(status_code=404, detail=f"Unknown collection {name!r}")
        return name

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(StoreError)
    async def store_error(_: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValidationError)
    async def invalid(_: Request, exc: ValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse({"detail": "Invalid data", "errors": errors}, status_code=422)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    guarded = [Depends(check_token)]

    @app.get("/projects", dependencies=guarded)
    def list_projects() -> list[dict]:
        projects = sorted(
            (workspace.project(s) for s in workspace.slugs()),
            key=lambda p: (p.meta.created_at, birth_time(p.path / "project.json")),
        )
        return [{"slug": p.slug, "name": p.meta.name, "path": str(p.path)} for p in projects]

    @app.post("/projects", dependencies=guarded)
    def new_project(body: NewProject) -> dict:
        proj = workspace.create_project(body.name)
        return {"slug": proj.slug, "name": proj.meta.name, "path": str(proj.path)}

    @app.get("/projects/{slug}", dependencies=guarded)
    def get_project(slug: str) -> dict:
        proj = project(slug)
        return {**proj.meta.model_dump(mode="json"), "path": str(proj.path)}

    @app.patch("/projects/{slug}", dependencies=guarded)
    def patch_project(slug: str, patch: dict[str, Any]) -> dict:
        proj = project(slug)
        merged = proj.meta.model_dump(mode="json")
        for key, value in patch.items():
            if key in ("slug", "created_at"):
                continue
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        proj.meta = ProjectMeta.model_validate(merged)
        proj.save_meta()
        return {**proj.meta.model_dump(mode="json"), "path": str(proj.path)}

    @app.get("/projects/{slug}/docs/{doc}", dependencies=guarded)
    def get_doc(slug: str, doc: str) -> dict:
        if doc not in TEXT_DOCS:
            raise HTTPException(status_code=404, detail=f"Unknown document {doc!r}")
        return {"text": project(slug).read_doc(doc)}

    @app.put("/projects/{slug}/docs/{doc}", dependencies=guarded)
    def put_doc(slug: str, doc: str, body: DocBody) -> dict:
        if doc not in TEXT_DOCS:
            raise HTTPException(status_code=404, detail=f"Unknown document {doc!r}")
        project(slug).write_doc(doc, body.text)
        return {"ok": True}

    @app.get("/projects/{slug}/c/{name}", dependencies=guarded)
    def list_records(slug: str, name: str) -> list[dict]:
        return [r.model_dump(mode="json") for r in project(slug).all(collection_name(name))]

    @app.post("/projects/{slug}/c/{name}", dependencies=guarded)
    def create_record(slug: str, name: str, data: dict[str, Any]) -> dict:
        return project(slug).create(collection_name(name), data).model_dump(mode="json")

    @app.get("/projects/{slug}/c/{name}/{record_id}", dependencies=guarded)
    def get_record(slug: str, name: str, record_id: str) -> dict:
        return project(slug).get(collection_name(name), record_id).model_dump(mode="json")

    @app.patch("/projects/{slug}/c/{name}/{record_id}", dependencies=guarded)
    def patch_record(slug: str, name: str, record_id: str, patch: dict[str, Any]) -> dict:
        rec = project(slug).update(collection_name(name), record_id, patch)
        return rec.model_dump(mode="json")

    @app.delete("/projects/{slug}/c/{name}/{record_id}", dependencies=guarded)
    def delete_record(slug: str, name: str, record_id: str) -> dict:
        project(slug).delete(collection_name(name), record_id)
        return {"ok": True}

    @app.get("/projects/{slug}/tallies", dependencies=guarded)
    def hypothesis_tallies(slug: str) -> dict:
        proj = project(slug)
        return {h.id: tallies(proj, h.id) for h in proj.all("hypotheses")}

    @app.get("/projects/{slug}/overview", dependencies=guarded)
    def overview(slug: str) -> dict:
        proj = project(slug)
        people = proj.all("people")
        stages = Counter(p.stage for p in people)
        evidence = proj.all("evidence")
        messages = proj.all("messages")
        return {
            "stages": dict(stages),
            "people": len(people),
            "organizations": len(proj.all("organizations")),
            "evidence_to_review": sum(1 for e in evidence if e.review_status == "proposed"),
            "evidence_accepted": sum(1 for e in evidence if e.review_status == "accepted"),
            "drafts_to_review": sum(1 for m in messages if m.status == "draft"),
            "sent": sum(1 for m in messages if m.status == "sent"),
            "prospects_to_review": stages.get("ready_for_review", 0),
            "leads_open": [p.model_dump(mode="json") for p in people if p.stage in OPEN_STAGES],
            "interviews": [i.model_dump(mode="json") for i in proj.all("interviews")],
        }

    @app.post("/projects/{slug}/export", dependencies=guarded)
    def export(slug: str) -> dict:
        json_path, md_path = export_project(project(slug))
        return {"json": str(json_path), "markdown": str(md_path)}

    @app.post("/projects/{slug}/reveal", dependencies=guarded)
    def reveal(slug: str) -> dict:
        subprocess.run(["open", str(project(slug).path)], check=False, timeout=10)
        return {"ok": True}

    @app.get("/projects/{slug}/outreach/templates", dependencies=guarded)
    def templates(slug: str) -> dict:
        return outreach.ensure_templates(project(slug)).model_dump(mode="json")

    @app.post("/projects/{slug}/outreach/drafts", dependencies=guarded)
    def create_drafts(slug: str, body: DraftRequest) -> dict:
        proj = project(slug)
        created, errors = [], {}
        for pid in body.person_ids:
            try:
                created.append(outreach.draft_initial(proj, pid, body.wave_id).id)
            except (NotFoundError, StoreError) as exc:
                errors[pid] = str(exc)
        return {"created": created, "errors": errors}

    @app.get("/projects/{slug}/outreach/queue", dependencies=guarded)
    def queue(slug: str) -> list[dict]:
        proj = project(slug)
        people = {p.id: p for p in proj.all("people")}
        orgs = {o.id: o for o in proj.all("organizations")}
        out = []
        for m in proj.all("messages"):
            if m.status not in ("draft", "approved"):
                continue
            person = people.get(m.person_id)
            org = orgs.get(person.organization_id) if person else None
            checks = outreach.run_checks(proj, m) if m.status == "draft" else m.checks
            out.append(
                {
                    **m.model_dump(mode="json"),
                    "checks": [c if isinstance(c, dict) else asdict(c) for c in checks],
                    "person": person.model_dump(mode="json") if person else None,
                    "organization": org.model_dump(mode="json") if org else None,
                }
            )
        return sorted(out, key=lambda m: m["created_at"])

    @app.post("/projects/{slug}/outreach/approve", dependencies=guarded)
    def approve(slug: str, body: ApproveRequest) -> dict:
        return outreach.approve(project(slug), body.ids, body.confirm_inferred)

    @app.post("/projects/{slug}/outreach/skip", dependencies=guarded)
    def skip(slug: str, body: IdsRequest) -> dict:
        return {"skipped": outreach.skip(project(slug), body.ids)}

    @app.get("/projects/{slug}/outreach/metrics", dependencies=guarded)
    def outreach_metrics(slug: str) -> dict:
        return outreach.metrics(project(slug))

    @app.post("/projects/{slug}/import/preview", dependencies=guarded)
    def import_preview(slug: str, body: CsvRequest) -> dict:
        headers, _ = csv_import.read_rows(body.csv)
        mapping = body.mapping if body.mapping is not None else csv_import.guess_mapping(headers)
        rows = csv_import.preview(project(slug), body.csv, mapping)
        return {
            "headers": headers,
            "mapping": mapping,
            "targets": csv_import.TARGETS,
            "rows": csv_import.rows_json(rows),
        }

    @app.post("/projects/{slug}/import/commit", dependencies=guarded)
    def import_commit(slug: str, body: CsvRequest) -> dict:
        if body.mapping is None:
            raise HTTPException(status_code=422, detail="A column mapping is required")
        return csv_import.commit(project(slug), body.csv, body.mapping)

    @app.post("/projects/{slug}/import/session", dependencies=guarded)
    def import_session(slug: str, body: SessionRequest) -> dict:
        call = sessions.import_session(project(slug), Path(body.path), body.person_id)
        return call.model_dump(mode="json")

    return app
