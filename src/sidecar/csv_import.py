"""Import people from a CSV file with a column mapping."""

import csv
import io
from dataclasses import asdict, dataclass, field

from sidecar.seed import ensure_org, find_org, org_key
from sidecar.store import Project

TARGETS = [
    "name",
    "first_name",
    "email",
    "email_confidence",
    "organization",
    "role",
    "phone",
    "website",
    "segment",
    "time_zone",
    "background",
    "notes",
]

# Header spellings recognized when guessing the mapping.
ALIASES = {
    "name": {"name", "full name", "contact", "contact name", "person"},
    "first_name": {"first name", "first", "given name"},
    "email": {"email", "email address", "e-mail", "mail"},
    "email_confidence": {"email confidence", "email status", "verification", "verified"},
    "organization": {"organization", "organisation", "company", "org", "employer", "business"},
    "role": {"role", "title", "job title", "position"},
    "phone": {"phone", "phone number", "business phone", "telephone"},
    "website": {"website", "url", "site", "company website"},
    "segment": {"segment", "type", "category"},
    "time_zone": {"time zone", "timezone", "tz"},
    "background": {"background", "bio", "summary"},
    "notes": {"notes", "note", "comments"},
}

CONFIDENCE_WORDS = {
    "verified_direct": ("verified", "direct"),
    "inferred_direct": ("inferred", "guess", "pattern"),
    "generic": ("generic", "info@", "general"),
    "unavailable": ("unavailable", "none", "unknown"),
}


@dataclass
class Row:
    line: int
    values: dict[str, str]
    action: str = "create"
    issues: list[str] = field(default_factory=list)


def read_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip() for h in reader.fieldnames or []]
    rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]
    return headers, rows


def guess_mapping(headers: list[str]) -> dict[str, str]:
    """Map CSV headers to person fields by common spellings."""
    mapping: dict[str, str] = {}
    for header in headers:
        key = header.lower().replace("_", " ").strip()
        for target, names in ALIASES.items():
            if key in names and target not in mapping.values():
                mapping[header] = target
                break
    return mapping


def _normalize(value: str, table: dict[str, tuple[str, ...]], default: str) -> str:
    low = value.lower().strip()
    if low in table:
        return low
    for target, words in table.items():
        if any(w in low for w in words):
            return target
    return default


def _match_segment(value: str, segments: list[str]) -> str:
    """The project segment a CSV value names, or an empty string."""
    low = value.lower().strip()
    if not low:
        return ""
    for seg in segments:
        if seg.lower() == low:
            return seg
    matches = [seg for seg in segments if low in seg.lower() or seg.lower() in low]
    return matches[0] if len(matches) == 1 else ""


def _person_values(
    raw: dict[str, str], mapping: dict[str, str], segments: list[str]
) -> dict[str, str]:
    values = {target: raw.get(header, "") for header, target in mapping.items() if target}
    if not values.get("first_name") and values.get("name"):
        values["first_name"] = values["name"].split()[0]
    if "segment" in values:
        values["segment"] = _match_segment(values["segment"], segments)
    if "email_confidence" not in values:
        # An address with no stated verification counts as unverified.
        values["email_confidence"] = "inferred_direct" if values.get("email") else "unavailable"
    else:
        default = "unavailable" if not values.get("email") else "inferred_direct"
        values["email_confidence"] = _normalize(
            values["email_confidence"], CONFIDENCE_WORDS, default
        )
    return values


def preview(project: Project, text: str, mapping: dict[str, str]) -> list[Row]:
    """What importing would do, row by row, without changing anything."""
    _, raw_rows = read_rows(text)
    people = project.all("people")
    emails = {p.email.lower() for p in people if p.email}
    names = {(p.name.lower(), p.organization_id) for p in people}
    seen_orgs: dict[str, int] = {}
    out: list[Row] = []
    for i, raw in enumerate(raw_rows, start=2):
        row = Row(line=i, values=_person_values(raw, mapping, project.meta.segments))
        v = row.values
        if not v.get("name"):
            row.action = "skip"
            row.issues.append("No name")
            out.append(row)
            continue
        org = find_org(project, v["organization"]) if v.get("organization") else None
        if v.get("email") and v["email"].lower() in emails:
            row.action = "skip"
            row.issues.append("Email already in People")
        elif (v["name"].lower(), org.id if org else "") in names:
            row.action = "skip"
            row.issues.append("Already in People")
        if org is not None and org.already_contacted:
            row.issues.append(f"{org.name} was already contacted")
        if org is not None and any(p.organization_id == org.id for p in people):
            row.issues.append(f"Someone at {org.name} is already in People")
        key = org_key(v.get("organization", ""))
        if key:
            if key in seen_orgs:
                row.issues.append(f"Same organization as line {seen_orgs[key]}")
            else:
                seen_orgs[key] = i
        out.append(row)
    return out


def commit(project: Project, text: str, mapping: dict[str, str]) -> dict[str, int]:
    """Create people (and organizations) for every row whose action is create."""
    created = skipped = 0
    for row in preview(project, text, mapping):
        if row.action != "create":
            skipped += 1
            continue
        values = dict(row.values)
        org_name = values.pop("organization", "")
        org_id = ensure_org(project, org_name).id if org_name else ""
        project.create(
            "people",
            {**values, "organization_id": org_id, "source": "csv", "stage": "discovered"},
            actor="import",
        )
        created += 1
    return {"created": created, "skipped": skipped}


def rows_json(rows: list[Row]) -> list[dict]:
    return [asdict(r) for r in rows]
