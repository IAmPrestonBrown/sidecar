"""Outreach emails: templates from the outreach brief, drafts, checks, and metrics."""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta

from sidecar.briefs import FIRST_NAME, OPTIONAL, ORGANIZATION, parse_templates
from sidecar.models import EmailSettings, Message, Organization, Person
from sidecar.store import Project, StoreError

READING_WPM = 200
COWORKER_GAP_DAYS = 14
DASHES = ("\N{EM DASH}", "\N{EN DASH}")

# Stages a person moves through after the first email, used for metrics.
CONTACTED = {
    "sent",
    "follow_up_due",
    "replied",
    "interested",
    "scheduling",
    "confirmed",
    "completed",
    "declined",
    "unresponsive",
    "do_not_contact",
}
REPLIED = {"replied", "interested", "scheduling", "confirmed", "completed", "declined"}
POSITIVE = {"interested", "scheduling", "confirmed", "completed"}
CONFIRMED = {"confirmed", "completed"}
EARLY_STAGES = {"discovered", "researching", "ready_for_review"}
ACTIVE_MESSAGE = {"draft", "approved", "scheduled", "sent"}


@dataclass
class Check:
    name: str
    level: str  # "pass", "warn", or "fail"
    detail: str = ""


def ensure_templates(project: Project) -> EmailSettings:
    """Fill empty templates from the outreach brief and save them once."""
    email = project.meta.email
    if email.body_template and email.subject_template:
        return email
    brief = project.read_doc("outreach_brief")
    if not brief.strip():
        return email
    t = parse_templates(brief)
    email.subject_template = email.subject_template or t.subject
    email.body_template = email.body_template or t.body
    email.follow_up_template = email.follow_up_template or t.follow_up
    email.final_template = email.final_template or t.final
    project.save_meta()
    return email


def fill(template: str, person: Person, org: Organization | None, optional: str = "") -> str:
    text = template.replace(FIRST_NAME, person.first_name or person.name.split()[0])
    text = text.replace(ORGANIZATION, org.name if org else "your company")
    if optional.strip():
        text = text.replace(OPTIONAL, optional.strip())
    else:
        text = re.sub(rf"^[ \t]*{re.escape(OPTIONAL)}[ \t]*\n?", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def reading_seconds(text: str) -> float:
    return len(text.split()) / READING_WPM * 60


def _phrase_found(phrase: str, text: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])"
    return re.search(pattern, text, flags=re.I) is not None


def _parse_time(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def run_checks(project: Project, message: Message) -> list[Check]:
    """Checks from the outreach brief. Any fail blocks approval."""
    people = {p.id: p for p in project.all("people")}
    person = people.get(message.person_id)
    if person is None:
        return [Check("Recipient", "fail", "Person not found")]
    orgs = {o.id: o for o in project.all("organizations")}
    org = orgs.get(person.organization_id)
    text = f"{message.subject}\n{message.body}"
    checks: list[Check] = []

    dashes = [c for c in DASHES if c in text]
    checks.append(
        Check("No em dashes", "fail", "Contains an em or en dash")
        if dashes
        else Check("No em dashes", "pass")
    )

    response = message.kind == "response"
    banned = [p for p in project.meta.banned_phrases if p and _phrase_found(p, text)]
    # In a conversation the person may have asked about these, so it is only a note.
    checks.append(
        Check("No blocked phrases", "warn" if response else "fail", ", ".join(banned))
        if banned
        else Check("No blocked phrases", "pass")
    )

    leftovers = re.findall(r"\[[^\]\n]{2,60}\]|\{[a-z_]+\}", text)
    checks.append(
        Check("Template filled in", "fail", ", ".join(sorted(set(leftovers))))
        if leftovers
        else Check("Template filled in", "pass")
    )

    if not response:
        seconds = reading_seconds(message.body)
        limit = project.meta.email.max_reading_seconds
        level = "pass" if seconds <= limit else "warn"
        checks.append(Check("Reading time", level, f"{seconds:.0f} seconds"))

    if message.kind == "initial" and project.meta.email.body_template:
        base = fill(project.meta.email.body_template, person, org)
        base_lines = {line.strip() for line in base.splitlines() if line.strip()}
        extra = [
            ln for ln in message.body.splitlines() if ln.strip() and ln.strip() not in base_lines
        ]
        checks.append(
            Check("Close to the template", "warn", f"{len(extra)} lines differ from the template")
            if len(extra) > 1
            else Check("Close to the template", "pass")
        )

    if not person.email:
        checks.append(Check("Email address", "fail", "No email address"))
    elif person.email_confidence == "verified_direct" or response:
        checks.append(Check("Email address", "pass", person.email))
    else:
        reason = {"generic": "Generic inbox", "inferred_direct": "Inferred, not verified"}.get(
            person.email_confidence, "Verification not recorded"
        )
        checks.append(Check("Email address", "warn", reason))

    if person.do_not_contact or person.stage in ("declined", "do_not_contact"):
        checks.append(Check("Allowed to contact", "fail", "Marked do not contact or declined"))
    else:
        checks.append(Check("Allowed to contact", "pass"))

    messages = project.all("messages")
    if message.kind == "initial":
        duplicate = [
            m
            for m in messages
            if m.person_id == person.id
            and m.id != message.id
            and m.kind == "initial"
            and m.status in ACTIVE_MESSAGE
        ]
        checks.append(
            Check("First email to this person", "fail", "Another first email exists")
            if duplicate
            else Check("First email to this person", "pass")
        )

    if message.kind in ("follow_up", "final"):
        previous = last_sent(project, person.id)
        if previous is None:
            checks.append(
                Check("Earlier email sent", "fail", "Nothing has been sent to this person")
            )
        elif not previous.gmail_thread_id:
            checks.append(
                Check("Same thread", "warn", "The earlier email was sent outside Sidecar")
            )
        else:
            checks.append(Check("Same thread", "pass"))
        if has_reply(project, person.id):
            checks.append(Check("No reply yet", "fail", "This person has replied"))
        else:
            checks.append(Check("No reply yet", "pass"))

    if org is not None and message.kind == "initial":
        recent = datetime.now(UTC) - timedelta(days=COWORKER_GAP_DAYS)
        coworkers = []
        for m in messages:
            other = people.get(m.person_id)
            if (
                other is None
                or other.id == person.id
                or other.organization_id != org.id
                or m.kind != "initial"
                or m.status not in ACTIVE_MESSAGE
            ):
                continue
            created = _parse_time(m.created_at)
            if (message.wave_id and m.wave_id == message.wave_id) or (created and created > recent):
                coworkers.append(other.name)
        if coworkers:
            checks.append(
                Check("One contact per organization", "fail", ", ".join(sorted(set(coworkers))))
            )
        elif org.already_contacted:
            checks.append(
                Check("One contact per organization", "warn", f"{org.name} was contacted before")
            )
        else:
            checks.append(Check("One contact per organization", "pass"))
    return checks


def blocking(checks: list[Check]) -> bool:
    return any(c.level == "fail" for c in checks)


def draft_initial(project: Project, person_id: str, wave_id: str = "") -> Message:
    """Create a first-email draft for a person from the project's templates."""
    email = ensure_templates(project)
    if not email.body_template:
        raise StoreError("No email template. Add one in Settings or in the outreach brief.")
    person = project.get("people", person_id)
    assert isinstance(person, Person)
    org = None
    if person.organization_id:
        org = project.get("organizations", person.organization_id)
        assert isinstance(org, Organization)
    message = project.create(
        "messages",
        {
            "person_id": person.id,
            "wave_id": wave_id,
            "kind": "initial",
            "subject": fill(email.subject_template, person, org),
            "body": fill(email.body_template, person, org),
            "status": "draft",
        },
    )
    if person.stage in EARLY_STAGES:
        project.update("people", person.id, {"stage": "ready_for_review"})
    assert isinstance(message, Message)
    return message


def add_business_days(start: date, days: int) -> date:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def last_sent(project: Project, person_id: str) -> Message | None:
    sent = [
        m
        for m in project.all("messages")
        if m.person_id == person_id and m.status == "sent" and m.kind != "reply"
    ]
    return max(sent, key=lambda m: m.sent_at or m.updated_at, default=None)


def has_reply(project: Project, person_id: str) -> bool:
    return any(
        m.person_id == person_id and m.kind == "reply" and not m.bounce
        for m in project.all("messages")
    )


NEXT_KIND = {"initial": "follow_up", "follow_up": "final"}
FOLLOW_UP_STAGES = {"sent", "follow_up_due"}


def draft_follow_up(project: Project, person_id: str) -> Message:
    """Draft the next email in the sequence for a person who has not replied."""
    email = ensure_templates(project)
    previous = last_sent(project, person_id)
    if previous is None or previous.kind not in NEXT_KIND:
        raise StoreError("No earlier email to follow up on")
    kind = NEXT_KIND[previous.kind]
    template = email.follow_up_template if kind == "follow_up" else email.final_template
    if not template:
        raise StoreError(f"No {kind.replace('_', '-')} template. Add one in Settings.")
    person = project.get("people", person_id)
    assert isinstance(person, Person)
    org = project.get("organizations", person.organization_id) if person.organization_id else None
    first = next(
        (m for m in project.all("messages") if m.person_id == person_id and m.kind == "initial"),
        previous,
    )
    subject = first.subject or fill(email.subject_template, person, org)
    message = project.create(
        "messages",
        {
            "person_id": person.id,
            "wave_id": previous.wave_id,
            "kind": kind,
            # "Re:" only when the follow-up joins the original Gmail thread.
            "subject": subject
            if subject.lower().startswith("re:") or not previous.gmail_thread_id
            else f"Re: {subject}",
            "body": fill(template, person, org),
            "status": "draft",
            "gmail_thread_id": previous.gmail_thread_id,
        },
    )
    assert isinstance(message, Message)
    return message


def due_follow_ups(project: Project, today: date) -> list[Message]:
    """Draft follow-ups that are due today for people who have not replied.

    Drafts wait in the review queue like any other email.
    """
    pending = {
        m.person_id
        for m in project.all("messages")
        if m.kind in ("follow_up", "final") and m.status in ("draft", "approved", "scheduled")
    }
    drafted = []
    for person in project.all("people"):
        if (
            person.stage not in FOLLOW_UP_STAGES
            or person.do_not_contact
            or not person.next_action_due
            or person.next_action_due > today.isoformat()
            or person.id in pending
            or has_reply(project, person.id)
        ):
            continue
        previous = last_sent(project, person.id)
        if previous is None or previous.kind not in NEXT_KIND:
            continue
        try:
            drafted.append(draft_follow_up(project, person.id))
        except StoreError:
            continue
        project.update("people", person.id, {"stage": "follow_up_due"}, actor="outreach")
    return drafted


TRIAGE_ACTIONS = {
    "interested": "Agree on an interview time",
    "scheduling": "Confirm the interview time and time zone",
    "confirmed": "Prepare for the interview",
    "replied": "Answer the reply",
    "declined": "",
    "do_not_contact": "",
    "unresponsive": "",
}


def draft_response(project: Project, reply_id: str, body: str) -> Message:
    """Draft an answer to a reply, in the same Gmail thread. It waits for approval."""
    reply = project.get("messages", reply_id)
    if reply.kind != "reply":
        raise StoreError("Only replies can be answered")
    if not body.strip():
        raise StoreError("The response is empty")
    subject = reply.subject or "Re:"
    message = project.create(
        "messages",
        {
            "person_id": reply.person_id,
            "kind": "response",
            "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
            "body": body.strip(),
            "status": "draft",
            "gmail_thread_id": reply.gmail_thread_id,
            "in_reply_to": reply.rfc_message_id,
        },
    )
    assert isinstance(message, Message)
    return message


def triage_reply(project: Project, reply_id: str, stage: str = "") -> Message:
    """Mark a reply as handled, moving the person to the stage the user chose."""
    reply = project.get("messages", reply_id)
    if reply.kind != "reply":
        raise StoreError("Only replies can be triaged")
    if stage:
        if stage not in TRIAGE_ACTIONS:
            raise StoreError(f"Unknown stage {stage!r}")
        fields: dict = {"stage": stage, "next_action": TRIAGE_ACTIONS[stage], "next_action_due": ""}
        if stage == "do_not_contact":
            fields["do_not_contact"] = True
        project.update("people", reply.person_id, fields)
    updated = project.update("messages", reply_id, {"triaged": True})
    assert isinstance(updated, Message)
    return updated


def approve(project: Project, message_ids: list[str], confirm_inferred: bool = False) -> dict:
    """Approve drafts that pass their checks. Returns approved ids and reasons for the rest."""
    approved: list[str] = []
    refused: dict[str, str] = {}
    for mid in message_ids:
        message = project.get("messages", mid)
        assert isinstance(message, Message)
        if message.status != "draft":
            refused[mid] = f"Already {message.status}"
            continue
        checks = run_checks(project, message)
        failed = [c.name for c in checks if c.level == "fail"]
        unverified = any(c.name == "Email address" and c.level == "warn" for c in checks)
        if failed:
            refused[mid] = "Failed: " + ", ".join(failed)
            continue
        if unverified and not confirm_inferred:
            refused[mid] = "Email address needs confirmation"
            continue
        project.update(
            "messages", mid, {"status": "approved", "checks": [asdict(c) for c in checks]}
        )
        person = project.get("people", message.person_id)
        if person.stage in EARLY_STAGES | {"approved"}:
            project.update("people", person.id, {"stage": "approved"})
        approved.append(mid)
    return {"approved": approved, "refused": refused}


def skip(project: Project, message_ids: list[str]) -> list[str]:
    done = []
    for mid in message_ids:
        message = project.get("messages", mid)
        if message.status in ("draft", "approved", "failed"):
            project.update("messages", mid, {"status": "skipped"})
            done.append(mid)
    return done


def metrics(project: Project, today: date | None = None) -> dict:
    """Outreach numbers from the outreach brief, computed from stages and messages."""
    today = today or date.today()
    people = project.all("people")
    orgs = {o.id: o for o in project.all("organizations")}
    messages = project.all("messages")
    by_segment: dict[str, dict[str, int]] = {}
    for p in people:
        if p.stage not in CONTACTED:
            continue
        row = by_segment.setdefault(
            p.segment, {"contacted": 0, "replied": 0, "positive": 0, "completed": 0}
        )
        row["contacted"] += 1
        row["replied"] += p.stage in REPLIED
        row["positive"] += p.stage in POSITIVE
        row["completed"] += p.stage == "completed"
    completed = [p for p in people if p.stage == "completed"]
    completed_orgs = {p.organization_id for p in completed if p.organization_id}
    due = [
        p
        for p in people
        if p.stage == "follow_up_due"
        or (
            p.next_action_due
            and p.next_action_due <= today.isoformat()
            and p.stage not in {"completed", "declined", "do_not_contact", "unresponsive"}
        )
    ]
    return {
        "emails_sent": sum(1 for m in messages if m.status == "sent"),
        "drafts": sum(1 for m in messages if m.status == "draft"),
        "approved_waiting": sum(1 for m in messages if m.status == "approved"),
        "contacted": sum(1 for p in people if p.stage in CONTACTED),
        "replied": sum(1 for p in people if p.stage in REPLIED),
        "positive": sum(1 for p in people if p.stage in POSITIVE),
        "confirmed": sum(1 for p in people if p.stage in CONFIRMED),
        "completed": len(completed),
        "completed_organizations": sorted(orgs[o].name for o in completed_orgs if o in orgs),
        "by_segment": by_segment,
        "follow_ups_due": [
            {"id": p.id, "name": p.name, "next_action": p.next_action, "due": p.next_action_due}
            for p in due
        ],
        "segments_completed": sorted({p.segment for p in completed}),
    }
