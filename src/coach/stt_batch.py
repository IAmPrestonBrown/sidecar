"""Deepgram prerecorded transcription of the final WAV."""

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx2

from coach.config import DeepgramConfig
from coach.transcript import Segment

log = logging.getLogger(__name__)

BATCH_URL = "https://api.deepgram.com/v1/listen"
BATCH_TIMEOUT_S = 300.0
PROGRESS_EVERY_S = 5.0


def batch_params(cfg: DeepgramConfig, keyterms: list[str]) -> list[tuple[str, str]]:
    params = [
        ("model", cfg.model),
        ("language", cfg.language),
        ("diarize_model", "latest"),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("utterances", "true"),
    ]
    if cfg.mip_opt_out:
        params.append(("mip_opt_out", "true"))
    params.extend(("keyterm", term) for term in keyterms)
    return params


async def transcribe(
    wav_path: Path,
    cfg: DeepgramConfig,
    api_key: str,
    keyterms: list[str],
    progress: Callable[[str], None] = print,
) -> dict:
    """POST the WAV to Deepgram and return the parsed JSON response."""
    if not api_key:
        raise RuntimeError("DEEPGRAM_API_KEY missing")
    size_mb = wav_path.stat().st_size / 1e6
    progress(f"Batch transcription: uploading {size_mb:.1f} MB to Deepgram")
    started = time.monotonic()

    async def ticker() -> None:
        while True:
            await asyncio.sleep(PROGRESS_EVERY_S)
            progress(f"  waiting for Deepgram... {time.monotonic() - started:.0f}s")

    tick = asyncio.create_task(ticker())
    try:
        async with httpx2.AsyncClient(timeout=BATCH_TIMEOUT_S) as client:
            with open(wav_path, "rb") as fh:
                resp = await client.post(
                    BATCH_URL,
                    params=batch_params(cfg, keyterms),
                    headers={"Authorization": f"Token {api_key}", "Content-Type": "audio/wav"},
                    content=fh.read(),
                )
        resp.raise_for_status()
        progress(f"Batch transcription done in {time.monotonic() - started:.0f}s")
        return resp.json()
    finally:
        tick.cancel()


def batch_segments(response: dict) -> list[Segment]:
    """Convert a prerecorded response into segments, one per utterance."""
    out: list[Segment] = []
    for utt in response.get("results", {}).get("utterances", []) or []:
        words = [(float(w["start"]), float(w["end"])) for w in utt.get("words", [])]
        out.append(
            Segment(
                start=float(utt["start"]),
                end=float(utt["end"]),
                connection=0,
                speaker_id=int(utt.get("speaker", 0)),
                label="",
                text=utt.get("transcript", "").strip(),
                words=words,
            )
        )
    return out
