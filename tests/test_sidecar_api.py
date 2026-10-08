from fastapi.testclient import TestClient

from sidecar.api import TOKEN_HEADER, create_app
from sidecar.store import Workspace

TOKEN = "t" * 32


def client(tmp_path) -> TestClient:
    ws = Workspace(tmp_path)
    ws.create_project("Study")
    return TestClient(create_app(ws, TOKEN))


def auth() -> dict:
    return {TOKEN_HEADER: TOKEN}


def test_token_required(tmp_path) -> None:
    c = client(tmp_path)
    assert c.get("/health").status_code == 200
    assert c.get("/projects").status_code == 401
    assert c.get("/projects", headers={TOKEN_HEADER: "wrong"}).status_code == 401
    assert c.get("/projects", headers=auth()).json()[0]["slug"] == "study"


def test_record_crud_and_validation(tmp_path) -> None:
    c = client(tmp_path)
    base = "/projects/study/c/people"
    made = c.post(base, json={"name": "Dana Lee"}, headers=auth()).json()
    assert made["stage"] == "discovered"
    got = c.patch(f"{base}/{made['id']}", json={"stage": "approved"}, headers=auth())
    assert got.json()["stage"] == "approved"
    bad = c.patch(f"{base}/{made['id']}", json={"stage": "maybe"}, headers=auth())
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["field"] == "stage"
    assert c.get(f"{base}/nope", headers=auth()).status_code == 404
    assert c.get("/projects/study/c/bogus", headers=auth()).status_code == 404
    assert c.delete(f"{base}/{made['id']}", headers=auth()).json() == {"ok": True}
    assert c.get(base, headers=auth()).json() == []


def test_docs_meta_overview_tallies_export(tmp_path) -> None:
    c = client(tmp_path)
    assert c.put("/projects/study/docs/brief", json={"text": "# Brief"}, headers=auth()).is_success
    assert c.get("/projects/study/docs/brief", headers=auth()).json()["text"] == "# Brief"
    assert c.get("/projects/study/docs/secrets", headers=auth()).status_code == 404
    meta = c.patch("/projects/study", json={"sending": {"daily_cap": 20}}, headers=auth()).json()
    assert meta["sending"]["daily_cap"] == 20
    assert meta["sending"]["max_gap_minutes"] == 9
    h = c.post(
        "/projects/study/c/hypotheses", json={"code": "H1", "statement": "s"}, headers=auth()
    ).json()
    c.post(
        "/projects/study/c/evidence",
        json={
            "quote": "q",
            "type": "behavior",
            "review_status": "accepted",
            "links": [{"hypothesis_id": h["id"], "stance": "contradicts"}],
        },
        headers=auth(),
    )
    t = c.get("/projects/study/tallies", headers=auth()).json()[h["id"]]
    assert t["contradicts"] == {"strong": 1, "weak": 0}
    ov = c.get("/projects/study/overview", headers=auth()).json()
    assert ov["evidence_accepted"] == 1
    out = c.post("/projects/study/export", headers=auth()).json()
    assert out["json"].endswith(".json")
    assert out["markdown"].endswith(".md")
