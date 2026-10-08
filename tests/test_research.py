import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from sidecar import research
from sidecar.store import StoreError, Workspace

PRICES = SimpleNamespace(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)


def prospect(name: str, org: str, **over) -> dict:
    base = {
        "name": name,
        "role": "Head baker",
        "organization": org,
        "organization_website": f"https://{org.split()[0].lower()}.example",
        "email": f"{name.split()[0].lower()}@example.com",
        "email_confidence": "inferred_direct",
        "email_source_url": "https://example.com/team",
        "phone": "",
        "segment": "Bakery cafe",
        "segment_basis": "Menu lists coffee",
        "background": "Runs the morning bake",
        "why_useful": "Plans quantities daily",
        "why_receptive": "Posts about the job (inference)",
        "sources": [{"url": "https://example.com/team", "title": "Team", "quote": "Head baker"}],
        "scores": {k: {"level": "medium", "reason": "r"} for k in research.SCORES},
    }
    return base | over


@dataclass
class FakeResponse:
    stop_reason: str
    content: list
    usage: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(
            model_dump=lambda **_: {
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "server_tool_use": {"web_search_requests": 3},
            }
        )
    )


def wait(project, run_id: str) -> object:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = project.get("research_runs", run_id)
        if record.status != "running":
            return record
        time.sleep(0.02)
    raise AssertionError("run did not finish")


@pytest.fixture
def project(tmp_path):
    proj = Workspace(tmp_path).create_project("Research")
    proj.meta.segments = ["Bakery cafe", "Retail-only bakery"]
    proj.save_meta()
    proj.create("organizations", {"name": "Hearth & Crumb Bakery", "already_contacted": True})
    return proj


def test_request_shape(project) -> None:
    req = research.build_request(project, "Owners of small bakeries", 5)
    names = [t["name"] for t in req["tools"]]
    assert names == ["web_search", "web_fetch", "submit_prospects"]
    assert req["tools"][0]["type"] == "web_search_20260318"
    assert "Hearth & Crumb Bakery" in req["messages"][0]["content"][0]["text"]
    item = research.SUBMIT_TOOL["input_schema"]["properties"]["prospects"]["items"]
    assert set(item["required"]) == set(item["properties"])


def test_run_pauses_submits_and_screens(project) -> None:
    calls = []

    def create(request):
        calls.append(request)
        if len(calls) == 1:
            return FakeResponse("pause_turn", [SimpleNamespace(type="text", text="searching")])
        return FakeResponse(
            "tool_use",
            [
                SimpleNamespace(
                    type="tool_use",
                    name="submit_prospects",
                    input={
                        "prospects": [
                            prospect("Ana Ruiz", "Sunrise Bakery"),
                            prospect("Dana Brooks", "Hearth & Crumb Bakery"),
                            prospect("Ben Lee", "Sunrise Bakery"),
                            prospect("Cy Ng", "Rye House", segment="Not a segment"),
                        ],
                        "notes": "Few public emails",
                    },
                )
            ],
        )

    run = research.start(project, "Owners of small bakeries", 5, create, PRICES)
    done = wait(project, run.id)
    assert done.status == "done"
    assert [s["name"] for s in done.suggestions] == ["Ana Ruiz", "Cy Ng"]
    assert done.suggestions[1]["segment"] == ""
    assert done.dropped == 2
    assert done.searches == 6
    assert done.cost_usd == pytest.approx(2 * (2.0 + 0.03))
    assert calls[1]["messages"][-1]["role"] == "assistant"

    added = research.decide(project, run.id, 0, accept=True)
    assert added["status"] == "added"
    person = project.get("people", added["person_id"])
    assert person.source == "research"
    assert person.email_confidence == "inferred_direct"
    assert person.scores.receptiveness.level == "medium"
    assert project.get("organizations", person.organization_id).name == "Sunrise Bakery"
    assert research.decide(project, run.id, 1, accept=False)["status"] == "rejected"
    with pytest.raises(StoreError, match="Already"):
        research.decide(project, run.id, 0, accept=True)


def test_failure_is_recorded(project) -> None:
    def create(request):
        raise RuntimeError("overloaded")

    run = research.start(project, "Bakers", 3, create, PRICES)
    failed = wait(project, run.id)
    assert failed.status == "failed"
    assert "overloaded" in failed.error


def test_one_run_at_a_time(project) -> None:
    project.create("research_runs", {"query": "x", "status": "running"})
    with pytest.raises(StoreError, match="in progress"):
        research.start(project, "Bakers", 3, lambda r: None, PRICES)
