"""Deepgram live streaming client over a raw websocket."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from urllib.parse import quote, urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus, WebSocketException

from coach.config import DeepgramConfig
from coach.transcript import Segment

log = logging.getLogger(__name__)

LIVE_URL = "wss://api.deepgram.com/v1/listen"
KEEPALIVE_S = 4.0
CLOSE_WAIT_S = 5.0
QUEUE_BLOCKS = 50
BACKOFF_MIN_S = 0.5
BACKOFF_MAX_S = 8.0
MIN_GAP_S = 1.0


def live_query(cfg: DeepgramConfig, sample_rate: int, keyterms: list[str]) -> str:
    """Build the live websocket query string."""
    params: list[tuple[str, str]] = [
        ("model", cfg.model),
        ("language", cfg.language),
        ("encoding", "linear16"),
        ("sample_rate", str(sample_rate)),
        ("channels", "1"),
        ("diarize", "true"),
        ("interim_results", "true"),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("utterance_end_ms", str(cfg.utterance_end_ms)),
        ("vad_events", "true"),
        ("endpointing", str(cfg.endpointing_ms)),
    ]
    if cfg.mip_opt_out:
        params.append(("mip_opt_out", "true"))
    params.extend(("keyterm", term) for term in keyterms)
    return urlencode(params, quote_via=quote)


def words_to_segments(words: list[dict], offset_s: float, connection: int) -> list[Segment]:
    """Group Deepgram words into segments of consecutive same-speaker words."""
    segments: list[Segment] = []
    for w in words:
        spk = int(w.get("speaker", 0))
        start = float(w["start"]) + offset_s
        end = float(w["end"]) + offset_s
        text = w.get("punctuated_word") or w.get("word", "")
        if segments and segments[-1].speaker_id == spk:
            seg = segments[-1]
            seg.end = end
            seg.text = f"{seg.text} {text}"
            seg.words.append((start, end))
        else:
            segments.append(Segment(start, end, connection, spk, "", text, [(start, end)]))
    return segments


class LiveSTT:
    """Streams audio to Deepgram and reports transcript events.

    Audio arrives through put_block from the writer thread via the event loop.
    Each block carries its session start sample, which gives the per-connection
    time offset.
    """

    def __init__(
        self,
        cfg: DeepgramConfig,
        api_key: str,
        sample_rate: int,
        keyterms: list[str],
        on_segments: Callable[[list[Segment]], None],
        on_interim: Callable[[str], None],
        on_utterance_end: Callable[[], None],
        on_status: Callable[[str, str], None],
        on_gap: Callable[[float, float, int], None],
        url: str = LIVE_URL,
    ) -> None:
        self.cfg = cfg
        self.base_url = url
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.keyterms = keyterms
        self.on_segments = on_segments
        self.on_interim = on_interim
        self.on_utterance_end = on_utterance_end
        self.on_status = on_status
        self.on_gap = on_gap
        self.queue: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue(maxsize=QUEUE_BLOCKS)
        self.dropped_blocks = 0
        self.connection = -1
        self.state = "idle"
        self._closing = asyncio.Event()
        self._closed = asyncio.Event()
        self._ws: ClientConnection | None = None
        self.sent_end_sample = 0
        self._connected_once = False
        self._auth_failed = False
        self._dropped_while_down = False

    def put_block(self, start_sample: int, block: bytes) -> None:
        """Queue a block for sending. Drops it if the queue is full."""
        try:
            self.queue.put_nowait((start_sample, block))
        except asyncio.QueueFull:
            self.dropped_blocks += 1
            self._dropped_while_down = self._ws is None

    def _set_status(self, state: str, detail: str = "") -> None:
        self.state = state
        self.on_status(state, detail)

    async def run(self) -> None:
        """Connect and stream until close() is called. Retries forever."""
        if not self.api_key:
            self._set_status("down", "DEEPGRAM_API_KEY missing")
            await self._closing.wait()
            self._closed.set()
            return
        url = f"{self.base_url}?{live_query(self.cfg, self.sample_rate, self.keyterms)}"
        backoff = BACKOFF_MIN_S
        while not self._closing.is_set():
            if not self._auth_failed:
                self._set_status("reconnecting" if self._connected_once else "connecting")
            try:
                async with connect(
                    url,
                    additional_headers={"Authorization": f"Token {self.api_key}"},
                    open_timeout=10,
                    max_size=2**22,
                ) as ws:
                    self._ws = ws
                    self.connection += 1
                    self._connected_once = True
                    backoff = BACKOFF_MIN_S
                    self._auth_failed = False
                    self._set_status("live")
                    await self._stream(ws)
            except InvalidStatus as exc:
                code = exc.response.status_code
                log.error("Deepgram rejected connection: HTTP %s", code)
                self._auth_failed = code in (401, 403)
                self._set_status("down", f"HTTP {code}")
            except (OSError, WebSocketException, TimeoutError) as exc:
                log.warning("Deepgram connection error: %s", exc)
            except Exception:
                log.exception("Live STT failed")
            finally:
                self._ws = None
            if self._closing.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(BACKOFF_MAX_S, backoff * 2)
        self._set_status("closed")
        self._closed.set()

    async def _stream(self, ws: ClientConnection) -> None:
        self._drain_stale()
        offset_s: list[float] = []
        sender = asyncio.create_task(self._send_loop(ws, offset_s))
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                self._handle(json.loads(raw), offset_s[0] if offset_s else 0.0)
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender

    def _drain_stale(self) -> None:
        """Drop queued audio if blocks were lost while disconnected.

        A full queue holds the oldest blocks, so sending them would start the
        connection on stale audio followed by a jump.
        """
        if not self._dropped_while_down:
            return
        self._dropped_while_down = False
        while not self.queue.empty():
            self.queue.get_nowait()

    async def _send_loop(self, ws: ClientConnection, offset_s: list[float]) -> None:
        expected: int | None = None
        while True:
            try:
                start, block = await asyncio.wait_for(self.queue.get(), timeout=KEEPALIVE_S)
            except TimeoutError:
                if self._closing.is_set():
                    await ws.send(json.dumps({"type": "CloseStream"}))
                    return
                await ws.send(json.dumps({"type": "KeepAlive"}))
                continue
            if start < 0:
                await ws.send(json.dumps({"type": "CloseStream"}))
                return
            if expected is None:
                offset_s.append(start / self.sample_rate)
                gap_start = self.sent_end_sample / self.sample_rate
                if start / self.sample_rate - gap_start >= MIN_GAP_S:
                    self.on_gap(gap_start, start / self.sample_rate, self.connection)
                expected = start
            if start > expected:
                await ws.send(bytes((start - expected) * 2))
            await ws.send(block)
            expected = start + len(block) // 2
            self.sent_end_sample = expected

    def _handle(self, msg: dict, offset_s: float) -> None:
        kind = msg.get("type")
        if kind == "Results":
            alt = msg.get("channel", {}).get("alternatives", [{}])[0]
            if msg.get("is_final"):
                words = alt.get("words", [])
                if words:
                    self.on_segments(words_to_segments(words, offset_s, self.connection))
                self.on_interim("")
            else:
                self.on_interim(alt.get("transcript", ""))
        elif kind == "UtteranceEnd":
            self.on_utterance_end()
        elif kind == "Error":
            log.warning("Deepgram error message: %s", msg)
        else:
            log.debug("Deepgram %s: %s", kind, msg)

    async def close(self) -> None:
        """Send CloseStream and wait up to CLOSE_WAIT_S for final results."""
        self._closing.set()
        try:
            self.queue.put_nowait((-1, b""))
        except asyncio.QueueFull:
            log.debug("STT queue full at close; CloseStream follows the drain")
        try:
            await asyncio.wait_for(self._closed.wait(), timeout=CLOSE_WAIT_S)
        except TimeoutError:
            log.warning("Deepgram did not close within %.0fs", CLOSE_WAIT_S)
            if self._ws is not None:
                await self._ws.close()
