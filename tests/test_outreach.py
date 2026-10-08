import json
from datetime import date
from pathlib import Path

import pytest

from sidecar import csv_import, outreach, sessions
from sidecar.backup import backup_workspace, prune
from sidecar.seed import create_from_briefs
from sidecar.store import StoreError, Workspace

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = (ROOT / "examples" / "research_brief.md").read_text()
OUTREACH = (ROOT / "examples" / "outreach_brief.md").read_text()


@pytest.fixture
def project(tmp_path):
    return create_from_briefs(Workspace(tmp_path), "Example study", RESEARCH, OUTREACH)


def add_person(project, name, org_name, email="a@example.com", confidence="verified_direct"):
    org = project.create("organizations", {"name": org_name})
    return project.create(
        "people",
        {
            "name": name,
            "first_name": name.split()[0],
            "organization_id": org.id,
            "email": email,
            "email_confidence": confidence,
        },
    )


def checks_by_name(project, message):
    return {c.name: c for c in outreach.run_checks(project, message)}


def test_templates_come_from_the_outreach_brief(project) -> None:
    email = outreach.ensure_templates(project)
    assert email.subject_template == "question about planning the daily bake"
    assert "{organization}" in email.body_template
    assert project.meta.email.final_template


def test_fill_drops_empty_optional_line(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery")
    org = project.get("organizations", person.organization_id)
    template = "Hi {first_name},\n\nAt {organization}.\n\n{optional_sentence}\n\nThanks,\nJordan"
    assert (
        outreach.fill(template, person, org) == "Hi Ana,\n\nAt Sunrise Bakery.\n\nThanks,\nJordan"
    )
    filled = outreach.fill(template, person, org, "You bake for two cafes.")
    assert "You bake for two cafes." in filled


def test_draft_passes_checks_and_approves(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery")
    message = outreach.draft_initial(project, person.id)
    assert "Hi Ana," in message.body
    assert "Sunrise Bakery" in message.body
    assert project.get("people", person.id).stage == "ready_for_review"
    checks = checks_by_name(project, message)
    assert not outreach.blocking(list(checks.values())), checks
    result = outreach.approve(project, [message.id])
    assert result["approved"] == [message.id]
    assert project.get("messages", message.id).status == "approved"
    assert project.get("people", person.id).stage == "approved"


def test_checks_catch_brief_violations(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery")
    message = outreach.draft_initial(project, person.id)
    body = message.body + "\n\nA quick chat \N{EM DASH} our app [Thing] helps."
    edited = project.update("messages", message.id, {"body": body})
    checks = checks_by_name(project, edited)
    assert checks["No em dashes"].level == "fail"
    assert "quick chat" in checks["No blocked phrases"].detail
    assert "app" in checks["No blocked phrases"].detail
    assert checks["Template filled in"].level == "fail"
    assert outreach.approve(project, [message.id])["approved"] == []


def test_blocked_phrase_needs_whole_word(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery")
    message = outreach.draft_initial(project, person.id)
    edited = project.update("messages", message.id, {"body": message.body + "\nI'd appreciate it."})
    assert checks_by_name(project, edited)["No blocked phrases"].level == "pass"


def test_inferred_email_needs_confirmation(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery", confidence="inferred_direct")
    message = outreach.draft_initial(project, person.id)
    first = outreach.approve(project, [message.id])
    assert first["refused"][message.id] == "Email address needs confirmation"
    assert outreach.approve(project, [message.id], confirm_inferred=True)["approved"]


def test_missing_email_and_do_not_contact_block(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery", email="")
    message = outreach.draft_initial(project, person.id)
    assert checks_by_name(project, message)["Email address"].level == "fail"
    project.update("people", person.id, {"email": "a@x.com", "do_not_contact": True})
    assert checks_by_name(project, message)["Allowed to contact"].level == "fail"


def test_one_contact_per_organization(project) -> None:
    first = add_person(project, "Ana Ruiz", "Sunrise Bakery")
    coworker = project.create(
        "people",
        {
            "name": "Ben Lee",
            "organization_id": first.organization_id,
            "email": "b@x.com",
            "email_confidence": "verified_direct",
        },
    )
    outreach.draft_initial(project, first.id)
    second = outreach.draft_initial(project, coworker.id)
    check = checks_by_name(project, second)["One contact per organization"]
    assert check.level == "fail"
    assert "Ana Ruiz" in check.detail


def test_already_contacted_org_warns(project) -> None:
    dana = next(p for p in project.all("people") if p.name == "Dana Brooks")
    project.update("people", dana.id, {"email": "d@x.com", "email_confidence": "verified_direct"})
    message = outreach.draft_initial(project, dana.id)
    assert checks_by_name(project, message)["One contact per organization"].level == "warn"


def test_duplicate_first_email_blocked(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery")
    outreach.draft_initial(project, person.id)
    again = outreach.draft_initial(project, person.id)
    assert checks_by_name(project, again)["First email to this person"].level == "fail"
    outreach.skip(project, [again.id])
    assert project.get("messages", again.id).status == "skipped"


def test_metrics(project) -> None:
    a = add_person(project, "Ana Ruiz", "Sunrise Bakery")
    b = add_person(project, "Ben Lee", "Elm Street Bakery")
    project.update("people", a.id, {"stage": "completed", "segment": "Bakery cafe"})
    project.update("people", b.id, {"stage": "sent", "next_action_due": "2026-01-01"})
    m = outreach.metrics(project, today=date(2026, 10, 8))
    assert m["completed"] == 1
    assert m["completed_organizations"] == ["Sunrise Bakery"]
    assert m["by_segment"]["Bakery cafe"]["completed"] == 1
    assert m["contacted"] >= 2
    assert any(f["name"] == "Ben Lee" for f in m["follow_ups_due"])


def test_csv_preview_and_commit(project) -> None:
    text = (
        "Full Name,Company,Email,Title,Notes\n"
        "Ana Ruiz,Sunrise Bakery,ana@oak.example,Head baker,met at expo\n"
        "Dana Brooks,Hearth & Crumb Bakery,,Manager,\n"
        ",Nameless Bakery,x@y.example,,\n"
        "Ben Lee,Sunrise Bakery,ben@oak.example,,\n"
    )
    headers, _ = csv_import.read_rows(text)
    mapping = csv_import.guess_mapping(headers)
    assert mapping == {
        "Full Name": "name",
        "Company": "organization",
        "Email": "email",
        "Title": "role",
        "Notes": "notes",
    }
    rows = csv_import.preview(project, text, mapping)
    assert [r.action for r in rows] == ["create", "skip", "skip", "create"]
    assert any("already contacted" in i for i in rows[1].issues)
    assert rows[3].issues == ["Same organization as line 2"]
    result = csv_import.commit(project, text, mapping)
    assert result == {"created": 2, "skipped": 2}
    ana = next(p for p in project.all("people") if p.name == "Ana Ruiz")
    assert ana.source == "csv"
    assert ana.email_confidence == "inferred_direct"
    assert project.get("organizations", ana.organization_id).name == "Sunrise Bakery"


def write_session(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(
        json.dumps(
            {
                "interviewee": "Dana",
                "organization": "Hearth",
                "started_at": "2026-10-01T10:00:00",
                "duration_s": 1800,
                "planned_minutes": 30,
                "costs": {"coach_usd": 0.5},
            }
        )
    )
    (folder / "marks.jsonl").write_text('{"at": 60}\n')
    items = [
        {
            "at": "02:05",
            "stance": "SUPPORTS",
            "hypotheses": ["H1", "H2"],
            "type": "BEHAVIOR",
            "note": "Uses four tools",
            "quote": "I juggle four tools",
        },
        {
            "at": "05:00",
            "stance": "NEW",
            "hypotheses": ["NEW"],
            "type": "OPINION",
            "note": "Dislikes phones",
            "quote": "Phones are the worst",
        },
    ]
    (folder / "evidence.jsonl").write_text("\n".join(json.dumps(i) for i in items) + "\n")
    return folder


def test_import_session_creates_call_and_proposed_evidence(project, tmp_path) -> None:
    folder = write_session(tmp_path / "rec" / "2026-10-01_1000_dana")
    call = sessions.import_session(project, folder)
    dana = next(p for p in project.all("people") if p.name == "Dana Brooks")
    assert call.person_id == dana.id
    assert call.marks == 1
    evidence = [e for e in project.all("evidence") if e.call_id == call.id]
    assert len(evidence) == 2
    assert all(e.review_status == "proposed" for e in evidence)
    first = next(e for e in evidence if e.at_seconds == 125)
    assert len(first.links) == 2
    assert first.links[0].stance == "supports"
    with pytest.raises(StoreError, match="already imported"):
        sessions.import_session(project, folder)


def test_backup_once_per_day_and_prune(tmp_path) -> None:
    root = tmp_path / "projects"
    ws = Workspace(root)
    ws.create_project("One")
    (root / "one" / "exports" / "big.json").write_text("{}")
    dest = tmp_path / "backups"
    made = backup_workspace(root, dest, today=date(2026, 10, 8))
    assert made == dest / "2026-10-08"
    assert (made / "one" / "project.json").exists()
    assert not (made / "one" / "exports").exists()
    assert backup_workspace(root, dest, today=date(2026, 10, 8)) is None
    (dest / "2026-09-01").mkdir()
    removed = prune(dest, date(2026, 10, 8))
    assert removed == [dest / "2026-09-01"]
    assert made.exists()


def test_address_without_recorded_verification_needs_confirmation(project) -> None:
    person = add_person(project, "Ana Ruiz", "Sunrise Bakery", confidence="unavailable")
    message = outreach.draft_initial(project, person.id)
    assert checks_by_name(project, message)["Email address"].detail == "Verification not recorded"
    assert outreach.approve(project, [message.id])["approved"] == []
