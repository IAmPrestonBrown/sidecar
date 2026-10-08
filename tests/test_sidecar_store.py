import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sidecar.briefs import (
    parse_banned,
    parse_competing,
    parse_hypotheses,
    parse_outreach,
    parse_segments,
    parse_templates,
)
from sidecar.export import export_project, tallies
from sidecar.seed import create_from_briefs, find_org
from sidecar.store import NotFoundError, StoreError, Workspace

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = (ROOT / "examples" / "research_brief.md").read_text()
OUTREACH = (ROOT / "examples" / "outreach_brief.md").read_text()


def test_crud_roundtrip_and_atomic_files(tmp_path) -> None:
    ws = Workspace(tmp_path)
    proj = ws.create_project("Test Study")
    org = proj.create("organizations", {"name": "Acme Processing"})
    per = proj.create("people", {"name": "Dana Lee", "organization_id": org.id})
    assert per.id.startswith("per_")
    proj.update("people", per.id, {"stage": "approved", "id": "hacked"})
    again = Workspace(tmp_path).project("test-study")
    assert again.get("people", per.id).stage == "approved"
    raw = json.loads((tmp_path / "test-study" / "people.json").read_text())
    assert raw[0]["name"] == "Dana Lee"
    assert (tmp_path / "test-study" / ".sidecar" / "people.json.bak").exists()
    lines = (tmp_path / "test-study" / "activity.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["fields"] == ["stage"]
    proj.delete("people", per.id)
    with pytest.raises(NotFoundError):
        proj.get("people", per.id)


def test_invalid_values_rejected_and_unknown_fields_kept(tmp_path) -> None:
    proj = Workspace(tmp_path).create_project("X")
    with pytest.raises(ValidationError, match="stage"):
        proj.create("people", {"name": "A", "stage": "maybe"})
    rec = proj.create("people", {"name": "B", "custom_field": 7})
    assert proj.get("people", rec.id).model_dump()["custom_field"] == 7
    with pytest.raises(StoreError):
        Workspace(tmp_path).create_project("X")


def test_external_edit_is_reloaded(tmp_path) -> None:
    proj = Workspace(tmp_path).create_project("Y")
    rec = proj.create("waves", {"name": "Wave 1"})
    path = tmp_path / "y" / "waves.json"
    data = json.loads(path.read_text())
    data[0]["name"] = "Edited by hand"
    path.write_text(json.dumps(data))
    import os

    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert proj.get("waves", rec.id).name == "Edited by hand"


def test_parse_example_brief_hypotheses() -> None:
    hyps = parse_hypotheses(RESEARCH)
    assert [h.code for h in hyps] == ["H1", "H2", "H3", "H4"]
    assert hyps[0].title == "Plans come from memory"
    assert hyps[3].title == "A short daily suggestion would be used"
    assert hyps[3].kind == "solution"
    assert all(h.kind == "problem" for h in hyps[:3])
    assert parse_competing(RESEARCH).startswith("Leftovers are a choice.")
    assert parse_segments(RESEARCH) == [
        "Bakery cafe",
        "Retail-only bakery",
        "Retail and wholesale",
        "Market stall or pop-up",
    ]


def test_parse_em_dash_headings() -> None:
    brief = "## H1 \u2014 Speed\n\nThings are slow.\n\n## H2 \u2013 Cost\n\nThings cost too much.\n"
    assert [(h.code, h.title) for h in parse_hypotheses(brief)] == [("H1", "Speed"), ("H2", "Cost")]


def test_parse_outreach_brief() -> None:
    seed = parse_outreach(OUTREACH)
    assert seed.contacted_orgs == [
        "Hearth & Crumb Bakery",
        "Second Rise Bakehouse",
        "Millstone Bread Co. / Millstone Bakery",
    ]
    assert seed.emailed_people == [("Maya Collins", "Larkspur Bakery")]
    assert seed.drafted == [
        ("Sam Ortega", "Golden Crust Bakery"),
        ("Priya Shah", "Oak Lane Bakehouse"),
    ]
    assert seed.leads[0] == ("Dana Brooks", "Hearth & Crumb Bakery", "agreed to a phone interview")
    assert parse_banned(OUTREACH)[:2] == ["quick chat", "touch base"]


def test_parse_templates() -> None:
    t = parse_templates(OUTREACH)
    assert t.subject == "question about planning the daily bake"
    assert t.body.startswith("Hi {first_name},")
    assert "{organization}" in t.body
    assert "\n{optional_sentence}\n" in t.body
    assert t.body.endswith("Best,\nAlex")
    assert t.follow_up.startswith("Hi {first_name},")
    assert "{organization}" in t.final


def test_org_abbreviations_keep_their_period() -> None:
    brief = "## Drafted\n\n- Ana Ruiz, Paws Co.\n"
    assert parse_outreach(brief).drafted == [("Ana Ruiz", "Paws Co.")]


def test_seed_project_links_leads_to_contacted_orgs(tmp_path) -> None:
    ws = Workspace(tmp_path)
    proj = create_from_briefs(ws, "Example study", RESEARCH, OUTREACH)
    hyps = {h.code: h for h in proj.all("hypotheses")}
    assert set(hyps) == {"H1", "H2", "H3", "H4", "CE"}
    assert "Full shelves" in hyps["CE"].statement
    assert len(proj.meta.segments) == 4
    assert "touch base" in proj.meta.banned_phrases
    people = {p.name: p for p in proj.all("people")}
    dana_org = proj.get("organizations", people["Dana Brooks"].organization_id)
    assert dana_org.name == "Hearth & Crumb Bakery"
    luis_org = proj.get("organizations", people["Luis Romero"].organization_id)
    assert luis_org.name == "Second Rise Bakehouse"
    assert people["Sam Ortega"].stage == "ready_for_review"
    assert people["Maya Collins"].stage == "sent"
    assert people["Dana Brooks"].stage == "interested"
    millstone = find_org(proj, "Millstone Bakery")
    assert millstone is not None
    assert millstone.already_contacted
    assert millstone.name == "Millstone Bread Co."
    assert find_org(proj, "hearth & crumb bakery, inc.") == dana_org
    assert len([o for o in proj.all("organizations") if o.already_contacted]) == 4


def test_tallies_count_independent_orgs_and_strength(tmp_path) -> None:
    proj = Workspace(tmp_path).create_project("Z")
    h = proj.create("hypotheses", {"code": "H1", "statement": "s"})
    o1 = proj.create("organizations", {"name": "A"})
    o2 = proj.create("organizations", {"name": "B"})
    p1 = proj.create("people", {"name": "p1", "organization_id": o1.id})
    p2 = proj.create("people", {"name": "p2", "organization_id": o1.id})
    p3 = proj.create("people", {"name": "p3", "organization_id": o2.id})
    link = [{"hypothesis_id": h.id, "stance": "supports"}]
    for pid, typ, basis in (
        (p1.id, "behavior", "statement"),
        (p2.id, "incident", "statement"),
        (p3.id, "opinion", "statement"),
        (p3.id, "behavior", "interpretation"),
    ):
        proj.create(
            "evidence",
            {
                "person_id": pid,
                "type": typ,
                "basis": basis,
                "review_status": "accepted",
                "links": link,
            },
        )
    proj.create("evidence", {"person_id": p3.id, "type": "behavior", "links": link})
    t = tallies(proj, h.id)
    assert t["supports"] == {"strong": 2, "weak": 2}
    assert t["organizations"] == 2


def test_export_writes_json_and_markdown(tmp_path) -> None:
    ws = Workspace(tmp_path)
    proj = create_from_briefs(ws, "Example study", RESEARCH, OUTREACH)
    json_path, md_path = export_project(proj)
    data = json.loads(json_path.read_text())
    assert data["format"] == "sidecar-project-export"
    assert len(data["hypotheses"]) == 5
    assert "Sam Ortega" in md_path.read_text()
    assert "### H1: Plans come from memory" in md_path.read_text()


def test_parse_hyphen_headings_and_solution_marker() -> None:
    brief = (
        "# Study\n\n## H1 - Pricing pain\n\nSmall shops find pricing tools too expensive.\n\n"
        "## H2 - Workarounds (solution)\n\nThey would pay for help.\n"
    )
    hyps = parse_hypotheses(brief)
    assert [(h.code, h.title, h.kind) for h in hyps] == [
        ("H1", "Pricing pain", "problem"),
        ("H2", "Workarounds", "solution"),
    ]


def test_shipped_prompts_and_examples_name_no_real_interviewer() -> None:
    texts = [p.read_text() for p in (ROOT / "prompts").glob("*.md")]
    texts += [RESEARCH, OUTREACH]
    for text in texts:
        assert "Preston" not in text
