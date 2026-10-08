"""Read research and outreach briefs.

Briefs are Markdown files split into sections by headings. Sidecar looks for these
sections, matching heading text without regard to case or numbering:

Research brief
    ``## H1 - Title`` followed by a paragraph, one per hypothesis. Add
    ``(solution)`` to the end of a heading to mark a solution hypothesis.
    ``Competing explanation``: the first paragraph, quotes optional.
    ``Segments``: a bullet list.

Outreach brief
    ``Email``: a ``Subject:`` line, then the body.
    ``Follow-up`` and ``Final note``: bodies.
    ``Banned phrases``: a bullet list.
    ``Already contacted``: organizations, one per bullet.
    ``Already emailed`` and ``Drafted``: ``Name, Organization`` bullets.
    ``Interview leads``: ``Name, Organization: status`` bullets.

Email bodies use ``[First Name]``, ``[Organization]``, and a line holding only
``[Optional sentence]``.
"""

import re
from dataclasses import dataclass, field

# Hyphen, en dash, or em dash between a hypothesis code and its title.
DASH = "[-\N{EN DASH}\N{EM DASH}]"

FIRST_NAME = "{first_name}"
ORGANIZATION = "{organization}"
OPTIONAL = "{optional_sentence}"


@dataclass
class ParsedHypothesis:
    code: str
    title: str
    statement: str
    kind: str = "problem"


@dataclass
class OutreachSeed:
    contacted_orgs: list[str] = field(default_factory=list)
    emailed_people: list[tuple[str, str]] = field(default_factory=list)
    drafted: list[tuple[str, str]] = field(default_factory=list)
    leads: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class Templates:
    subject: str = ""
    body: str = ""
    follow_up: str = ""
    final: str = ""


def _heading_key(text: str) -> str:
    """Heading text without numbering or punctuation, lowercased."""
    text = re.sub(r"^\s*\d+[.)]?\s*", "", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def sections(brief: str) -> dict[str, str]:
    """Map each heading (normalized) to the text under it, up to the next heading."""
    out: dict[str, str] = {}
    parts = re.split(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", brief, flags=re.M)
    for title, body in zip(parts[1::2], parts[2::2], strict=True):
        out.setdefault(_heading_key(title), body.strip("\n"))
    return out


def _section(brief: str, *names: str) -> str:
    found = sections(brief)
    for name in names:
        if name in found:
            return found[name]
    return ""


def bullets(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s*[-*]\s+(.+)$", text, re.M)]


def _strip_period(text: str) -> str:
    """Drop a sentence-ending period but keep abbreviations like "Co."."""
    if text.endswith(("Co.", "Inc.", "Corp.", "Ltd.")):
        return text
    return text.rstrip(".")


def _name_and_org(item: str) -> tuple[str, str]:
    name, _, org = item.partition(",")
    return name.strip(), _strip_period(org.strip())


def parse_hypotheses(brief: str) -> list[ParsedHypothesis]:
    found: dict[str, ParsedHypothesis] = {}
    heading = re.compile(rf"^#{{2,3}}\s*(H\d+)\s*{DASH}\s*(.+?)\s*$", re.M)
    for m in heading.finditer(brief):
        title = m.group(2)
        kind = "problem"
        if re.search(r"\(solution\)$", title, re.I):
            kind = "solution"
            title = title[: -len("(solution)")].rstrip()
        rest = brief[m.end() :].lstrip("\n")
        para = rest.split("\n\n", 1)[0].strip()
        if para and not para.startswith("#"):
            found.setdefault(
                m.group(1), ParsedHypothesis(m.group(1), title, " ".join(para.split()), kind)
            )
    return sorted(found.values(), key=lambda h: int(h.code[1:]))


def parse_competing(brief: str) -> str:
    text = _section(brief, "competing explanation")
    para = text.split("\n\n", 1)[0].strip()
    return " ".join(para.strip('"“”').split())


def parse_segments(brief: str) -> list[str]:
    return bullets(_section(brief, "segments"))


def parse_banned(brief: str) -> list[str]:
    return bullets(_section(brief, "banned phrases"))


def parse_outreach(brief: str) -> OutreachSeed:
    seed = OutreachSeed()
    seed.contacted_orgs = [_strip_period(b) for b in bullets(_section(brief, "already contacted"))]
    seed.emailed_people = [_name_and_org(b) for b in bullets(_section(brief, "already emailed"))]
    seed.drafted = [_name_and_org(b) for b in bullets(_section(brief, "drafted"))]
    for item in bullets(_section(brief, "interview leads")):
        who, _, status = item.partition(":")
        name, org = _name_and_org(who)
        seed.leads.append((name, org, status.strip().rstrip(".")))
    return seed


def _placeholders(body: str) -> str:
    body = re.sub(r"\[First Name\]", FIRST_NAME, body, flags=re.I)
    body = re.sub(r"^\[Optional[^\]]*\]\s*$", OPTIONAL, body, flags=re.M | re.I)
    return re.sub(r"\[(?:Organization|Company)\]", ORGANIZATION, body, flags=re.I)


def parse_templates(brief: str) -> Templates:
    email = _section(brief, "email", "email template")
    subject = ""
    m = re.search(r"^\s*Subject:\s*(.+?)\s*$", email, re.M)
    if m:
        subject = m.group(1)
        email = email[m.end() :]
    return Templates(
        subject=subject,
        body=_placeholders(email.strip()),
        follow_up=_placeholders(_section(brief, "follow up").strip()),
        final=_placeholders(_section(brief, "final note").strip()),
    )
