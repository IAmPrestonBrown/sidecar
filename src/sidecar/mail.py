"""Paced sending of approved emails, and replies from Gmail.

Only messages the user approved are sent, one at a time, inside the project's
send window and daily cap, with a random gap between sends. Sending pauses
during a live call. Every send rechecks the person first. Replies are stored for
review and stop that person's follow-ups; they never change a stage on their own.
"""

import logging
import random
import threading
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sidecar import outreach
from sidecar.gmail import GmailError, NotConnectedError
from sidecar.models import Message, Person
from sidecar.store import Project, Workspace

log = logging.getLogger(__name__)

SEND_CHECK_S = 30
REPLY_CHECK_S = 120
STOP_STAGES = {
    "replied",
    "interested",
    "scheduling",
    "confirmed",
    "completed",
    "declined",
    "unresponsive",
    "do_not_contact",
}
FOLLOW_UP_GAP = {"initial": 4, "follow_up": 5, "final": 5}
NEXT_ACTION = {
    "initial": "Follow up if no reply",
    "follow_up": "Send the final note if no reply",
    "final": "No reply after the final note. Mark unresponsive if nothing comes.",
}


def _parse(iso: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _clock(text: str) -> time:
    hours, _, minutes = text.partition(":")
    return time(int(hours), int(minutes or 0))


def recipient_now(person: Person, now: datetime) -> datetime:
    """The current time where the recipient is, when their time zone is known."""
    if person.time_zone:
        try:
            return now.astimezone(ZoneInfo(person.time_zone))
        except ZoneInfoNotFoundError, ValueError:
            pass
    return now


class Mailer:
    def __init__(
        self,
        workspace: Workspace,
        gmail: Any,
        call_live: Callable[[], bool] = lambda: False,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        rng: random.Random | None = None,
    ) -> None:
        self.workspace = workspace
        self.gmail = gmail
        self.call_live = call_live
        self.clock = clock
        self.rng = rng or random.Random()
        self.next_at: dict[str, datetime] = {}
        self.lock = threading.Lock()
        self.last_reply_check: datetime | None = None
        self.last_error = ""

    # Status -------------------------------------------------------------------

    def sent_today(self, project: Project, now: datetime) -> int:
        today = now.date().isoformat()
        return sum(
            1
            for m in project.all("messages")
            if m.status == "sent"
            and m.kind != "reply"
            and m.sent_at[:10] == today
            and _parse(m.sent_at) is not None
        )

    def earliest_next(self, project: Project) -> datetime | None:
        if project.slug in self.next_at:
            return self.next_at[project.slug]
        times = [
            t
            for m in project.all("messages")
            if m.status == "sent" and (t := _parse(m.sent_at)) is not None
        ]
        if not times:
            return None
        return max(times) + timedelta(minutes=project.meta.sending.min_gap_minutes)

    def queue(self, project: Project) -> list[Message]:
        approved = [m for m in project.all("messages") if m.status == "approved"]
        return sorted(approved, key=lambda m: m.updated_at)

    def blocked(self, project: Project, now: datetime) -> str:
        """Why nothing can be sent right now, or an empty string."""
        sending = project.meta.sending
        if not sending.active:
            return "Sending is off for this project"
        if not self.gmail.status()["connected"]:
            return "Gmail is not connected"
        if self.call_live():
            return "Paused during a call"
        if self.sent_today(project, now) >= sending.daily_cap:
            return f"Daily cap of {sending.daily_cap} reached"
        nxt = self.earliest_next(project)
        if nxt and now < nxt:
            return f"Next send after {nxt.astimezone(now.tzinfo).strftime('%H:%M')}"
        return ""

    def in_window(self, project: Project, person: Person, now: datetime) -> bool:
        sending = project.meta.sending
        local = recipient_now(person, now)
        if local.weekday() not in sending.weekdays:
            return False
        return _clock(sending.window_start) <= local.time() < _clock(sending.window_end)

    def status(self, project: Project) -> dict:
        now = self.clock()
        nxt = self.earliest_next(project)
        return {
            "active": project.meta.sending.active,
            "connected": self.gmail.status()["connected"],
            "sent_today": self.sent_today(project, now),
            "daily_cap": project.meta.sending.daily_cap,
            "waiting": len(self.queue(project)),
            "blocked": self.blocked(project, now),
            "next_after": nxt.isoformat() if nxt and nxt > now else "",
            "last_error": self.last_error,
        }

    # Sending -----------------------------------------------------------------

    def recheck(self, project: Project, message: Message) -> str:
        """A reason this approved message must not be sent now, or an empty string."""
        current = project.get("messages", message.id)
        if current.status != "approved":
            return f"No longer approved ({current.status})"
        person = project.get("people", message.person_id)
        assert isinstance(person, Person)
        if person.do_not_contact or person.stage in ("declined", "do_not_contact"):
            return "Marked do not contact or declined"
        if not person.email:
            return "No email address"
        if outreach.has_reply(project, person.id):
            return "This person has replied"
        if message.kind == "initial":
            if any(
                m.person_id == person.id and m.kind == "initial" and m.status == "sent"
                for m in project.all("messages")
            ):
                return "A first email was already sent"
        elif person.stage in STOP_STAGES:
            return f"Stage is {person.stage.replace('_', ' ')}"
        return ""

    def send_next(self, project: Project) -> Message | None:
        """Send the oldest approved message that is in its window, if sending is allowed."""
        with self.lock:
            now = self.clock()
            if self.blocked(project, now):
                return None
            for message in self.queue(project):
                person = project.get("people", message.person_id)
                assert isinstance(person, Person)
                reason = self.recheck(project, message)
                if reason:
                    project.update(
                        "messages",
                        message.id,
                        {"status": "skipped", "error": reason},
                        actor="mailer",
                    )
                    continue
                if not self.in_window(project, person, now):
                    continue
                return self._send(project, message, person, now)
            return None

    def _send(self, project: Project, message: Message, person: Person, now: datetime) -> Message:
        email = project.meta.email
        body = message.body
        if email.footer_enabled and (email.postal_address or email.opt_out_line):
            body += "\n\n" + "\n".join(x for x in (email.postal_address, email.opt_out_line) if x)
        previous = outreach.last_sent(project, person.id) if message.kind != "initial" else None
        try:
            sent = self.gmail.send(
                person.email,
                message.subject,
                body,
                email.sender_name,
                thread_id=message.gmail_thread_id,
                in_reply_to=previous.rfc_message_id if previous and message.gmail_thread_id else "",
            )
        except NotConnectedError as exc:
            self.last_error = str(exc)
            raise
        except GmailError as exc:
            self.last_error = str(exc)
            log.warning("Send failed for %s: %s", message.id, exc)
            failed = project.update(
                "messages", message.id, {"status": "failed", "error": str(exc)}, actor="mailer"
            )
            assert isinstance(failed, Message)
            return failed
        self.last_error = ""
        updated = project.update(
            "messages",
            message.id,
            {
                "status": "sent",
                "sent_at": now.isoformat(timespec="seconds"),
                "gmail_message_id": sent["id"],
                "gmail_thread_id": sent["thread_id"],
                "rfc_message_id": sent["message_id"],
                "error": "",
            },
            actor="mailer",
        )
        due = outreach.add_business_days(now.date(), FOLLOW_UP_GAP[message.kind])
        project.update(
            "people",
            person.id,
            {
                "stage": "sent",
                "next_action": NEXT_ACTION[message.kind],
                "next_action_due": due.isoformat(),
            },
            actor="mailer",
        )
        if person.organization_id:
            project.update(
                "organizations", person.organization_id, {"already_contacted": True}, actor="mailer"
            )
        gap = self.rng.uniform(
            project.meta.sending.min_gap_minutes, project.meta.sending.max_gap_minutes
        )
        self.next_at[project.slug] = now + timedelta(minutes=gap)
        assert isinstance(updated, Message)
        return updated

    # Replies -----------------------------------------------------------------

    def check_replies(self) -> int:
        """Store new messages in tracked threads as replies waiting for review."""
        if not self.gmail.status()["connected"]:
            return 0
        projects = [self.workspace.project(s) for s in self.workspace.slugs()]
        owners: dict[str, tuple[Project, str]] = {}
        known: set[str] = set()
        for project in projects:
            for m in project.all("messages"):
                if m.gmail_message_id:
                    known.add(m.gmail_message_id)
                if m.gmail_thread_id and m.status == "sent":
                    owners[m.gmail_thread_id] = (project, m.person_id)
        found = self.gmail.new_messages(set(owners), known)
        now = self.clock().isoformat(timespec="seconds")
        for item in found:
            project, person_id = owners[item.thread_id]
            project.create(
                "messages",
                {
                    "person_id": person_id,
                    "kind": "reply",
                    "status": "received",
                    "subject": item.subject,
                    "body": item.body,
                    "from_address": item.from_address,
                    "received_at": now,
                    "gmail_message_id": item.id,
                    "gmail_thread_id": item.thread_id,
                    "rfc_message_id": item.message_id,
                    "auto_reply": item.auto_reply,
                    "bounce": item.bounce,
                    "triaged": False,
                },
                actor="mailer",
            )
            action = (
                "Email bounced. Check the address."
                if item.bounce
                else "Read the reply in the Inbox"
            )
            project.update("people", person_id, {"next_action": action}, actor="mailer")
            if not item.bounce:
                for m in project.all("messages"):
                    if (
                        m.person_id == person_id
                        and m.kind in ("follow_up", "final")
                        and m.status in ("draft", "approved")
                    ):
                        project.update(
                            "messages",
                            m.id,
                            {"status": "skipped", "error": "Skipped because a reply arrived"},
                            actor="mailer",
                        )
        self.last_reply_check = self.clock()
        return len(found)

    # Loop --------------------------------------------------------------------

    def tick(self, today: date | None = None) -> None:
        now = self.clock()
        for slug in self.workspace.slugs():
            project = self.workspace.project(slug)
            if project.meta.sending.active:
                outreach.due_follow_ups(project, today or now.date())
                self.send_next(project)
        if self.last_reply_check is None or now - self.last_reply_check >= timedelta(
            seconds=REPLY_CHECK_S
        ):
            self.check_replies()

    def run(self, stop: threading.Event) -> None:
        while not stop.wait(SEND_CHECK_S):
            try:
                self.tick()
            except NotConnectedError:
                continue
            except GmailError, OSError:
                log.exception("Mail check failed")
