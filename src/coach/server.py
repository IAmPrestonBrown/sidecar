"""FastAPI app serving the UI and the /ws event hub."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Generator
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from coach.session import LiveSession

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent / "ui"
CLIENT_QUEUE = 500


class Hub:
    """Fans events out to connected websocket clients.

    Each client has a bounded queue. A client that falls behind is dropped
    and rebuilds from a snapshot when it reconnects.
    """

    def __init__(self) -> None:
        self.clients: dict[WebSocket, asyncio.Queue[str]] = {}

    def broadcast(self, event: dict) -> None:
        text = json.dumps(event, default=str)
        for ws, queue in list(self.clients.items()):
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                log.warning("UI client fell behind; dropping it")
                self.clients.pop(ws, None)
                asyncio.get_running_loop().create_task(ws.close())


def create_app(session: LiveSession, hub: Hub) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=CLIENT_QUEUE)
        await ws.send_text(json.dumps(session.snapshot(), default=str))
        hub.clients[ws] = queue
        sender = asyncio.create_task(_pump(ws, queue))
        try:
            while True:
                msg = await ws.receive_json()
                handle_client_message(session, msg)
        except WebSocketDisconnect:
            pass
        except (ValueError, RuntimeError) as exc:
            log.warning("UI websocket error: %s", exc)
        finally:
            hub.clients.pop(ws, None)
            sender.cancel()

    return app


async def _pump(ws: WebSocket, queue: asyncio.Queue[str]) -> None:
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            await ws.send_text(await queue.get())


def handle_client_message(session: LiveSession, msg: dict) -> None:
    kind = msg.get("type")
    if kind == "start":
        session.start()
    elif kind == "mark":
        session.mark()
    elif kind == "ask_next":
        session.ask_next()
    elif kind == "swap_speakers":
        session.event("swap_pressed")
        session.swap_speakers()
    elif kind == "dismiss_pinned":
        session.dismiss_pinned()
    elif kind == "end_request":
        session.event("end_request")
    elif kind == "end_confirm":
        session.event("end_confirm")
        session.request_end()
    else:
        log.debug("Unknown UI message: %s", kind)


class QuietServer(uvicorn.Server):
    """Uvicorn server that leaves signal handling to the CLI."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None]:
        yield


def make_server(app: FastAPI, port: int) -> QuietServer:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    return QuietServer(config)
