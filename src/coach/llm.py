"""Claude request building, prompt caching layout, validation, and cost tracking."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import anthropic
from pydantic import BaseModel

from coach.config import Config, Prices
from coach.schemas import MODE_TOOLS, TOOLS, CoachUpdate, validate_output

log = logging.getLogger(__name__)

EMPTY_CHUNK = "(no finalized speech yet)"
ACTIVITY_LEVELS = {
    "quiet": (
        "Activity level: QUIET. Aim for 2-5 interventions in the whole interview. "
        "Intervene only when one question or warning would clearly increase what "
        "the interviewer learns. When unsure, stay silent."
    ),
    "balanced": (
        "Activity level: BALANCED. Aim for roughly one card every 1-2 minutes of "
        "conversation. Intervene when one question would likely increase what the interviewer "
        "learns, even if it is not decisive. When the interviewee says something "
        "concrete that nobody has pulled on yet, that is usually worth a card."
    ),
    "active": (
        "Activity level: ACTIVE. Aim for roughly one card per minute of conversation. "
        "Offer a follow-up whenever the interviewee says something concrete, vague, or "
        "surprising that has not been pulled on yet."
    ),
}
CACHE = {"type": "ephemeral"}


@dataclass(frozen=True)
class SessionHeader:
    interviewee: str
    organization: str
    planned_minutes: int
    interviewer_label: str
    them_label: str

    def render(self) -> str:
        return (
            "<session>\n"
            f"Interviewee: {self.interviewee}\n"
            f"Organization: {self.organization}\n"
            f"Planned minutes: {self.planned_minutes}\n"
            f"Transcript labels: {self.interviewer_label} is the interviewer. "
            f"{self.them_label} is {self.interviewee} (the interviewee).\n"
            "</session>"
        )


@dataclass(frozen=True)
class ModeSettings:
    model: str
    max_tokens: int
    effort: str
    thinking: str
    timeout: float

    def request(self, system: list[dict], messages: list[dict], max_tokens: int) -> dict:
        """Request body. Thinking and effort are part of the cached prefix."""
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "thinking": {"type": self.thinking},
            "output_config": {"effort": self.effort},
            "system": system,
            "tools": TOOLS,
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
            "messages": messages,
        }


@dataclass
class CallResult:
    mode: str
    output: BaseModel | None
    record: dict


def call_cost(usage: dict, prices: Prices) -> float:
    """Return the dollar cost of one call from its usage fields."""
    return (
        usage.get("input_tokens", 0) * prices.input
        + usage.get("output_tokens", 0) * prices.output
        + usage.get("cache_read_input_tokens", 0) * prices.cache_read
        + usage.get("cache_creation_input_tokens", 0) * prices.cache_write
    ) / 1_000_000


def load_prompt(prompts_dir: Path, name: str) -> str:
    return (prompts_dir / name).read_text()


def build_system(cfg: Config, header: SessionHeader, notes_path: Path | None) -> list[dict]:
    """System blocks A and B. Block B carries the cache breakpoint."""
    brief = cfg.brief_path.read_text()
    parts = [f"<research_brief>\n{brief.strip()}\n</research_brief>"]
    if notes_path is not None and notes_path.exists():
        parts.append(f"<interviewee_notes>\n{notes_path.read_text().strip()}\n</interviewee_notes>")
    parts.append(header.render())
    return [
        {"type": "text", "text": load_prompt(cfg.prompts_dir, "coach_system.md")},
        {"type": "text", "text": "\n\n".join(parts), "cache_control": CACHE},
    ]


def build_user_content(closed: list[str], open_chunk: str, volatile: str) -> list[dict]:
    """Transcript chunks then the volatile block. The last closed chunk is cached."""
    blocks: list[dict] = []
    for i, text in enumerate(closed):
        wrapped = f"<transcript_chunk index={i + 1}>\n{text}\n</transcript_chunk>"
        block: dict = {"type": "text", "text": wrapped}
        if i == len(closed) - 1:
            block["cache_control"] = CACHE
        blocks.append(block)
    body = open_chunk or EMPTY_CHUNK
    wrapped_open = f"<transcript_open_chunk>\n{body}\n</transcript_open_chunk>"
    blocks.append({"type": "text", "text": wrapped_open})
    blocks.append({"type": "text", "text": volatile})
    return blocks


class CoachLLM:
    """Builds and sends coach requests for the three modes."""

    def __init__(
        self,
        cfg: Config,
        header: SessionHeader,
        notes_path: Path | None,
        debug_dir: Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.system = build_system(cfg, header, notes_path)
        if cfg.coach.live_activity not in ACTIVITY_LEVELS:
            raise ValueError(
                f"live_activity must be one of {', '.join(ACTIVITY_LEVELS)}, "
                f"not {cfg.coach.live_activity!r}"
            )
        self.activity = ACTIVITY_LEVELS[cfg.coach.live_activity]
        self.mode_templates = {
            mode: load_prompt(cfg.prompts_dir, f"mode_{mode}.md") for mode in MODE_TOOLS
        }
        self.debug_dir = debug_dir
        self.total_cost = 0.0
        self.calls = 0
        self.client = (
            anthropic.AsyncAnthropic(
                api_key=cfg.anthropic_api_key, timeout=cfg.coach.timeout_s, max_retries=0
            )
            if cfg.anthropic_api_key
            else None
        )

    @property
    def available(self) -> bool:
        return self.client is not None

    def mode_settings(self, mode: str) -> ModeSettings:
        c = self.cfg.coach
        if mode == "live":
            return ModeSettings(
                c.live_model, c.live_max_tokens, c.live_effort, c.live_thinking, c.timeout_s
            )
        if mode == "mark":
            return ModeSettings(
                c.mark_model, c.mark_max_tokens, c.mark_effort, c.mark_thinking, c.mark_timeout_s
            )
        return ModeSettings(
            c.ask_model, c.ask_max_tokens, c.ask_effort, c.ask_thinking, c.timeout_s
        )

    def mode_instructions(self, mode: str, values: dict[str, str]) -> str:
        return self.mode_templates[mode].strip().format(activity=self.activity, **values)

    def build_request(self, mode: str, closed: list[str], open_chunk: str, volatile: str) -> dict:
        ms = self.mode_settings(mode)
        content = build_user_content(closed, open_chunk, volatile)
        return ms.request(self.system, [{"role": "user", "content": content}], ms.max_tokens)

    async def prewarm(self, mode: str) -> dict:
        """Write the tools and system prefix to the cache with a max_tokens=0 call."""
        if self.client is None:
            raise RuntimeError("ANTHROPIC_API_KEY missing")
        ms = self.mode_settings(mode)
        request = ms.request(self.system, [{"role": "user", "content": "warmup"}], 0)
        response = await self.client.with_options(timeout=60.0).messages.create(**request)
        usage = response.usage.model_dump(exclude_none=True)
        cost = call_cost(usage, self.cfg.prices)
        self.total_cost += cost
        log.info(
            "prewarm %s cache_read=%s cache_write=%s $%.4f",
            mode,
            usage.get("cache_read_input_tokens"),
            usage.get("cache_creation_input_tokens"),
            cost,
        )
        return {"mode": f"prewarm_{mode}", "usage": usage, "cost_usd": round(cost, 6)}

    async def call(
        self,
        mode: str,
        trigger: str,
        closed: list[str],
        open_chunk: str,
        volatile: str,
        position_s: float,
        on_cards: Callable[[CoachUpdate], None] | None = None,
    ) -> CallResult:
        """Stream one request. API errors propagate. Bad output returns output=None.

        For live mode, on_cards receives the cards as soon as the cards array
        is complete, before the evidence list streams in.
        """
        if self.client is None:
            raise RuntimeError("ANTHROPIC_API_KEY missing")
        request = self.build_request(mode, closed, open_chunk, volatile)
        ms = self.mode_settings(mode)
        self._debug_dump(mode, request)
        tool_name, _ = MODE_TOOLS[mode]
        started = time.time()
        t0 = time.monotonic()
        first_card_s: float | None = None
        client = self.client.with_options(timeout=ms.timeout)
        async with client.messages.stream(**request) as stream:
            async for event in stream:
                if on_cards is None or first_card_s is not None or event.type != "input_json":
                    continue
                snap = event.snapshot
                if isinstance(snap, dict) and "evidence" in snap:
                    early = validate_output("live", {**snap, "evidence": []})
                    if isinstance(early, CoachUpdate):
                        first_card_s = time.monotonic() - t0
                        on_cards(early)
            response = await stream.get_final_message()
        latency = time.monotonic() - t0
        usage = response.usage.model_dump(exclude_none=True)
        cost = call_cost(usage, self.cfg.prices)
        self.total_cost += cost
        self.calls += 1
        output: BaseModel | None = None
        raw_input = None
        if response.stop_reason == "refusal":
            log.warning("Coach %s call refused: %s", mode, response.stop_details)
        else:
            for block in response.content:
                if block.type == "tool_use" and block.name == tool_name:
                    raw_input = block.input
                    output = validate_output(mode, block.input)
                    break
            else:
                log.warning("Coach %s call returned no %s tool call", mode, tool_name)
        log.info(
            "coach %s trigger=%s latency=%.2fs cards_at=%s in=%s cache_read=%s cache_write=%s "
            "out=%s $%.4f",
            mode,
            trigger,
            latency,
            f"{first_card_s:.2f}s" if first_card_s is not None else "-",
            usage.get("input_tokens"),
            usage.get("cache_read_input_tokens"),
            usage.get("cache_creation_input_tokens"),
            usage.get("output_tokens"),
            cost,
        )
        record = {
            "mode": mode,
            "trigger": trigger,
            "request_time": started,
            "latency_s": round(latency, 3),
            "cards_latency_s": round(first_card_s, 3) if first_card_s is not None else None,
            "model": request["model"],
            "stop_reason": response.stop_reason,
            "usage": usage,
            "cost_usd": round(cost, 6),
            "output": output.model_dump() if output is not None else None,
            "discarded_input": raw_input if output is None else None,
            "position_s": round(position_s, 2),
        }
        return CallResult(mode, output, record)

    def _debug_dump(self, mode: str, request: dict) -> None:
        if self.debug_dir is None or not self.cfg.coach.debug_prompts:
            return
        self.debug_dir.mkdir(exist_ok=True)
        path = self.debug_dir / f"{time.time():.3f}_{mode}.json"
        path.write_text(json.dumps(request, indent=1))

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
