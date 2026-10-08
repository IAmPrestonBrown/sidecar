"""Gmail access: OAuth for installed apps, sending, and reading new thread messages.

The OAuth client is the user's own Google Cloud "Desktop app" client, saved as
``google_client.json`` in the Sidecar config directory. The refresh token is kept
in the macOS Keychain. Only the connected address and the Gmail history position
are written to disk.
"""

import base64
import contextlib
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

import httpx2

log = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("SIDECAR_CONFIG_DIR", "~/.config/sidecar")).expanduser()
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
KEYRING_SERVICE = "Sidecar Gmail"
CONNECT_TIMEOUT_S = 300
REPLY_HEADERS = ["From", "To", "Subject", "Date", "Message-ID", "Auto-Submitted", "X-Autoreply"]


class GmailError(Exception):
    pass


class NotConnectedError(GmailError):
    pass


class TokenStore(Protocol):
    def get(self, account: str) -> str | None: ...
    def set(self, account: str, token: str) -> None: ...
    def delete(self, account: str) -> None: ...


class KeychainStore:
    """Refresh tokens in the macOS Keychain through the keyring package."""

    def get(self, account: str) -> str | None:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, account)

    def set(self, account: str, token: str) -> None:
        import keyring

        keyring.set_password(KEYRING_SERVICE, account, token)

    def delete(self, account: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, account)


@dataclass(frozen=True)
class Client:
    client_id: str
    client_secret: str


@dataclass
class NewMessage:
    """A message that arrived in a thread Sidecar is tracking."""

    id: str
    thread_id: str
    from_address: str
    subject: str
    date: str
    message_id: str
    body: str
    auto_reply: bool
    bounce: bool


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def build_mime(
    sender: str,
    sender_name: str,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str = "",
) -> tuple[str, str]:
    """A plain-text message, base64url encoded for the Gmail API, and its Message-ID."""
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender)) if sender_name else sender
    msg["To"] = to
    msg["Subject"] = subject
    message_id = make_msgid(domain=sender.rpartition("@")[2] or None)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    return _b64url(msg.as_bytes()), message_id


def _plain_text(payload: dict) -> str:
    """The first text/plain part of a Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = _plain_text(part)
        if text:
            return text
    return ""


def _is_bounce(from_address: str) -> bool:
    low = from_address.lower()
    return "mailer-daemon@" in low or "postmaster@" in low


class Gmail:
    """One connected Gmail account for the whole app."""

    def __init__(
        self,
        config_dir: Path = CONFIG_DIR,
        store: TokenStore | None = None,
        http: httpx2.Client | None = None,
        opener: Callable[[str], None] | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.store = store or KeychainStore()
        self.http = http or httpx2.Client(timeout=30)
        self.opener = opener
        self.lock = threading.Lock()
        self._access: tuple[str, float] | None = None
        self._pending: dict[str, Any] | None = None

    # Files -------------------------------------------------------------------

    @property
    def client_file(self) -> Path:
        return self.config_dir / "google_client.json"

    @property
    def state_file(self) -> Path:
        return self.config_dir / "gmail.json"

    def client(self) -> Client | None:
        try:
            data = json.loads(self.client_file.read_text())
        except OSError, json.JSONDecodeError:
            return None
        info = data.get("installed") or data.get("web") or data
        if not info.get("client_id"):
            return None
        return Client(info["client_id"], info.get("client_secret", ""))

    def state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except OSError, json.JSONDecodeError:
            return {}

    def save_state(self, **fields: Any) -> None:
        data = {**self.state(), **fields}
        self.config_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(self.state_file)

    @property
    def email(self) -> str:
        return self.state().get("email", "")

    def status(self) -> dict:
        email = self.email
        return {
            "configured": self.client() is not None,
            "client_file": str(self.client_file),
            "connected": bool(email and self.store.get(email)),
            "email": email,
            "connecting": self._pending is not None,
        }

    # OAuth -------------------------------------------------------------------

    def begin_connect(self) -> str:
        """Start the browser sign-in and return its URL.

        A one-shot server on a random local port receives Google's redirect,
        exchanges the code with PKCE, and saves the refresh token.
        """
        client = self.client()
        if client is None:
            raise GmailError(f"Add your Google OAuth client file at {self.client_file}")
        verifier = _b64url(secrets.token_bytes(48))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        state = secrets.token_urlsafe(24)
        gmail = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                query = parse_qs(urlparse(self.path).query)
                if query.get("state", [""])[0] != state:
                    self._reply(400, "This sign-in link is out of date. Start again from Sidecar.")
                    return
                if "error" in query:
                    gmail._pending = None
                    self._reply(200, "Sign-in was cancelled. You can close this tab.")
                    return
                try:
                    gmail.finish_connect(client, query.get("code", [""])[0], verifier, redirect)
                except GmailError as exc:
                    self._reply(500, f"Could not connect Gmail: {exc}")
                    return
                self._reply(
                    200, "Gmail is connected. You can close this tab and return to Sidecar."
                )

            def _reply(self, code: int, text: str) -> None:
                body = f"<!doctype html><meta charset=utf-8><title>Sidecar</title><p>{text}</p>"
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())
                threading.Thread(target=server.shutdown, daemon=True).start()

            def log_message(self, *_: object) -> None:
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        redirect = f"http://127.0.0.1:{server.server_port}/"
        self._pending = {"server": server}

        def serve() -> None:
            timer = threading.Timer(CONNECT_TIMEOUT_S, server.shutdown)
            timer.start()
            server.serve_forever()
            timer.cancel()
            server.server_close()
            self._pending = None

        threading.Thread(target=serve, daemon=True).start()
        url = (
            AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": client.client_id,
                    "redirect_uri": redirect,
                    "response_type": "code",
                    "scope": " ".join(SCOPES),
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": state,
                    "access_type": "offline",
                    "prompt": "consent",
                }
            )
        )
        if self.opener:
            self.opener(url)
        return url

    def finish_connect(self, client: Client, code: str, verifier: str, redirect: str) -> str:
        res = self.http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if res.status_code != 200:
            raise GmailError(f"Token exchange failed ({res.status_code})")
        tokens = res.json()
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise GmailError("Google did not return a refresh token")
        granted = set(tokens.get("scope", "").split())
        if not set(SCOPES) <= granted:
            raise GmailError("Both Gmail permissions are needed: send, and read")
        with self.lock:
            self._access = (
                tokens["access_token"],
                time.time() + tokens.get("expires_in", 3600) - 60,
            )
        profile = self._get("/profile")
        email = profile["emailAddress"]
        self.store.set(email, refresh)
        self.save_state(email=email, history_id=profile.get("historyId", ""))
        self._pending = None
        log.info("Connected Gmail account %s", email)
        return email

    def disconnect(self) -> None:
        email = self.email
        refresh = self.store.get(email) if email else None
        if refresh:
            try:
                self.http.post(REVOKE_URL, data={"token": refresh})
            except httpx2.HTTPError:
                log.warning("Could not revoke the Gmail token; removing it locally")
            self.store.delete(email)
        with self.lock:
            self._access = None
        self.save_state(email="", history_id="")

    def access_token(self) -> str:
        with self.lock:
            if self._access and self._access[1] > time.time():
                return self._access[0]
        client = self.client()
        email = self.email
        refresh = self.store.get(email) if email else None
        if client is None or not refresh:
            raise NotConnectedError("Gmail is not connected")
        res = self.http.post(
            TOKEN_URL,
            data={
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if res.status_code in (400, 401):
            # Expired or revoked, for example after seven days in Testing mode.
            # Forget the token so the app shows Gmail as disconnected.
            self.store.delete(email)
            with self.lock:
                self._access = None
            raise NotConnectedError(
                "Gmail access expired or was revoked. Connect again in Settings."
            )
        if res.status_code != 200:
            raise GmailError(f"Token refresh failed ({res.status_code})")
        data = res.json()
        with self.lock:
            self._access = (data["access_token"], time.time() + data.get("expires_in", 3600) - 60)
            return self._access[0]

    # API ---------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        try:
            return self.http.request(method, API + path, headers=headers, **kwargs)
        except httpx2.HTTPError as exc:
            raise GmailError(f"Network error: {exc}") from exc

    def _get(self, path: str, **params: Any) -> dict:
        res = self._request("GET", path, params=params)
        if res.status_code != 200:
            raise GmailError(f"GET {path.split('?')[0]} failed ({res.status_code})")
        return res.json()

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        sender_name: str = "",
        thread_id: str = "",
        in_reply_to: str = "",
    ) -> dict:
        """Send a plain-text email. Returns Gmail's ids and the RFC Message-ID."""
        raw, message_id = build_mime(self.email, sender_name, to, subject, body, in_reply_to)
        payload = {"raw": raw, **({"threadId": thread_id} if thread_id else {})}
        res = self._request("POST", "/messages/send", json=payload)
        if res.status_code != 200:
            detail = res.json().get("error", {}).get("message", "") if res.content else ""
            raise GmailError(f"Send failed ({res.status_code}) {detail}".strip())
        data = res.json()
        return {"id": data["id"], "thread_id": data["threadId"], "message_id": message_id}

    def _message(self, message_id: str) -> NewMessage:
        data = self._get(f"/messages/{message_id}", format="full")
        headers = {h["name"].lower(): h["value"] for h in data["payload"].get("headers", [])}
        sender = headers.get("from", "")
        auto = headers.get("auto-submitted", "no").lower() != "no" or "x-autoreply" in headers
        return NewMessage(
            id=data["id"],
            thread_id=data["threadId"],
            from_address=sender,
            subject=headers.get("subject", ""),
            date=headers.get("date", ""),
            message_id=headers.get("message-id", ""),
            body=_plain_text(data["payload"]) or data.get("snippet", ""),
            auto_reply=auto,
            bounce=_is_bounce(sender),
        )

    def new_messages(self, threads: set[str], known: set[str]) -> list[NewMessage]:
        """Messages from other people in the given threads that are not yet known.

        Reads the mailbox history since the last check. When Google no longer has
        that history, every tracked thread is read in full instead.
        """
        if not threads:
            return []
        start = self.state().get("history_id", "")
        ids: list[str] = []
        latest = start
        if start:
            res = self._request(
                "GET", "/history", params={"startHistoryId": start, "historyTypes": "messageAdded"}
            )
            if res.status_code == 404:
                start = ""
            elif res.status_code != 200:
                raise GmailError(f"History check failed ({res.status_code})")
            else:
                while True:
                    data = res.json()
                    latest = data.get("historyId", latest)
                    for item in data.get("history", []):
                        for added in item.get("messagesAdded", []):
                            msg = added["message"]
                            if msg["threadId"] in threads and "SENT" not in msg.get("labelIds", []):
                                ids.append(msg["id"])
                    token = data.get("nextPageToken")
                    if not token:
                        break
                    res = self._request(
                        "GET",
                        "/history",
                        params={
                            "startHistoryId": start,
                            "historyTypes": "messageAdded",
                            "pageToken": token,
                        },
                    )
        if not start:
            latest = self._get("/profile").get("historyId", "")
            for thread in threads:
                data = self._get(f"/threads/{thread}", format="minimal")
                ids += [
                    m["id"] for m in data.get("messages", []) if "SENT" not in m.get("labelIds", [])
                ]
        out = [self._message(i) for i in dict.fromkeys(ids) if i not in known]
        if latest:
            self.save_state(history_id=latest)
        return out
