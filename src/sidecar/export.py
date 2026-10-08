"""One-file exports of a project for use in other tools."""

import json
from datetime import date
from pathlib import Path

from sidecar.models import COLLECTIONS, STRONG_TYPES, Evidence, Hypothesis
from sidecar.store import Project, atomic_write

STANCE_ORDER = ("supports", "contradicts", "mixed")


def _transcript(project: Project, session_dir: str) -> str:
    if not session_dir:
        return ""
    folder = project.path / "calls" / session_dir
    for name in ("transcript.md", "transcript_live.md"):
        path = folder / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def export_data(project: Project) -> dict:
    """Everything in the project as one JSON-ready dict."""
    data: dict = {
        "format": "sidecar-project-export",
        "format_version": 1,
        "exported_on": date.today().isoformat(),
        "project": project.meta.model_dump(mode="json"),
        "brief": project.read_doc("brief"),
        "outreach_brief": project.read_doc("outreach_brief"),
    }
    for name in COLLECTIONS:
        data[name] = [r.model_dump(mode="json") for r in project.all(name)]
    data["transcripts"] = {
        c.id: _transcript(project, getattr(c, "session_dir", "")) for c in project.all("calls")
    }
    return data


def tallies(project: Project, hypothesis_id: str) -> dict:
    """Accepted-evidence counts for one hypothesis, by stance and strength."""
    people = {p.id: p for p in project.all("people")}
    out = {s: {"strong": 0, "weak": 0} for s in STANCE_ORDER}
    orgs: set[str] = set()
    for ev in project.all("evidence"):
        if ev.review_status != "accepted":
            continue
        for link in ev.links:
            if link.hypothesis_id != hypothesis_id:
                continue
            strong = ev.type in STRONG_TYPES and ev.basis != "interpretation"
            out[link.stance]["strong" if strong else "weak"] += 1
            org = ev.organization_id or getattr(people.get(ev.person_id), "organization_id", "")
            if org:
                orgs.add(org)
    out["organizations"] = len(orgs)
    return out


def _evidence_line(ev: Evidence, people: dict, orgs: dict) -> str:
    who = people.get(ev.person_id)
    org = orgs.get(ev.organization_id or getattr(who, "organization_id", ""))
    source = ", ".join(x for x in (getattr(who, "name", ""), getattr(org, "name", "")) if x)
    text = ev.quote or ev.note
    meta = f"{ev.type}, {ev.basis}" + (f", {source}" if source else "")
    return f'- "{text}" ({meta})' if ev.quote else f"- {text} ({meta})"


def export_markdown(project: Project) -> str:
    people = {p.id: p for p in project.all("people")}
    orgs = {o.id: o for o in project.all("organizations")}
    evidence = [e for e in project.all("evidence") if e.review_status == "accepted"]
    hyps: list[Hypothesis] = sorted(project.all("hypotheses"), key=lambda h: h.sort)
    lines = [f"# {project.meta.name}", f"Exported {date.today().isoformat()} from Sidecar.", ""]
    lines += ["## Hypotheses and accepted evidence", ""]
    for h in hyps:
        t = tallies(project, h.id)
        counts = ", ".join(
            f"{s} {t[s]['strong'] + t[s]['weak']} ({t[s]['strong']} strong)" for s in STANCE_ORDER
        )
        lines += [
            f"### {h.code}: {h.title or h.kind}",
            h.statement,
            "",
            f"Status: {h.status}. {counts}. Independent organizations: {t['organizations']}.",
            "",
        ]
        for stance in STANCE_ORDER:
            items = [
                e
                for e in evidence
                if any(lk.hypothesis_id == h.id and lk.stance == stance for lk in e.links)
            ]
            if items:
                lines.append(f"{stance.capitalize()}:")
                lines += [_evidence_line(e, people, orgs) for e in items]
                lines.append("")
        if h.notes:
            lines += ["Notes: " + h.notes, ""]
    lines += [
        "## People",
        "",
        "| Name | Organization | Segment | Stage | Next action |",
        "|---|---|---|---|---|",
    ]
    for p in sorted(people.values(), key=lambda p: p.name.lower()):
        org = orgs.get(p.organization_id)
        lines.append(
            f"| {p.name} | {getattr(org, 'name', '')} | {p.segment} | {p.stage} | {p.next_action} |"
        )
    lines.append("")
    calls = project.all("calls")
    if calls:
        lines += ["## Calls", ""]
        for c in calls:
            who = people.get(c.person_id)
            name = getattr(who, "name", c.title)
            lines.append(f"- {c.started_at[:16]} {name}: {int(c.duration_s // 60)} min")
        lines.append("")
    return "\n".join(lines)


def export_project(project: Project) -> tuple[Path, Path]:
    """Write exports/<slug>-<date>.json and .md and return both paths."""
    out_dir = project.path / "exports"
    out_dir.mkdir(exist_ok=True)
    stem = f"{project.slug}-{date.today().isoformat()}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    atomic_write(json_path, json.dumps(export_data(project), indent=2, ensure_ascii=False) + "\n")
    atomic_write(md_path, export_markdown(project))
    project.log_activity("export", "project", "", "user", files=[json_path.name, md_path.name])
    return json_path, md_path
