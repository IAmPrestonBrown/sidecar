"""Import recorded coach sessions into a project as calls and proposed evidence."""

import json
from pathlib import Path

from sidecar.models import Call, Person
from sidecar.store import Project, StoreError

EVIDENCE_TYPES = {
    "BEHAVIOR": "behavior",
    "INCIDENT": "incident",
    "OPINION": "opinion",
    "CAPABILITY_CLAIM": "capability_claim",
    "ARTIFACT": "artifact",
    "SEGMENT": "segment",
    "SECONDHAND": "secondhand",
}
STANCES = {"SUPPORTS": "supports", "CONTRADICTS": "contradicts", "MIXED": "mixed"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return {}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _seconds(mmss: str) -> float | None:
    parts = mmss.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]) * 60 + int(parts[1])


def match_person(project: Project, interviewee: str, organization: str) -> Person | None:
    """Find the person a session was recorded with, by name and organization."""
    name = interviewee.strip().lower()
    if not name:
        return None
    orgs = {o.id: o.name.lower() for o in project.all("organizations")}
    candidates = [
        p
        for p in project.all("people")
        if p.name.lower() == name
        or p.first_name.lower() == name
        or p.name.lower().startswith(name + " ")
    ]
    if len(candidates) > 1 and organization:
        org = organization.lower()
        candidates = [p for p in candidates if orgs.get(p.organization_id, "").startswith(org[:12])]
    return candidates[0] if len(candidates) == 1 else None


def import_session(project: Project, session_dir: Path, person_id: str = "") -> Call:
    """Create a call for a session folder and add its evidence as proposed items.

    Importing the same folder twice is refused.
    """
    session_dir = session_dir.expanduser().resolve()
    meta = _read_json(session_dir / "session.json")
    if not meta:
        raise StoreError(f"{session_dir} has no session.json")
    if any(c.session_dir == str(session_dir) for c in project.all("calls")):
        raise StoreError(f"{session_dir.name} was already imported")

    person = None
    if person_id:
        person = project.get("people", person_id)
    else:
        person = match_person(project, meta.get("interviewee", ""), meta.get("organization", ""))
    call = project.create(
        "calls",
        {
            "person_id": person.id if person else "",
            "title": f"{meta.get('interviewee', 'Call')} ({session_dir.name})",
            "started_at": meta.get("started_at") or meta.get("created_at", ""),
            "duration_s": float(meta.get("duration_s") or 0.0),
            "session_dir": str(session_dir),
            "status": "imported",
            "planned_minutes": int(meta.get("planned_minutes") or 30),
            "marks": len(_read_jsonl(session_dir / "marks.jsonl")),
            "cost_usd": float((meta.get("costs") or {}).get("coach_usd", 0.0)),
        },
        actor="import",
    )
    codes = {h.code: h.id for h in project.all("hypotheses")}
    for item in _read_jsonl(session_dir / "evidence.jsonl"):
        stance = STANCES.get(str(item.get("stance", "")).upper())
        links = [
            {"hypothesis_id": codes[c], "stance": stance}
            for c in item.get("hypotheses", [])
            if stance and c in codes
        ]
        project.create(
            "evidence",
            {
                "call_id": call.id,
                "person_id": person.id if person else "",
                "organization_id": person.organization_id if person else "",
                "at_seconds": _seconds(str(item.get("at", ""))),
                "quote": item.get("quote", ""),
                "note": item.get("note", ""),
                "type": EVIDENCE_TYPES.get(str(item.get("type", "")).upper(), "opinion"),
                "basis": "statement",
                "source": "call",
                "review_status": "proposed",
                "links": links,
                "origin": "coach",
            },
            actor="import",
        )
    assert isinstance(call, Call)
    return call
