"""Prospect research: Claude searches the public web and proposes people to contact.

Each run is stored as a research_runs record holding its suggestions. Nothing
is added to People until the user approves a suggestion.
"""

import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sidecar.models import ResearchRun
from sidecar.seed import ensure_org, find_org
from sidecar.store import Project, StoreError

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
MODEL = os.environ.get("SIDECAR_RESEARCH_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = 16000
MAX_TURNS = 6
MAX_SUGGESTIONS = 12
SEARCH_USD = 0.01  # per web search request
SCORES = [
    "information_value",
    "receptiveness",
    "contactability",
    "segment_diversity",
    "organizational_independence",
]
CONFIDENCE = ["verified_direct", "inferred_direct", "generic", "unavailable"]

_score = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": {"type": "string"},
    },
    "required": ["level", "reason"],
    "additionalProperties": False,
}
_source = {
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "title": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["url", "title", "quote"],
    "additionalProperties": False,
}
_prospect_fields = {
    "name": {"type": "string"},
    "role": {"type": "string"},
    "organization": {"type": "string"},
    "organization_website": {"type": "string"},
    "email": {"type": "string"},
    "email_confidence": {"type": "string", "enum": CONFIDENCE},
    "email_source_url": {"type": "string"},
    "phone": {"type": "string"},
    "segment": {"type": "string"},
    "segment_basis": {"type": "string"},
    "background": {"type": "string"},
    "why_useful": {"type": "string"},
    "why_receptive": {"type": "string"},
    "sources": {"type": "array", "items": _source},
    "scores": {
        "type": "object",
        "properties": dict.fromkeys(SCORES, _score),
        "required": SCORES,
        "additionalProperties": False,
    },
}
SUBMIT_TOOL = {
    "name": "submit_prospects",
    "description": "Submit the prospects found, once, after searching is complete.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "prospects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _prospect_fields,
                    "required": list(_prospect_fields),
                    "additionalProperties": False,
                },
            },
            "notes": {"type": "string"},
        },
        "required": ["prospects", "notes"],
        "additionalProperties": False,
    },
}


def tools(searches: int) -> list[dict]:
    return [
        {"type": "web_search_20260318", "name": "web_search", "max_uses": searches},
        {
            "type": "web_fetch_20260318",
            "name": "web_fetch",
            "max_uses": searches * 2,
            "blocked_domains": ["linkedin.com"],
            "max_content_tokens": 8000,
        },
        SUBMIT_TOOL,
    ]


def exclusions(project: Project) -> str:
    lines = []
    for org in sorted(project.all("organizations"), key=lambda o: o.name):
        names = ", ".join([org.name, *org.aliases])
        lines.append(f"- {names}" + (f" ({org.domain})" if org.domain else ""))
    return "\n".join(lines) or "(none)"


def build_request(project: Project, query: str, count: int) -> dict:
    system = (PROMPTS_DIR / "research.md").read_text()
    brief = project.read_doc("outreach_brief") or "(no outreach brief)"
    segments = "\n".join(f"- {s}" for s in project.meta.segments) or "(none defined)"
    context = (
        f"<outreach_brief>\n{brief}\n</outreach_brief>\n\n"
        f"<segments>\nUse one of these for each prospect's segment, or an empty string.\n"
        f"{segments}\n</segments>\n\n"
        f"<exclude>\nAlready known organizations. Do not propose anyone from these.\n"
        f"{exclusions(project)}\n</exclude>"
    )
    ask = f"Find up to {count} prospects.\n\nWho to look for: {query.strip()}"
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
        "system": [{"type": "text", "text": system}],
        "tools": tools(max(4, count)),
        "tool_choice": {"type": "auto"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": ask},
                ],
            }
        ],
    }


def cost(usage: dict, prices: Any) -> float:
    tokens = (
        usage.get("input_tokens", 0) * prices.input
        + usage.get("output_tokens", 0) * prices.output
        + usage.get("cache_read_input_tokens", 0) * prices.cache_read
        + usage.get("cache_creation_input_tokens", 0) * prices.cache_write
    ) / 1_000_000
    searches = (usage.get("server_tool_use") or {}).get("web_search_requests", 0)
    return tokens + searches * SEARCH_USD


def screen(project: Project, prospects: list[dict]) -> list[dict]:
    """Drop people and organizations the project already has, and repeats within the run."""
    people = project.all("people")
    emails = {p.email.lower() for p in people if p.email}
    names = {p.name.lower() for p in people}
    seen: set[str] = set()
    out = []
    for p in prospects:
        org = find_org(project, p["organization"]) if p["organization"] else None
        key = (p["organization"] or p["name"]).lower()
        if org is not None or key in seen:
            continue
        if (p["email"] and p["email"].lower() in emails) or p["name"].lower() in names:
            continue
        seen.add(key)
        segment = p["segment"] if p["segment"] in project.meta.segments else ""
        out.append({**p, "segment": segment, "status": "pending"})
    return out


def run(project: Project, run_id: str, create: Callable[[dict], Any], prices: Any) -> None:
    """Carry out one research run and store its suggestions on the run record."""
    record = project.get("research_runs", run_id)
    request = build_request(project, record.query, record.count)
    total = 0.0
    searches = 0
    try:
        for _ in range(MAX_TURNS):
            response = create(request)
            usage = response.usage.model_dump(exclude_none=True)
            total += cost(usage, prices)
            searches += (usage.get("server_tool_use") or {}).get("web_search_requests", 0)
            submitted = next(
                (
                    b.input
                    for b in response.content
                    if b.type == "tool_use" and b.name == SUBMIT_TOOL["name"]
                ),
                None,
            )
            if submitted is not None:
                suggestions = screen(project, submitted["prospects"])[:MAX_SUGGESTIONS]
                project.update(
                    "research_runs",
                    run_id,
                    {
                        "status": "done",
                        "suggestions": suggestions,
                        "notes": submitted.get("notes", ""),
                        "dropped": len(submitted["prospects"]) - len(suggestions),
                        "cost_usd": round(total, 4),
                        "searches": searches,
                    },
                    actor="research",
                )
                return
            if response.stop_reason == "pause_turn":
                # A long server-tool turn; send it back to let Claude continue.
                request = {
                    **request,
                    "messages": [
                        *request["messages"],
                        {"role": "assistant", "content": response.content},
                    ],
                }
                continue
            if response.stop_reason == "refusal":
                raise StoreError("Claude declined this research request")
            # Finished without submitting: ask once more for the tool call.
            request = {
                **request,
                "messages": [
                    *request["messages"],
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": "Call submit_prospects now with what you found."},
                ],
            }
        raise StoreError("The research run did not return any prospects")
    except Exception as exc:  # noqa: BLE001 - any failure is recorded on the run
        log.warning("Research run %s failed: %s", run_id, exc)
        project.update(
            "research_runs",
            run_id,
            {"status": "failed", "error": str(exc)[:500], "cost_usd": round(total, 4)},
            actor="research",
        )


def anthropic_create() -> tuple[Callable[[dict], Any], Any]:
    """A streaming Messages call and the configured prices, using the coach's API key."""
    import anthropic

    from coach.config import load_config

    cfg = load_config()
    if not cfg.anthropic_api_key:
        raise StoreError("ANTHROPIC_API_KEY is missing from ~/.config/sidecar/.env")
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key, timeout=900, max_retries=2)

    def create(request: dict) -> Any:
        with client.messages.stream(**request) as stream:
            return stream.get_final_message()

    return create, cfg.prices


def start(
    project: Project,
    query: str,
    count: int,
    create: Callable[[dict], Any],
    prices: Any,
) -> ResearchRun:
    if not query.strip():
        raise StoreError("Describe who to look for")
    stale = datetime.now(UTC) - timedelta(minutes=30)
    for r in project.all("research_runs"):
        if r.status != "running":
            continue
        # A run left over from an engine that was closed mid-run.
        if datetime.fromisoformat(r.created_at.replace("Z", "+00:00")) < stale:
            project.update("research_runs", r.id, {"status": "failed", "error": "Interrupted"})
        else:
            raise StoreError("A research run is already in progress")
    record = project.create(
        "research_runs",
        {"query": query.strip(), "status": "running", "count": min(max(count, 1), MAX_SUGGESTIONS)},
        actor="research",
    )
    assert isinstance(record, ResearchRun)
    threading.Thread(target=run, args=(project, record.id, create, prices), daemon=True).start()
    return record


def decide(project: Project, run_id: str, index: int, accept: bool) -> dict:
    """Add one suggestion to People, or reject it."""
    record = project.get("research_runs", run_id)
    suggestions = [dict(s) for s in record.suggestions]
    if not 0 <= index < len(suggestions):
        raise StoreError("No such suggestion")
    s = suggestions[index]
    if s["status"] != "pending":
        raise StoreError(f"Already {s['status']}")
    person_id = ""
    if accept:
        if find_org(project, s["organization"]) if s["organization"] else None:
            raise StoreError(f"{s['organization']} is already in this project")
        org_id = ""
        if s["organization"]:
            org = ensure_org(
                project,
                s["organization"],
                website=s["organization_website"],
                segment=s["segment"],
            )
            org_id = org.id
        sources = list(s["sources"])
        if s["email_source_url"] and not any(x["url"] == s["email_source_url"] for x in sources):
            sources.append(
                {"url": s["email_source_url"], "title": "Email address source", "quote": ""}
            )
        person = project.create(
            "people",
            {
                "name": s["name"],
                "first_name": s["name"].split()[0] if s["name"] else "",
                "organization_id": org_id,
                "role": s["role"],
                "email": s["email"],
                "email_confidence": s["email_confidence"] if s["email"] else "unavailable",
                "phone": s["phone"],
                "segment": s["segment"],
                "segment_basis": s["segment_basis"],
                "background": s["background"],
                "why_useful": s["why_useful"],
                "why_receptive": s["why_receptive"],
                "sources": sources,
                "scores": s["scores"],
                "researched_on": record.created_at[:10],
                "source": "research",
                "stage": "discovered",
            },
            actor="research",
        )
        person_id = person.id
    s["status"] = "added" if accept else "rejected"
    s["person_id"] = person_id
    suggestions[index] = s
    project.update("research_runs", run_id, {"suggestions": suggestions})
    return s
