"""Records stored in a project folder, one pydantic model per collection."""

import secrets
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


HypothesisKind = Literal["problem", "solution", "competing"]
HypothesisStatus = Literal["open", "supported", "weakened", "rejected", "parked"]
EmailConfidence = Literal["verified_direct", "inferred_direct", "generic", "unavailable"]
Stage = Literal[
    "discovered",
    "researching",
    "ready_for_review",
    "approved",
    "scheduled_to_send",
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
]
Level = Literal["high", "medium", "low"]
EvidenceType = Literal[
    "behavior", "incident", "opinion", "capability_claim", "artifact", "segment", "secondhand"
]
EvidenceBasis = Literal["statement", "observed", "artifact", "interpretation"]
Stance = Literal["supports", "contradicts", "mixed"]
ReviewStatus = Literal["proposed", "accepted", "rejected"]
# "reply" is a message received from the person; "response" is our answer to one.
MessageKind = Literal["initial", "follow_up", "final", "reply", "response"]
MessageStatus = Literal["draft", "approved", "scheduled", "sent", "failed", "skipped", "received"]

STRONG_TYPES = {"behavior", "incident"}


class Record(BaseModel):
    """Base for every stored record. Unknown fields are kept, not dropped."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Source(BaseModel):
    url: str = ""
    title: str = ""
    quote: str = ""


class Score(BaseModel):
    level: Level = "medium"
    reason: str = ""


class Scores(BaseModel):
    information_value: Score | None = None
    receptiveness: Score | None = None
    contactability: Score | None = None
    segment_diversity: Score | None = None
    organizational_independence: Score | None = None


class HistoryEntry(BaseModel):
    at: str = Field(default_factory=now_iso)
    text: str


class Hypothesis(Record):
    code: str
    title: str = ""
    statement: str
    kind: HypothesisKind = "problem"
    status: HypothesisStatus = "open"
    notes: str = ""
    sort: int = 0
    history: list[HistoryEntry] = []


class Organization(Record):
    name: str
    aliases: list[str] = []
    domain: str = ""
    website: str = ""
    segment: str = ""
    already_contacted: bool = False
    # Vendors, publishers, and regulators are sources but not independent
    # confirmations, so tallies leave them out of the organization count.
    independent: bool = True
    sources: list[Source] = []
    notes: str = ""


class Person(Record):
    name: str
    first_name: str = ""
    organization_id: str = ""
    role: str = ""
    email: str = ""
    email_confidence: EmailConfidence = "unavailable"
    phone: str = ""
    website: str = ""
    background: str = ""
    why_useful: str = ""
    why_receptive: str = ""
    segment: str = ""
    segment_basis: str = ""
    sources: list[Source] = []
    source: Literal["", "manual", "csv", "research", "referral", "brief"] = ""
    researched_on: str = ""
    time_zone: str = ""
    stage: Stage = "discovered"
    next_action: str = ""
    next_action_due: str = ""
    priority: Level = "medium"
    scores: Scores = Scores()
    do_not_contact: bool = False
    wave_id: str = ""
    notes: str = ""


class Interview(Record):
    person_id: str
    proposed_times: list[str] = []
    time_zone: str = ""
    confirmed_time: str = ""
    method: Literal["phone", "video", "in_person", ""] = ""
    details: str = ""
    completed: bool = False
    call_id: str = ""
    outcome: str = ""


class EvidenceLink(BaseModel):
    hypothesis_id: str
    stance: Stance
    # Set when this link was graded on its own. Otherwise strength follows the
    # evidence type and basis.
    strength: Literal["", "strong", "moderate", "weak"] = ""


class Evidence(Record):
    call_id: str = ""
    person_id: str = ""
    organization_id: str = ""
    at_seconds: float | None = None
    quote: str = ""
    note: str = ""
    type: EvidenceType = "opinion"
    basis: EvidenceBasis = "statement"
    source: Literal["call", "email", "manual", "import"] = "manual"
    review_status: ReviewStatus = "proposed"
    links: list[EvidenceLink] = []
    origin: str = ""


class Message(Record):
    person_id: str
    wave_id: str = ""
    kind: MessageKind = "initial"
    subject: str = ""
    body: str = ""
    status: MessageStatus = "draft"
    checks: list[dict] = []
    gmail_message_id: str = ""
    gmail_thread_id: str = ""
    # RFC 5322 Message-ID, used to thread follow-ups.
    rfc_message_id: str = ""
    # Responses only: the Message-ID being answered.
    in_reply_to: str = ""
    scheduled_for: str = ""
    sent_at: str = ""
    error: str = ""
    # Replies only.
    from_address: str = ""
    received_at: str = ""
    auto_reply: bool = False
    bounce: bool = False
    triaged: bool = True


class Wave(Record):
    name: str
    notes: str = ""


class Call(Record):
    person_id: str = ""
    title: str = ""
    started_at: str = ""
    duration_s: float = 0.0
    session_dir: str = ""
    status: Literal["planned", "recording", "finalizing", "done", "imported"] = "planned"
    planned_minutes: int = 30
    marks: int = 0
    cost_usd: float = 0.0


class ResearchRun(Record):
    query: str
    status: Literal["running", "done", "failed"] = "done"
    cost_usd: float = 0.0
    suggestion_ids: list[str] = []


COLLECTIONS: dict[str, tuple[type[Record], str]] = {
    "hypotheses": (Hypothesis, "hyp"),
    "organizations": (Organization, "org"),
    "people": (Person, "per"),
    "interviews": (Interview, "int"),
    "evidence": (Evidence, "evi"),
    "messages": (Message, "msg"),
    "waves": (Wave, "wav"),
    "calls": (Call, "cal"),
    "research_runs": (ResearchRun, "run"),
}


class CoachSettings(BaseModel):
    activity: Literal["quiet", "balanced", "active"] = "balanced"
    keyterms: list[str] = []


class EmailSettings(BaseModel):
    """Sender details and email templates.

    Templates use {first_name}, {organization}, and {optional_sentence}. A line
    holding only {optional_sentence} is dropped when the sentence is empty.
    """

    sender_name: str = ""
    footer_enabled: bool = False
    postal_address: str = ""
    opt_out_line: str = ""
    subject_template: str = ""
    body_template: str = ""
    follow_up_template: str = ""
    final_template: str = ""
    # Drafts that take longer than this to read get a note in the review queue.
    max_reading_seconds: int = 40


class SendingSettings(BaseModel):
    # Approved emails go out only while this is on.
    active: bool = False
    daily_cap: int = 30
    window_start: str = "08:00"
    window_end: str = "17:00"
    weekdays: list[int] = [0, 1, 2, 3, 4]
    min_gap_minutes: int = 3
    max_gap_minutes: int = 9


class ProjectMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    slug: str
    created_at: str = Field(default_factory=now_iso)
    coach: CoachSettings = CoachSettings()
    email: EmailSettings = EmailSettings()
    sending: SendingSettings = SendingSettings()
    banned_phrases: list[str] = []
    # Segment names from the research brief. People and organizations use one of
    # these, or an empty string when the segment is not known yet.
    segments: list[str] = []
    format_version: int = 1
