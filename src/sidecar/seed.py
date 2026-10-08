"""Create projects from the research and outreach briefs."""

import re

from sidecar.briefs import (
    parse_banned,
    parse_competing,
    parse_hypotheses,
    parse_outreach,
    parse_segments,
)
from sidecar.models import Organization
from sidecar.store import Project, Workspace

# Legal and generic suffixes ignored when comparing organization names.
_ORG_SUFFIXES = {"inc", "llc", "ltd", "co", "corp", "company", "group"}


def org_key(name: str) -> str:
    """Lowercase name without punctuation or trailing legal suffixes."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    while words and words[-1] in _ORG_SUFFIXES:
        words.pop()
    return " ".join(words)


def find_org(project: Project, name: str) -> Organization | None:
    """Match an organization by exact name, alias, or name stem."""
    key = org_key(name)
    for org in project.all("organizations"):
        names = [org.name, *org.aliases]
        if any(n.lower() == name.lower() for n in names):
            return org
        if any(org_key(n) == key for n in names):
            return org
        if key and any(org_key(n).startswith(key + " ") for n in names):
            return org
    return None


def ensure_org(project: Project, name: str, **fields: object) -> Organization:
    org = find_org(project, name)
    if org is not None:
        if fields:
            org = project.update("organizations", org.id, fields, actor="seed")
        return org
    aliases: list[str] = []
    if "/" in name:
        parts = [p.strip() for p in name.split("/")]
        name, aliases = parts[0], parts[1:]
    return project.create(
        "organizations", {"name": name, "aliases": aliases, **fields}, actor="seed"
    )


def seed_hypotheses(project: Project, brief: str) -> int:
    count = 0
    for i, h in enumerate(parse_hypotheses(brief)):
        project.create(
            "hypotheses",
            {
                "code": h.code,
                "title": h.title,
                "statement": h.statement,
                "kind": h.kind,
                "sort": i,
                "history": [{"text": "Created from the brief"}],
            },
            actor="seed",
        )
        count += 1
    competing = parse_competing(brief)
    if competing:
        project.create(
            "hypotheses",
            {
                "code": "CE",
                "title": "Competing explanation",
                "statement": competing,
                "kind": "competing",
                "sort": 100,
                "history": [{"text": "Created from the brief"}],
            },
            actor="seed",
        )
        count += 1
    return count


def seed_outreach(project: Project, brief: str) -> dict[str, int]:
    seed = parse_outreach(brief)
    for name in seed.contacted_orgs:
        ensure_org(
            project,
            name,
            already_contacted=True,
            notes="Listed as already contacted in the outreach brief.",
        )
    note = "Imported from the outreach brief. Confirm real dates and status."
    for person, org_name in seed.emailed_people:
        org = ensure_org(project, org_name, already_contacted=True)
        project.create(
            "people",
            {
                "name": person,
                "first_name": person.split()[0],
                "organization_id": org.id,
                "source": "brief",
                "stage": "sent",
                "notes": note,
            },
            actor="seed",
        )
    for person, org_name in seed.drafted:
        org = ensure_org(project, org_name)
        project.create(
            "people",
            {
                "name": person,
                "first_name": person.split()[0],
                "organization_id": org.id,
                "source": "brief",
                "stage": "ready_for_review",
                "notes": "Drafted before Sidecar. Not confirmed as sent.",
            },
            actor="seed",
        )
    for person, org_name, status in seed.leads:
        org = ensure_org(project, org_name, already_contacted=True)
        project.create(
            "people",
            {
                "name": person,
                "first_name": person.split()[0],
                "organization_id": org.id,
                "source": "brief",
                "stage": "interested",
                "next_action": "Confirm the interview date, time, and time zone",
                "notes": f"{note} Brief says: {status}.",
            },
            actor="seed",
        )
    return {
        "organizations": len(project.all("organizations")),
        "people": len(project.all("people")),
    }


def create_from_briefs(
    ws: Workspace,
    name: str,
    research_brief: str,
    outreach_brief: str = "",
    keyterms: list[str] | None = None,
) -> Project:
    project = ws.create_project(name)
    project.write_doc("brief", research_brief)
    if outreach_brief:
        project.write_doc("outreach_brief", outreach_brief)
    project.meta.coach.keyterms = keyterms or []
    project.meta.banned_phrases = parse_banned(outreach_brief)
    project.meta.segments = parse_segments(research_brief)
    project.save_meta()
    seed_hypotheses(project, research_brief)
    if outreach_brief:
        seed_outreach(project, outreach_brief)
    return project
