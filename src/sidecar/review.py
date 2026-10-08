"""Everything the call review page shows, read from a coach session folder."""

import json
from pathlib import Path

from sidecar.models import Call
from sidecar.store import NotFoundError


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _segments(folder: Path) -> tuple[list[dict], str]:
    """Final transcript segments when the batch pass wrote them, else the live ones."""
    for name, source in (("transcript.jsonl", "final"), ("transcript_live.jsonl", "live")):
        rows = [
            {"start": r["start"], "end": r["end"], "label": r.get("label", ""), "text": r["text"]}
            for r in _jsonl(folder / name)
            if r.get("text") and r.get("speaker_id", 0) >= 0
        ]
        if rows:
            return sorted(rows, key=lambda r: r["start"]), source
    return [], "none"


def session_folder(call: Call) -> Path:
    folder = Path(call.session_dir)
    if not call.session_dir or not folder.is_dir():
        raise NotFoundError("The session folder for this call is missing")
    return folder


def call_review(call: Call) -> dict:
    folder = session_folder(call)
    segments, source = _segments(folder)
    marks = []
    for rec in _jsonl(folder / "marks.jsonl"):
        out = rec.get("output") or {}
        marks.append(
            {
                "at": float(rec.get("at", 0.0)),
                "headline": out.get("headline", "Mark"),
                "claim": out.get("claim", ""),
                "unknown": out.get("unknown", ""),
                "ask": out.get("ask", ""),
            }
        )
    asks = [
        {"at": float(rec.get("at", 0.0)), "ask": (rec.get("output") or {}).get("ask", "")}
        for rec in _jsonl(folder / "asks.jsonl")
        if (rec.get("output") or {}).get("ask")
    ]
    try:
        meta = json.loads((folder / "session.json").read_text())
    except OSError, json.JSONDecodeError:
        meta = {}
    return {
        "segments": segments,
        "transcript_source": source,
        "marks": marks,
        "asks": asks,
        "has_audio": (folder / "audio.wav").exists(),
        "duration_s": float(meta.get("duration_s") or call.duration_s or 0.0),
        "labels": meta.get("labels", {}),
    }
