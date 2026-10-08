"""Finalized transcript segments, turn rendering, chunking, and talk ratio."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

GAP_SPEAKER = -1
GAP_LABEL = "GAP"


def mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def hhmmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}"


@dataclass(slots=True)
class Segment:
    """A run of finalized words from one diarized speaker on one connection.

    words holds (start, end) pairs in absolute session seconds. side is "loud"
    or "quiet" once the loudness classifier has labeled the segment.
    """

    start: float
    end: float
    connection: int
    speaker_id: int
    label: str
    text: str
    words: list[tuple[float, float]] = field(default_factory=list)
    side: str | None = None

    @property
    def is_gap(self) -> bool:
        return self.speaker_id == GAP_SPEAKER

    @property
    def key(self) -> tuple[int, int]:
        return (self.connection, self.speaker_id)

    def to_json(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "connection": self.connection,
            "speaker_id": self.speaker_id,
            "label": self.label,
            "text": self.text,
            "words": [[round(a, 3), round(b, 3)] for a, b in self.words],
            "side": self.side,
        }

    @classmethod
    def from_json(cls, data: dict) -> Segment:
        return cls(
            start=data["start"],
            end=data["end"],
            connection=data["connection"],
            speaker_id=data["speaker_id"],
            label=data["label"],
            text=data["text"],
            words=[(a, b) for a, b in data.get("words", [])],
            side=data.get("side"),
        )


def gap_segment(start: float, end: float, connection: int) -> Segment:
    text = f"[live transcription gap {mmss(start)}-{mmss(end)}]"
    return Segment(start, end, connection, GAP_SPEAKER, GAP_LABEL, text)


def render_turns(segments: list[Segment], fmt: Callable[[float], str] = mmss) -> str:
    """Render segments as one line per turn. Same-label neighbors merge."""
    lines: list[str] = []
    cur_label: str | None = None
    cur_start = 0.0
    cur_text: list[str] = []

    def flush() -> None:
        if cur_label is not None and cur_text:
            lines.append(f"[{fmt(cur_start)}] {cur_label}: {' '.join(cur_text)}")

    for seg in segments:
        if seg.is_gap:
            flush()
            cur_label, cur_text = None, []
            lines.append(f"[{fmt(seg.start)}] {seg.text}")
            continue
        if seg.label != cur_label:
            flush()
            cur_label, cur_start, cur_text = seg.label, seg.start, []
        cur_text.append(seg.text)
    flush()
    return "\n".join(lines)


class TranscriptStore:
    """Append-only store of finalized segments.

    Chunks group segments for prompt caching. A chunk closes at the first turn
    boundary after it spans chunk_seconds. Closed chunk text is frozen and only
    re-rendered when the label version changes.
    """

    def __init__(self, chunk_seconds: float, jsonl_path: Path | None = None) -> None:
        self.chunk_seconds = chunk_seconds
        self.segments: list[Segment] = []
        self.jsonl_path = jsonl_path
        self.label_version = 0
        self._chunk_starts: list[int] = [0]
        self._frozen: dict[int, tuple[int, str]] = {}

    def __len__(self) -> int:
        return len(self.segments)

    @property
    def last_end(self) -> float:
        return self.segments[-1].end if self.segments else 0.0

    def append(self, seg: Segment) -> None:
        """Add a finalized segment and persist it."""
        if self.segments:
            prev = self.segments[-1]
            open_start = self.segments[self._chunk_starts[-1]].start
            boundary = prev.label != seg.label or seg.is_gap or prev.is_gap
            if boundary and prev.end - open_start >= self.chunk_seconds:
                self._chunk_starts.append(len(self.segments))
        self.segments.append(seg)
        if self.jsonl_path is not None:
            with open(self.jsonl_path, "a") as fh:
                fh.write(json.dumps(seg.to_json()) + "\n")
                fh.flush()

    def relabel(self, label_for: Callable[[Segment], str]) -> bool:
        """Apply a new speaker mapping. Return True if any label changed."""
        changed = False
        for seg in self.segments:
            if seg.is_gap:
                continue
            new = label_for(seg)
            if new != seg.label:
                seg.label = new
                changed = True
        if changed:
            self.label_version += 1
        return changed

    def chunks(self) -> tuple[list[str], str]:
        """Return (closed chunk texts, open chunk text)."""
        bounds = [*self._chunk_starts, len(self.segments)]
        closed: list[str] = []
        for i in range(len(self._chunk_starts) - 1):
            cached = self._frozen.get(i)
            if cached is None or cached[0] != self.label_version:
                text = render_turns(self.segments[bounds[i] : bounds[i + 1]])
                cached = (self.label_version, text)
                self._frozen[i] = cached
            closed.append(cached[1])
        open_text = render_turns(self.segments[bounds[-2] : bounds[-1]])
        return closed, open_text

    def window(self, start_s: float, end_s: float) -> list[Segment]:
        return [s for s in self.segments if s.end >= start_s and s.start <= end_s]

    def recent(self, n_turns: int) -> list[Segment]:
        """Return the segments making up roughly the last n turns."""
        out: list[Segment] = []
        turns = 0
        last_label: str | None = None
        for seg in reversed(self.segments):
            if seg.label != last_label:
                turns += 1
                last_label = seg.label
                if turns > n_turns:
                    break
            out.append(seg)
        out.reverse()
        return out

    def talk_share(self, label: str, since_s: float = 0.0) -> float | None:
        """Share of word duration spoken by label since since_s."""
        mine = total = 0.0
        for seg in reversed(self.segments):
            if seg.end < since_s:
                break
            if seg.is_gap:
                continue
            dur = sum(b - a for a, b in seg.words if b >= since_s)
            total += dur
            if seg.label == label:
                mine += dur
        if total <= 0:
            return None
        return mine / total

    def gaps(self) -> list[Segment]:
        return [s for s in self.segments if s.is_gap]


def load_jsonl(path: Path) -> list[Segment]:
    """Read segments from transcript_live.jsonl. Skip a torn final line."""
    out: list[Segment] = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            out.append(Segment.from_json(json.loads(line)))
        except json.JSONDecodeError, KeyError:
            continue
    return out


def render_markdown(
    title: str,
    date_line: str,
    source_line: str,
    segments: list[Segment],
    marks: list[tuple[float, str]],
    note: str = "",
) -> str:
    """Render the final transcript.md text."""
    parts = [f"# {title}", date_line, source_line]
    if note:
        parts.append(f"\n> {note}")
    parts.append("")
    parts.append(render_turns(segments, fmt=hhmmss))
    if marks:
        parts.append("\n## Marks")
        parts.extend(f"[{hhmmss(t)}] {headline}" for t, headline in marks)
    return "\n".join(parts) + "\n"
