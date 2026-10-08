"""Session directory, live state, JSONL logs, and finalize."""

import asyncio
import contextlib
import json
import logging
import re
import time
import wave
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import numpy as np

from coach import stt_batch
from coach.audio import FileSource, MicSource, Recorder, RmsLog, pcm_to_wav
from coach.config import Config
from coach.llm import CallResult, CoachLLM, SessionHeader
from coach.scheduler import LiveScheduler, Slot
from coach.schemas import AskNext, CoachUpdate, MarkAnalysis
from coach.speakers import SpeakerMapper, map_batch_speakers
from coach.stt_live import LiveSTT
from coach.transcript import (
    Segment,
    TranscriptStore,
    gap_segment,
    load_jsonl,
    mmss,
    render_markdown,
    render_turns,
)

log = logging.getLogger(__name__)

MARK_WINDOW_S = 90.0
TALK_WINDOW_S = 180.0
RECENT_CARDS = 6
UI_TURNS = 8
SILENT_MIC_S = 3.0
STALL_S = 2.0
OVERFLOW_SHOW_S = 10.0
TICK_S = 0.5
TALK_EVERY_TICKS = 4


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "session"


def new_session_dir(cfg: Config, interviewee: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = cfg.interviews_dir / f"{stamp}_{slugify(interviewee)}"
    suffix = 1
    base = path
    while path.exists():
        suffix += 1
        path = base.with_name(f"{base.name}-{suffix}")
    path.mkdir(parents=True)
    return path


class JsonlWriter:
    """Appends one JSON object per line and flushes every line."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = open(path, "a")  # noqa: SIM115 - held open for the session

    def write(self, obj: dict) -> None:
        self._fh.write(json.dumps(obj, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return {}


def update_session_json(session_dir: Path, **fields: object) -> None:
    path = session_dir / "session.json"
    data = read_json(path)
    data.update(fields)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


def setup_session_logging(session_dir: Path) -> logging.Handler:
    handler = logging.FileHandler(session_dir / "session.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def them_label_for(interviewee: str) -> str:
    first = interviewee.strip().split()[0] if interviewee.strip() else "THEM"
    return re.sub(r"[^A-Z0-9]", "", first.upper()) or "THEM"


@dataclass
class Status:
    state: str = "idle"
    detail: str = ""
    latency: float | None = None

    def to_json(self) -> dict:
        return {"state": self.state, "detail": self.detail, "latency": self.latency}


class LiveSession:
    """Authoritative state for one interview. The UI is only a view of it."""

    def __init__(
        self,
        cfg: Config,
        session_dir: Path,
        interviewee: str,
        organization: str,
        planned_minutes: int,
        notes_path: Path | None,
        replay: Path | None = None,
        speed: float = 1.0,
    ) -> None:
        self.cfg = cfg
        self.dir = session_dir
        self.interviewee = interviewee
        self.organization = organization
        self.planned_minutes = planned_minutes
        self.notes_path = notes_path
        self.replay = replay
        self.speed = speed
        self.interviewer = cfg.session.interviewer_label
        self.them = them_label_for(interviewee)
        if self.them == self.interviewer:
            self.them = "THEM"
        self.phase = "prestart"
        self.preflight: list[dict] = []
        self.broadcast: Callable[[dict], None] = lambda event: None
        self.on_ended: Callable[[], None] = lambda: None
        self.status = {name: Status() for name in ("mic", "stt", "coach")}
        self.started_at: float | None = None
        self.interim = ""
        self.current_cards: list[dict] = []
        self.history: deque[dict] = deque(maxlen=RECENT_CARDS)
        self.evidence: list[dict] = []
        self.pinned: dict | None = None
        self.last_quiet_at: float | None = None
        self.level = {"rms": 0.0, "peak": 0.0}
        self.skip_batch = asyncio.Event()
        self.finalized = asyncio.Event()
        self._finalizing = False
        self._silent_since: float | None = None
        self._overflow_at: float | None = None
        self._last_samples = 0
        self._samples_moved_at = time.monotonic()
        self._live_seq = 0
        self._shown_seq = 0
        self._tasks: list[asyncio.Task] = []
        self._end_task: asyncio.Task | None = None

        self.transcript = TranscriptStore(
            cfg.coach.chunk_seconds, session_dir / "transcript_live.jsonl"
        )
        self.mapper = SpeakerMapper(self.interviewer, self.them)
        self.events = JsonlWriter(session_dir / "events.jsonl")
        self.coach_log = JsonlWriter(session_dir / "coach.jsonl")
        self.marks_log = JsonlWriter(session_dir / "marks.jsonl")
        self.asks_log = JsonlWriter(session_dir / "asks.jsonl")
        self.evidence_log = JsonlWriter(session_dir / "evidence.jsonl")
        self.recorder: Recorder | None = None
        self.stt: LiveSTT | None = None
        header = SessionHeader(
            interviewee, organization, planned_minutes, self.interviewer, self.them
        )
        self.llm = CoachLLM(cfg, header, notes_path, debug_dir=session_dir / "debug")
        self.scheduler = LiveScheduler(
            self._run_live,
            cfg.coach.min_interval_s,
            cfg.coach.timer_interval_s,
            cfg.coach.them_trigger_words,
            cfg.coach.timeout_s,
            on_status=self._live_status,
        )
        self.mark_slot = Slot()
        self.ask_slot = Slot()
        if not self.llm.available:
            self.status["coach"] = Status("down", "ANTHROPIC_API_KEY missing")
        update_session_json(
            session_dir,
            interviewee=interviewee,
            organization=organization,
            planned_minutes=planned_minutes,
            labels={"interviewer": self.interviewer, "interviewee": self.them},
            notes=str(notes_path) if notes_path else None,
            replay=str(replay) if replay else None,
            created_at=datetime.now().isoformat(timespec="seconds"),
            config=cfg.snapshot(),
            models={
                "live": cfg.coach.live_model,
                "mark": cfg.coach.mark_model,
                "ask_next": cfg.coach.ask_model,
                "stt_live": cfg.deepgram.model,
            },
        )

    def keyterms(self) -> list[str]:
        terms = list(self.cfg.deepgram.keyterms)
        for extra in (self.interviewee, self.organization):
            if extra and extra not in terms:
                terms.append(extra)
        return terms

    @property
    def elapsed(self) -> float:
        return self.recorder.seconds if self.recorder is not None else 0.0

    def event(self, kind: str, **data: object) -> None:
        self.events.write(
            {"t": time.time(), "session_s": round(self.elapsed, 2), "kind": kind, **data}
        )

    def set_status(
        self, name: str, state: str, detail: str = "", latency: float | None = None
    ) -> None:
        st = self.status[name]
        changed = st.state != state or st.detail != detail
        st.state, st.detail = state, detail
        if latency is not None:
            st.latency = round(latency, 2)
        if changed:
            log.info("status %s=%s %s", name, state, detail)
            self.event("status", component=name, state=state, detail=detail)
        self.broadcast({"type": "status", "status": self.status_json()})

    def status_json(self) -> dict:
        return {name: st.to_json() for name, st in self.status.items()}

    # Recording lifecycle

    def start(self) -> None:
        """Start recording, live STT, and the tick loop."""
        if self.phase != "prestart":
            return
        loop = asyncio.get_running_loop()
        bf, sr = self.cfg.audio.block_frames, self.cfg.audio.sample_rate
        if self.replay is not None:
            source: MicSource | FileSource = FileSource(self.replay, sr, bf, self.speed)
        else:
            source = MicSource(self.cfg.audio.input_device, sr, bf)
        self.recorder = Recorder(source, self.dir / "audio.pcm", sr, bf)
        self.stt = LiveSTT(
            self.cfg.deepgram,
            self.cfg.deepgram_api_key,
            sr,
            self.keyterms(),
            on_segments=self._on_segments,
            on_interim=self._on_interim,
            on_utterance_end=self._on_utterance_end,
            on_status=lambda state, detail: self.set_status("stt", state, detail),
            on_gap=self._on_gap,
        )
        stt = self.stt

        def stt_sink(start: int, block: bytes) -> None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(stt.put_block, start, block)

        def level_sink(rms: float, peak: float) -> None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._on_level, rms, peak)

        self.recorder.stt_sink = stt_sink
        self.recorder.level_sink = level_sink
        try:
            self.recorder.start()
        except Exception as exc:
            log.exception("Audio capture failed to start")
            self.set_status("mic", "down", str(exc)[:120])
            if self.recorder.running:
                self.recorder.stop()
            self.recorder = None
            return
        self.started_at = time.time()
        self._samples_moved_at = time.monotonic()
        self.phase = "recording"
        self.set_status("mic", "ok", "replay" if self.replay else "")
        self.event("start")
        update_session_json(self.dir, started_at=datetime.now().isoformat(timespec="seconds"))
        self._tasks.append(asyncio.create_task(self._supervise("stt", stt.run)))
        self._tasks.append(asyncio.create_task(self._supervise("tick", self._tick_loop)))
        if self.llm.available:
            self._tasks.append(asyncio.create_task(self._prewarm()))
        self.broadcast(self.snapshot())

    async def _supervise(self, name: str, fn: Callable) -> None:
        while self.phase == "recording":
            try:
                await fn()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Task %s crashed; restarting", name)
                await asyncio.sleep(1.0)

    async def _tick_loop(self) -> None:
        ticks = 0
        while self.phase == "recording":
            ticks += 1
            self.scheduler.tick()
            self._check_mic()
            if ticks % TALK_EVERY_TICKS == 0:
                self.broadcast(self.talk_json())
            source = self.recorder.source if self.recorder is not None else None
            if isinstance(source, FileSource) and source.finished.is_set():
                log.info("Replay finished; ending session")
                self.request_end()
                return
            await asyncio.sleep(TICK_S)

    async def _prewarm(self) -> None:
        """Write the tools and system prefix to the cache before the first live call.

        Live calls every 6-25 seconds keep it warm afterwards. MARK and ASK NEXT
        read the same tools and system entry.
        """
        try:
            self.coach_log.write(await self.llm.prewarm("live"))
        except anthropic.APIError as exc:
            log.warning("Prewarm failed: %s", exc)
            self.set_status("coach", "error", type(exc).__name__)

    def _check_mic(self) -> None:
        """Report overflow, stalled capture, and all-zero input on the MIC status."""
        if self.recorder is None:
            return
        now = time.monotonic()
        if self.recorder.source.overflow:
            self.recorder.source.overflow = False
            self._overflow_at = now
            self.event("input_overflow")
        samples = self.recorder.samples_written
        if samples != self._last_samples:
            self._last_samples, self._samples_moved_at = samples, now
        if self.level["peak"] == 0.0:
            self._silent_since = self._silent_since or now
        else:
            self._silent_since = None
        if now - self._samples_moved_at >= STALL_S:
            self.set_status("mic", "stalled", "no audio arriving")
        elif self._silent_since is not None and now - self._silent_since >= SILENT_MIC_S:
            self.set_status("mic", "silent", "all zeros: mic permission?")
        elif self._overflow_at is not None and now - self._overflow_at < OVERFLOW_SHOW_S:
            self.set_status("mic", "overflow", "input overflow")
        elif self.status["mic"].state != "ok":
            self.set_status("mic", "ok", "replay" if self.replay else "")

    def _on_level(self, rms: float, peak: float) -> None:
        self.level = {"rms": round(rms, 4), "peak": round(peak, 4)}
        self.broadcast({"type": "level", **self.level, "elapsed": round(self.elapsed, 1)})

    # Transcript events

    def _word_rms(self, seg: Segment) -> list[list[float]]:
        if self.recorder is None:
            return []
        return [self.recorder.rms_log.window(a, b) for a, b in seg.words]

    def _on_segments(self, segments: list[Segment]) -> None:
        mapping_changed = False
        for seg in segments:
            mapping_changed |= self.mapper.observe(seg, self._word_rms(seg))
            seg.label = self.mapper.label_for(seg)
            self.transcript.append(seg)
            self.scheduler.add_words(len(seg.words))
            print(f"[{mmss(seg.start)}] {seg.label}: {seg.text}", flush=True)
            self.broadcast({"type": "segment", "segment": self._seg_json(seg)})
        if mapping_changed:
            self._mapping_changed("auto")
        self.scheduler.enabled = self.mapper.mapped

    def _mapping_changed(self, kind: str) -> None:
        self.transcript.relabel(self.mapper.label_for)
        self.event("mapping", change=kind, history=self.mapper.history[-1:])
        self.broadcast(
            {
                "type": "mapping",
                "mapping": self.mapping_json(),
                "transcript": self.transcript_json(),
            }
        )

    def _on_interim(self, text: str) -> None:
        self.interim = text
        self.broadcast({"type": "interim", "text": text})

    def _on_utterance_end(self) -> None:
        last = next((s for s in reversed(self.transcript.segments) if not s.is_gap), None)
        if last is None:
            return
        turn: list[str] = []
        for seg in reversed(self.transcript.segments):
            if seg.is_gap or seg.label != last.label:
                break
            turn.append(seg.text)
        text = " ".join(reversed(turn))
        self.scheduler.on_utterance_end(last.label == self.them, text)

    def _on_gap(self, start: float, end: float, connection: int) -> None:
        seg = gap_segment(start, end, connection)
        self.transcript.append(seg)
        self.event("stt_gap", start=round(start, 2), end=round(end, 2))
        self.broadcast({"type": "segment", "segment": self._seg_json(seg)})

    # Coach calls

    def _live_status(self, state: str, latency: float | None, detail: str = "") -> None:
        if self.status["coach"].state == "down" and state != "ok":
            return
        self.set_status("coach", state, detail, latency)

    def _meta(self, trigger: str) -> str:
        elapsed = self.elapsed
        remaining = self.planned_minutes - elapsed / 60
        whole = self.transcript.talk_share(self.interviewer)
        recent = self.transcript.talk_share(self.interviewer, max(0.0, elapsed - TALK_WINDOW_S))
        gaps = ", ".join(f"{mmss(g.start)}-{mmss(g.end)}" for g in self.transcript.gaps())

        def pct(v: float | None) -> str:
            return "n/a" if v is None else f"{v:.2f}"

        return (
            "<interview_meta>\n"
            f"elapsed: {mmss(elapsed)}\n"
            f"planned_minutes: {self.planned_minutes}\n"
            f"minutes_remaining: {remaining:.1f}\n"
            f"trigger: {trigger}\n"
            f"interviewer_talk_share: session {pct(whole)}, last_3_min {pct(recent)}\n"
            f"stt_gaps: {gaps or 'none'}\n"
            f"speaker_mapping: {'locked' if self.mapper.locked else 'provisional'}\n"
            "</interview_meta>"
        )

    def _recent_outputs(self) -> str:
        cards = (self.current_cards + list(self.history))[:RECENT_CARDS]
        lines = ["<recent_outputs>", "Recent cards (newest first):"]
        if not cards:
            lines.append("none")
        for c in cards:
            ask = f" | ask: {c['ask']}" if c.get("ask") else ""
            lines.append(f"[{c['at']}] {c['kind']}: {c['headline']}{ask}")
        lines.append("Evidence logged so far:")
        if not self.evidence:
            lines.append("none")
        for e in self.evidence:
            hyps = ",".join(e.get("hypotheses", []))
            lines.append(f"[{e['at']}] {e['stance']} {hyps} {e['type']}: {e['note']}")
        lines.append("</recent_outputs>")
        return "\n".join(lines)

    def _volatile(self, mode: str, trigger: str, values: dict[str, str], extra: str = "") -> str:
        parts = [
            self.llm.mode_instructions(mode, values),
            self._meta(trigger),
            self._recent_outputs(),
        ]
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    async def _call(
        self,
        mode: str,
        trigger: str,
        volatile: str,
        on_cards: Callable[[CoachUpdate], None] | None = None,
    ) -> CallResult:
        closed, open_chunk = self.transcript.chunks()
        result = await self.llm.call(
            mode, trigger, closed, open_chunk, volatile, self.transcript.last_end, on_cards
        )
        self.coach_log.write(result.record)
        self.broadcast({"type": "cost", "total": round(self.llm.total_cost, 4)})
        return result

    async def _run_live(self, trigger: str) -> None:
        if not self.llm.available:
            return
        self._live_seq += 1
        seq = self._live_seq
        shown = False

        def on_cards(early: CoachUpdate) -> None:
            nonlocal shown
            if seq >= self._shown_seq:
                shown = self._apply_cards(early, seq)

        volatile = self._volatile("live", trigger, {"trigger": trigger})
        result = await self._call("live", trigger, volatile, on_cards)
        out = result.output
        if not isinstance(out, CoachUpdate) or seq < self._shown_seq:
            return
        at = mmss(self.elapsed)
        for ev in out.evidence:
            item = {**ev.model_dump(), "logged_at": at}
            self.evidence.append(item)
            self.evidence_log.write(item)
            self.broadcast({"type": "evidence", "item": item})
        if not shown:
            self._apply_cards(out, seq)

    def _apply_cards(self, out: CoachUpdate, seq: int) -> bool:
        """Show cards from a live update. Return True if cards were applied."""
        self._shown_seq = seq
        now = time.time()
        if out.intervene and out.cards:
            at = mmss(self.elapsed)
            for old in reversed(self.current_cards):
                self.history.appendleft(old)
            self.current_cards = [
                {**c.model_dump(), "at": at, "shown_at": now, "id": f"{seq}-{i}"}
                for i, c in enumerate(out.cards)
            ]
            self.last_quiet_at = None
        else:
            self.last_quiet_at = now
        self.broadcast(self.cards_json())
        return True

    def mark(self) -> bool:
        if self.phase != "recording" or not self.llm.available:
            return False
        mark_s = self.elapsed
        self.event("mark_pressed", at=round(mark_s, 2))
        started = self.mark_slot.start(self._supervised_user("mark", self._run_mark(mark_s)))
        if started:
            self.broadcast({"type": "mark_result", "state": "running", "at": mmss(mark_s)})
        else:
            self.broadcast({"type": "busy", "what": "mark"})
        return started

    def ask_next(self) -> bool:
        if self.phase != "recording" or not self.llm.available:
            return False
        now_s = self.elapsed
        self.event("ask_next_pressed", at=round(now_s, 2))
        started = self.ask_slot.start(self._supervised_user("ask_next", self._run_ask(now_s)))
        if started:
            self.broadcast({"type": "ask_next_result", "state": "running", "at": mmss(now_s)})
        else:
            self.broadcast({"type": "busy", "what": "ask_next"})
        return started

    async def _supervised_user(self, mode: str, coro: Coroutine[Any, Any, None]) -> None:
        timeout = self.cfg.coach.mark_timeout_s if mode == "mark" else self.cfg.coach.timeout_s
        kind = "mark_result" if mode == "mark" else "ask_next_result"
        try:
            await asyncio.wait_for(coro, timeout=timeout + 5)
        except Exception as exc:
            log.exception("%s call failed", mode)
            self.broadcast({"type": kind, "state": "error", "detail": type(exc).__name__})

    async def _run_mark(self, mark_s: float) -> None:
        window = self.transcript.window(mark_s - MARK_WINDOW_S, mark_s)
        extra = (
            f"<mark_window start={mmss(max(0.0, mark_s - MARK_WINDOW_S))} end={mmss(mark_s)}>\n"
            f"{render_turns(window) or EMPTY_WINDOW}\n</mark_window>"
        )
        values = {"mark_time": mmss(mark_s)}
        result = await self._call("mark", "MARK", self._volatile("mark", "MARK", values, extra))
        out = result.output
        record = {
            "at": round(mark_s, 2),
            "at_mmss": mmss(mark_s),
            "output": result.record["output"],
        }
        self.marks_log.write(record)
        if not isinstance(out, MarkAnalysis):
            self.broadcast({"type": "mark_result", "state": "error", "detail": "no valid output"})
            return
        self.pinned = {"kind": "mark", "at": mmss(mark_s), **out.model_dump()}
        self.broadcast({"type": "mark_result", "state": "done", "result": self.pinned})

    async def _run_ask(self, now_s: float) -> None:
        values = {"now": mmss(now_s)}
        result = await self._call(
            "ask_next", "ASK_NEXT", self._volatile("ask_next", "ASK_NEXT", values)
        )
        out = result.output
        self.asks_log.write(
            {"at": round(now_s, 2), "at_mmss": mmss(now_s), "output": result.record["output"]}
        )
        if not isinstance(out, AskNext):
            self.broadcast(
                {"type": "ask_next_result", "state": "error", "detail": "no valid output"}
            )
            return
        self.pinned = {"kind": "ask_next", "at": mmss(now_s), **out.model_dump()}
        self.broadcast({"type": "ask_next_result", "state": "done", "result": self.pinned})

    def swap_speakers(self) -> None:
        if not self.mapper.mapped:
            return
        self.mapper.swap()
        self._mapping_changed("swap")

    def dismiss_pinned(self) -> None:
        self.pinned = None
        self.broadcast({"type": "pinned", "pinned": None})

    # Views

    def _seg_json(self, seg: Segment) -> dict:
        return {
            "start": mmss(seg.start),
            "label": seg.label,
            "text": seg.text,
            "gap": seg.is_gap,
        }

    def transcript_json(self) -> list[dict]:
        return [self._seg_json(s) for s in self.transcript.recent(UI_TURNS)]

    def mapping_json(self) -> dict:
        return {
            "mapped": self.mapper.mapped,
            "locked": self.mapper.locked,
            "interviewer": self.interviewer,
            "them": self.them,
        }

    def cards_json(self) -> dict:
        return {
            "type": "cards",
            "current": self.current_cards,
            "history": list(self.history),
            "quiet_since": self.last_quiet_at,
        }

    def snapshot(self) -> dict:
        recent = self.transcript.talk_share(
            self.interviewer, max(0.0, self.elapsed - TALK_WINDOW_S)
        )
        return {
            "type": "snapshot",
            "phase": self.phase,
            "interviewee": self.interviewee,
            "organization": self.organization,
            "planned_minutes": self.planned_minutes,
            "elapsed": round(self.elapsed, 1),
            "preflight": self.preflight,
            "status": self.status_json(),
            "mapping": self.mapping_json(),
            "talk_recent": recent,
            "transcript": self.transcript_json(),
            "interim": self.interim,
            "cards": self.cards_json(),
            "evidence": self.evidence,
            "pinned": self.pinned,
            "busy": {"mark": self.mark_slot.busy, "ask_next": self.ask_slot.busy},
            "cost": round(self.llm.total_cost, 4),
            "replay": self.replay is not None,
            "server_time": time.time(),
        }

    def talk_json(self) -> dict:
        recent = self.transcript.talk_share(
            self.interviewer, max(0.0, self.elapsed - TALK_WINDOW_S)
        )
        return {"type": "talk", "recent": recent}

    # Finalize

    def request_end(self) -> None:
        """Start finalize in the background. Repeated calls do nothing."""
        if self._end_task is None:
            self._end_task = asyncio.get_running_loop().create_task(self.finalize())

    async def finalize(self) -> None:
        """Stop everything and write the final files. Safe to call twice."""
        if self._finalizing:
            await self.finalized.wait()
            return
        self._finalizing = True
        try:
            await self._finalize_steps()
        finally:
            self.phase = "ended"
            self.finalized.set()
            self.on_ended()

    async def _finalize_steps(self) -> None:
        was_recording = self.phase == "recording"
        self.phase = "finalizing"
        self.broadcast({"type": "session_end", "state": "finalizing"})
        steps: dict[str, str] = {}
        if was_recording and self.recorder is not None:
            await asyncio.to_thread(self.recorder.stop)
            steps["audio_stop"] = "ok"
            if self.stt is not None:
                if (
                    self.stt.state != "live"
                    and self.stt.sent_end_sample < self.recorder.samples_written
                ):
                    sr = self.cfg.audio.sample_rate
                    self._on_gap(
                        self.stt.sent_end_sample / sr, self.recorder.seconds, self.stt.connection
                    )
                try:
                    await self.stt.close()
                    steps["stt_close"] = "ok"
                except Exception as exc:
                    log.exception("STT close failed")
                    steps["stt_close"] = f"failed: {type(exc).__name__}"
        for task in self._tasks + [t for t in (self.scheduler.task,) if t is not None]:
            task.cancel()
        for slot in (self.mark_slot, self.ask_slot):
            if slot.task is not None:
                slot.task.cancel()
        update_session_json(
            self.dir,
            final_mapping={f"{c}:{k}": v for (c, k), v in sorted(self.mapper.mapping.items())},
            final_loud_label=self.mapper.loud_label,
        )
        steps.update(await finalize_files(self.cfg, self.dir, self.skip_batch))
        update_session_json(
            self.dir,
            ended_at=datetime.now().isoformat(timespec="seconds"),
            duration_s=round(self.elapsed, 2),
            costs={"coach_usd": round(self.llm.total_cost, 4), "coach_calls": self.llm.calls},
            mapping_history=self.mapper.history,
            stt_dropped_blocks=self.stt.dropped_blocks if self.stt else 0,
            finalize_steps=steps,
        )
        for writer in (
            self.events,
            self.coach_log,
            self.marks_log,
            self.asks_log,
            self.evidence_log,
        ):
            writer.close()
        await self.llm.close()
        self.broadcast({"type": "session_end", "state": "ended", "dir": str(self.dir)})
        print_summary(self.dir, self.llm.total_cost, self.llm.calls, steps)


EMPTY_WINDOW = "(no finalized speech in this window)"


def print_summary(session_dir: Path, cost: float, calls: int, steps: dict[str, str]) -> None:
    print("\nSession files:")
    for path in sorted(session_dir.iterdir()):
        if path.is_file():
            print(f"  {path}")
    print("Finalize steps: " + ", ".join(f"{k}={v}" for k, v in steps.items()))
    print(f"Coach cost: ${cost:.4f} over {calls} calls")


def wav_rms_window(
    wav_path: Path, sample_rate: int, block_frames: int
) -> Callable[[float, float], list[float]]:
    """Build a per-block RMS lookup from a 16 kHz mono int16 WAV, reading it in chunks."""
    rms_log = RmsLog(block_frames, sample_rate)
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getframerate() != sample_rate or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError(f"{wav_path} is not {sample_rate} Hz mono int16")
        while True:
            chunk = wf.readframes(block_frames * 600)
            if not chunk:
                break
            data = np.frombuffer(chunk, dtype=np.int16)
            n_blocks = len(data) // block_frames
            if n_blocks == 0:
                break
            blocks = data[: n_blocks * block_frames].astype(np.float32) / 32768.0
            blocks = blocks.reshape(n_blocks, block_frames)
            for value in np.sqrt(np.mean(blocks * blocks, axis=1)):
                rms_log.append(float(value))
    return rms_log.window


def _session_meta(session_dir: Path) -> tuple[str, str, str, str, str]:
    meta = read_json(session_dir / "session.json")
    name = meta.get("interviewee", "Interviewee")
    org = meta.get("organization", "")
    labels = meta.get("labels", {})
    started = meta.get("started_at") or meta.get("created_at") or ""
    # Sessions recorded before the rename stored this label under "preston".
    interviewer = labels.get("interviewer") or labels.get("preston", "INTERVIEWER")
    them = labels.get("interviewee", them_label_for(name))
    return name, org, interviewer, them, started


def _marks(session_dir: Path) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    path = session_dir / "marks.jsonl"
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        headline = (rec.get("output") or {}).get("headline") or "(mark analysis unavailable)"
        out.append((float(rec.get("at", 0.0)), headline))
    return out


def _header(session_dir: Path, duration_s: float) -> tuple[str, str]:
    name, org, _, _, started = _session_meta(session_dir)
    title = f"Interview: {name} ({org})" if org else f"Interview: {name}"
    try:
        date = datetime.fromisoformat(started).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        date = started
    total = int(duration_s)
    dur = f"{total // 60}:{total % 60:02d}"
    return title, f"Date: {date}  Duration: {dur}"


def write_live_markdown(session_dir: Path, segments: list[Segment], duration_s: float) -> None:
    title, date_line = _header(session_dir, duration_s)
    text = render_markdown(
        title,
        date_line,
        "Source: Deepgram live nova-3, diarized. Speaker labels mapped automatically.",
        segments,
        _marks(session_dir),
    )
    (session_dir / "transcript_live.md").write_text(text)


def wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


async def run_batch(cfg: Config, session_dir: Path) -> None:
    """Batch-transcribe audio.wav and write transcript_deepgram.json and transcript.md."""
    wav = session_dir / "audio.wav"
    name, org, interviewer, them, _ = _session_meta(session_dir)
    terms = list(cfg.deepgram.keyterms) + [
        t for t in (name, org) if t and t not in cfg.deepgram.keyterms
    ]
    response = await stt_batch.transcribe(wav, cfg.deepgram, cfg.deepgram_api_key, terms)
    (session_dir / "transcript_deepgram.json").write_text(json.dumps(response, indent=1))
    batch = stt_batch.batch_segments(response)
    live = load_live_segments(session_dir)
    window = await asyncio.to_thread(
        wav_rms_window, wav, cfg.audio.sample_rate, cfg.audio.block_frames
    )
    labels = map_batch_speakers(batch, live, window, interviewer, them)
    for seg in batch:
        seg.label = labels.get(seg.speaker_id, f"S{seg.speaker_id}")
    title, date_line = _header(session_dir, wav_duration(wav))
    text = render_markdown(
        title,
        date_line,
        "Source: Deepgram prerecorded nova-3, diarized. Speaker labels mapped automatically.",
        batch,
        _marks(session_dir),
    )
    (session_dir / "transcript.md").write_text(text)


def final_mapping(session_dir: Path) -> tuple[dict[str, str], str | None]:
    """Return the last id mapping as {"conn:speaker": label} and the loud-side label.

    session.json holds both after a clean finalize. After a crash, the last
    mapping event in events.jsonl holds them.
    """
    meta = read_json(session_dir / "session.json")
    if meta.get("final_mapping") is not None:
        return meta["final_mapping"], meta.get("final_loud_label")
    mapping: dict[str, str] = {}
    loud_label: str | None = None
    path = session_dir / "events.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("kind") == "mapping" and event.get("history"):
                last = event["history"][-1]
                mapping = last.get("mapping", mapping)
                loud_label = last.get("loud_label", loud_label)
    return mapping, loud_label


def load_live_segments(session_dir: Path) -> list[Segment]:
    """Load live segments with labels from the final speaker mapping."""
    segments = load_jsonl(session_dir / "transcript_live.jsonl")
    mapping, loud_label = final_mapping(session_dir)
    _, _, interviewer, them, _ = _session_meta(session_dir)
    loud = loud_label or interviewer
    quiet = them if loud == interviewer else interviewer
    for seg in segments:
        if seg.is_gap:
            continue
        if seg.side is not None:
            seg.label = loud if seg.side == "loud" else quiet
        else:
            seg.label = mapping.get(f"{seg.connection}:{seg.speaker_id}", seg.label)
    return segments


def describe_error(exc: BaseException | None) -> str:
    """Short, key-free description of a batch failure."""
    if isinstance(exc, httpx2.HTTPStatusError):
        return f"Deepgram HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"[:200]


def write_fallback_transcript(session_dir: Path, duration_s: float, reason: str) -> None:
    live = load_live_segments(session_dir)
    title, date_line = _header(session_dir, duration_s)
    note = (
        f"Batch transcription failed ({reason}). This transcript comes from the live pass. "
        f"Retry with: uv run coach finalize {session_dir}"
    )
    text = render_markdown(
        title,
        date_line,
        "Source: Deepgram live nova-3, diarized. Speaker labels mapped automatically.",
        live,
        _marks(session_dir),
        note=note,
    )
    (session_dir / "transcript.md").write_text(text)


async def finalize_files(
    cfg: Config,
    session_dir: Path,
    skip_batch: asyncio.Event,
) -> dict[str, str]:
    """Write audio.wav, transcript_live.md, and transcript.md. Return step status."""
    steps: dict[str, str] = {}
    pcm = session_dir / "audio.pcm"
    wav = session_dir / "audio.wav"
    if pcm.exists():
        try:
            n = await asyncio.to_thread(pcm_to_wav, pcm, wav, cfg.audio.sample_rate)
            pcm.unlink()
            steps["wav"] = f"ok ({n / cfg.audio.sample_rate:.1f}s)"
        except OSError as exc:
            log.exception("WAV write failed")
            steps["wav"] = f"failed: {exc}"
    elif wav.exists():
        steps["wav"] = "exists"
    else:
        steps["wav"] = "no audio"
    duration = wav_duration(wav) if wav.exists() else 0.0
    live = load_live_segments(session_dir)
    write_live_markdown(session_dir, live, duration)
    steps["transcript_live_md"] = "ok"
    if not wav.exists():
        write_fallback_transcript(session_dir, duration, "no audio.wav")
        steps["batch"] = "skipped: no audio"
        return steps
    if skip_batch.is_set():
        write_fallback_transcript(session_dir, duration, "skipped by second Ctrl-C")
        steps["batch"] = "skipped"
        print(f"Batch step skipped. Retry with: uv run coach finalize {session_dir}")
        return steps
    batch = asyncio.create_task(run_batch(cfg, session_dir))
    skipper = asyncio.create_task(skip_batch.wait())
    done, _ = await asyncio.wait({batch, skipper}, return_when=asyncio.FIRST_COMPLETED)
    skipper.cancel()
    if batch in done and batch.exception() is None:
        steps["batch"] = "ok"
        return steps
    if batch in done:
        reason = describe_error(batch.exception())
        log.error("Batch transcription failed: %s", reason)
    else:
        batch.cancel()
        reason = "skipped by second Ctrl-C"
    write_fallback_transcript(session_dir, duration, reason)
    steps["batch"] = f"failed: {reason}"
    print(f"Batch transcription did not complete. Retry with: uv run coach finalize {session_dir}")
    return steps
