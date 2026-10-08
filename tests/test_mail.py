import base64
import json
import random
from datetime import date, datetime
from email import message_from_bytes
from zoneinfo import ZoneInfo

import httpx2
import pytest

from sidecar import outreach
from sidecar.gmail import Gmail, GmailError, NewMessage, NotConnectedError, build_mime
from sidecar.mail import Mailer
from sidecar.store import Workspace

PACIFIC = ZoneInfo("America/Los_Angeles")
# Wednesday, mid-morning.
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=PACIFIC)


class DictStore:
    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}

    def get(self, account: str) -> str | None:
        return self.tokens.get(account)

    def set(self, account: str, token: str) -> None:
        self.tokens[account] = token

    def delete(self, account: str) -> None:
        self.tokens.pop(account, None)


def decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def test_build_mime_threads_follow_ups() -> None:
    raw, message_id = build_mime(
        "me@example.com", "Alex", "ana@example.com", "Re: hello", "Body", "<a@b>"
    )
    msg = message_from_bytes(decode(raw))
    assert msg["From"] == "Alex <me@example.com>"
    assert msg["In-Reply-To"] == "<a@b>"
    assert msg["Message-ID"] == message_id
    assert message_id.endswith("@example.com>")


def make_gmail(tmp_path, handler) -> Gmail:
    (tmp_path / "google_client.json").write_text(
        json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}})
    )
    return Gmail(tmp_path, DictStore(), httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_connect_send_and_read_replies(tmp_path) -> None:
    sent: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/token":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if form["grant_type"] == "authorization_code":
                assert form["code_verifier"] == "verifier"
                return httpx2.Response(
                    200,
                    json={
                        "access_token": "at",
                        "refresh_token": "rt",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/gmail.send "
                        "https://www.googleapis.com/auth/gmail.readonly",
                    },
                )
        if path.endswith("/profile"):
            return httpx2.Response(200, json={"emailAddress": "me@example.com", "historyId": "10"})
        if path.endswith("/messages/send"):
            sent.append(json.loads(request.content))
            return httpx2.Response(200, json={"id": "m1", "threadId": "t1"})
        if path.endswith("/history"):
            assert request.url.params["startHistoryId"] == "10"
            return httpx2.Response(
                200,
                json={
                    "historyId": "12",
                    "history": [
                        {
                            "messagesAdded": [
                                {"message": {"id": "m1", "threadId": "t1", "labelIds": ["SENT"]}}
                            ]
                        },
                        {
                            "messagesAdded": [
                                {"message": {"id": "r1", "threadId": "t1", "labelIds": ["INBOX"]}}
                            ]
                        },
                        {
                            "messagesAdded": [
                                {
                                    "message": {
                                        "id": "x1",
                                        "threadId": "other",
                                        "labelIds": ["INBOX"],
                                    }
                                }
                            ]
                        },
                    ],
                },
            )
        if path.endswith("/messages/r1"):
            text = base64.urlsafe_b64encode(b"Sure, Tuesday works.").decode()
            return httpx2.Response(
                200,
                json={
                    "id": "r1",
                    "threadId": "t1",
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [
                            {"name": "From", "value": "Ana <ana@example.com>"},
                            {"name": "Subject", "value": "Re: hello"},
                        ],
                        "parts": [{"mimeType": "text/plain", "body": {"data": text}}],
                    },
                },
            )
        raise AssertionError(f"unexpected {request.method} {request.url}")

    gmail = make_gmail(tmp_path, handler)
    assert gmail.status()["configured"]
    assert not gmail.status()["connected"]
    client = gmail.client()
    assert client is not None
    assert (
        gmail.finish_connect(client, "code", "verifier", "http://127.0.0.1:1/") == "me@example.com"
    )
    assert gmail.status() | {"client_file": ""} == {
        "configured": True,
        "client_file": "",
        "connected": True,
        "email": "me@example.com",
        "connecting": False,
    }

    out = gmail.send("ana@example.com", "hello", "Body", "Alex")
    assert out["thread_id"] == "t1"
    assert "threadId" not in sent[0]
    assert message_from_bytes(decode(sent[0]["raw"]))["To"] == "ana@example.com"

    replies = gmail.new_messages({"t1"}, known={"m1"})
    assert [r.id for r in replies] == ["r1"]
    assert replies[0].body == "Sure, Tuesday works."
    assert not replies[0].bounce
    assert gmail.state()["history_id"] == "12"


def test_missing_scope_is_refused(tmp_path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "scope": "https://www.googleapis.com/auth/gmail.send",
            },
        )

    gmail = make_gmail(tmp_path, handler)
    with pytest.raises(GmailError, match="Both Gmail permissions"):
        gmail.finish_connect(gmail.client(), "code", "v", "http://127.0.0.1:1/")


def test_expired_token_disconnects(tmp_path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"error": "invalid_grant"})

    gmail = make_gmail(tmp_path, handler)
    gmail.save_state(email="me@example.com")
    gmail.store.set("me@example.com", "rt")
    assert gmail.status()["connected"]
    with pytest.raises(NotConnectedError, match="Connect again"):
        gmail.access_token()
    assert not gmail.status()["connected"]


def test_connect_needs_client_file(tmp_path) -> None:
    with pytest.raises(GmailError, match=r"google_client\.json"):
        Gmail(tmp_path, DictStore()).begin_connect()


class FakeGmail:
    def __init__(self) -> None:
        self.connected = True
        self.sent: list[dict] = []
        self.incoming: list[NewMessage] = []
        self.fail = False

    def status(self) -> dict:
        return {"connected": self.connected}

    def send(self, to, subject, body, sender_name="", thread_id="", in_reply_to="") -> dict:
        if self.fail:
            raise GmailError("Send failed (500)")
        n = len(self.sent) + 1
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "body": body,
                "thread_id": thread_id,
                "in_reply_to": in_reply_to,
            }
        )
        return {"id": f"m{n}", "thread_id": thread_id or f"t{n}", "message_id": f"<m{n}@x>"}

    def new_messages(self, threads, known) -> list[NewMessage]:
        out = [m for m in self.incoming if m.thread_id in threads and m.id not in known]
        self.incoming = []
        return out


@pytest.fixture
def setup(tmp_path):
    ws = Workspace(tmp_path / "projects")
    project = ws.create_project("Mail")
    project.meta.sending.active = True
    project.meta.email.subject_template = "hello"
    project.meta.email.body_template = "Hi {first_name},\n\nQuestion.\n\nAlex"
    project.meta.email.follow_up_template = "Hi {first_name},\n\nFollowing up.\n\nAlex"
    project.meta.email.final_template = "Hi {first_name},\n\nLast note.\n\nAlex"
    project.save_meta()
    clock = {"now": NOW}
    gmail = FakeGmail()
    mailer = Mailer(ws, gmail, clock=lambda: clock["now"], rng=random.Random(1))
    return ws, project, gmail, mailer, clock


def approved_for(project, name="Ana Ruiz", **person):
    org = project.create("organizations", {"name": f"{name} Bakery"})
    p = project.create(
        "people",
        {
            "name": name,
            "first_name": name.split()[0],
            "organization_id": org.id,
            "email": f"{name.split()[0].lower()}@example.com",
            "email_confidence": "verified_direct",
            **person,
        },
    )
    msg = outreach.draft_initial(project, p.id)
    assert outreach.approve(project, [msg.id])["approved"] == [msg.id]
    return p, msg


def test_sends_approved_email_and_paces(setup) -> None:
    _, project, _, mailer, clock = setup
    ana, msg = approved_for(project)
    ben, _ = approved_for(project, "Ben Lee")
    sent = mailer.send_next(project)
    assert sent is not None
    assert sent.id == msg.id
    assert sent.status == "sent"
    assert sent.gmail_thread_id == "t1"
    person = project.get("people", ana.id)
    assert person.stage == "sent"
    assert person.next_action_due == "2026-10-20"
    assert project.get("organizations", ana.organization_id).already_contacted
    assert mailer.send_next(project) is None
    assert mailer.status(project)["blocked"].startswith("Next send after")
    clock["now"] = NOW.replace(minute=15)
    assert mailer.send_next(project).person_id == ben.id
    assert mailer.status(project)["sent_today"] == 2


def test_nothing_sends_when_off_disconnected_in_call_or_capped(setup) -> None:
    _, project, gmail, mailer, _ = setup
    approved_for(project)
    project.meta.sending.active = False
    assert mailer.blocked(project, NOW) == "Sending is off for this project"
    project.meta.sending.active = True
    gmail.connected = False
    assert mailer.send_next(project) is None
    gmail.connected = True
    mailer.call_live = lambda: True
    assert mailer.blocked(project, NOW) == "Paused during a call"
    mailer.call_live = lambda: False
    project.meta.sending.daily_cap = 0
    assert "Daily cap" in mailer.blocked(project, NOW)
    assert gmail.sent == []


def test_send_window_uses_recipient_time_zone(setup) -> None:
    _, project, _, mailer, clock = setup
    approved_for(project, time_zone="America/New_York")
    clock["now"] = datetime(2026, 10, 14, 15, 0, tzinfo=PACIFIC)  # 6 p.m. in New York
    assert mailer.send_next(project) is None
    clock["now"] = datetime(2026, 10, 17, 10, 0, tzinfo=PACIFIC)  # Saturday
    assert mailer.send_next(project) is None
    clock["now"] = datetime(2026, 10, 15, 7, 0, tzinfo=PACIFIC)  # 10 a.m. in New York
    assert mailer.send_next(project) is not None


def test_recheck_skips_people_who_opted_out(setup) -> None:
    _, project, gmail, mailer, _ = setup
    ana, msg = approved_for(project)
    project.update("people", ana.id, {"do_not_contact": True})
    assert mailer.send_next(project) is None
    skipped = project.get("messages", msg.id)
    assert skipped.status == "skipped"
    assert skipped.error == "Marked do not contact or declined"
    assert gmail.sent == []


def test_failed_send_is_recorded(setup) -> None:
    _, project, gmail, mailer, _ = setup
    _, msg = approved_for(project)
    gmail.fail = True
    assert mailer.send_next(project).status == "failed"
    assert project.get("messages", msg.id).error == "Send failed (500)"


def test_follow_up_sequence_and_reply_stop(setup) -> None:
    _, project, gmail, mailer, clock = setup
    ana, _ = approved_for(project)
    mailer.send_next(project)
    assert outreach.due_follow_ups(project, date(2026, 10, 19)) == []
    [follow] = outreach.due_follow_ups(project, date(2026, 10, 20))
    assert follow.kind == "follow_up"
    assert follow.subject == "Re: hello"
    assert follow.gmail_thread_id == "t1"
    assert project.get("people", ana.id).stage == "follow_up_due"
    assert outreach.due_follow_ups(project, date(2026, 10, 20)) == []
    assert outreach.approve(project, [follow.id])["approved"] == [follow.id]
    clock["now"] = datetime(2026, 10, 20, 10, 0, tzinfo=PACIFIC)
    mailer.send_next(project)
    assert gmail.sent[-1]["thread_id"] == "t1"
    assert gmail.sent[-1]["in_reply_to"] == "<m1@x>"
    [final] = outreach.due_follow_ups(project, date(2026, 10, 27))
    assert final.kind == "final"

    gmail.incoming = [
        NewMessage(
            "r1",
            "t1",
            "Ana <ana@example.com>",
            "Re: hello",
            "",
            "<r1@x>",
            "Happy to talk",
            False,
            False,
        )
    ]
    assert mailer.check_replies() == 1
    assert project.get("messages", final.id).status == "skipped"
    reply = next(m for m in project.all("messages") if m.kind == "reply")
    assert not reply.triaged
    assert project.get("people", ana.id).next_action == "Read the reply in the Inbox"
    assert outreach.due_follow_ups(project, date(2026, 11, 30)) == []
    outreach.triage_reply(project, reply.id, "interested")
    person = project.get("people", ana.id)
    assert person.stage == "interested"
    assert project.get("messages", reply.id).triaged


def test_follow_up_check_flags_reply_and_outside_thread(setup) -> None:
    _, project, _, _, _ = setup
    org = project.create("organizations", {"name": "Old Bakery"})
    person = project.create(
        "people",
        {"name": "Cal Day", "organization_id": org.id, "email": "c@x.com", "stage": "sent"},
    )
    project.create(
        "messages",
        {"person_id": person.id, "kind": "initial", "status": "sent", "sent_at": "2026-10-05"},
    )
    follow = outreach.draft_follow_up(project, person.id)
    assert not follow.subject.startswith("Re:")
    checks = {c.name: c for c in outreach.run_checks(project, follow)}
    assert checks["Same thread"].level == "warn"
    assert "One contact per organization" not in checks
    project.create("messages", {"person_id": person.id, "kind": "reply", "status": "received"})
    checks = {c.name: c for c in outreach.run_checks(project, follow)}
    assert checks["No reply yet"].level == "fail"
