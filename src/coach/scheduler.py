"""Decides when to run live coach calls and guards user-initiated calls."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import anthropic

log = logging.getLogger(__name__)

THEM_TURN_END = "THEM_TURN_END"
ME_TURN_END = "ME_TURN_END"
TIMER = "TIMER"
TIMER_MIN_WORDS = 20
ME_MIN_WORDS = 15

LiveRunner = Callable[[str], Awaitable[None]]
StatusSink = Callable[[str, float | None, str], None]


class LiveScheduler:
    """Coalesces triggers into at most one in-flight live call.

    tick() must be called periodically. It fires the timer trigger and any
    pending trigger once the minimum interval has passed.
    """

    def __init__(
        self,
        run_live: LiveRunner,
        min_interval_s: float,
        timer_interval_s: float,
        them_trigger_words: int,
        timeout_s: float,
        clock: Callable[[], float] = time.monotonic,
        on_status: StatusSink | None = None,
    ) -> None:
        self.run_live = run_live
        self.min_interval_s = min_interval_s
        self.timer_interval_s = timer_interval_s
        self.them_trigger_words = them_trigger_words
        self.timeout_s = timeout_s
        self.clock = clock
        self.on_status = on_status
        self.enabled = False
        self.new_words = 0
        self.pending: str | None = None
        self.in_flight = False
        self.last_call: float | None = None
        self.task: asyncio.Task | None = None

    def add_words(self, n: int) -> None:
        self.new_words += n

    def on_utterance_end(self, is_them: bool, last_turn_text: str) -> None:
        if is_them:
            if self.new_words >= self.them_trigger_words:
                self.trigger(THEM_TURN_END)
            return
        text = last_turn_text.strip()
        if self.new_words > 0 and (text.endswith("?") or len(text.split()) >= ME_MIN_WORDS):
            self.trigger(ME_TURN_END)

    def trigger(self, reason: str) -> None:
        if not self.enabled:
            return
        if self.in_flight or not self._interval_ok():
            self.pending = reason
            return
        self._fire(reason)

    def tick(self) -> None:
        if not self.enabled or self.in_flight:
            return
        if self.pending is not None and self._interval_ok():
            reason, self.pending = self.pending, None
            self._fire(reason)
            return
        since = self.clock() - (self.last_call if self.last_call is not None else -1e9)
        if since >= self.timer_interval_s and self.new_words >= TIMER_MIN_WORDS:
            self._fire(TIMER)

    def _interval_ok(self) -> bool:
        if self.last_call is None:
            return True
        return self.clock() - self.last_call >= self.min_interval_s

    def _fire(self, reason: str) -> None:
        self.in_flight = True
        self.last_call = self.clock()
        self.new_words = 0
        self.task = asyncio.get_running_loop().create_task(self._run(reason))

    async def _run(self, reason: str) -> None:
        start = self.clock()
        try:
            await asyncio.wait_for(self.run_live(reason), timeout=self.timeout_s)
            self._status("ok", self.clock() - start)
        except TimeoutError:
            log.warning("Live coach call timed out after %.1fs", self.timeout_s)
            self._status("slow", self.clock() - start)
        except anthropic.APIError as exc:
            log.warning("Live coach call failed: %s: %s", type(exc).__name__, str(exc)[:200])
            self._status("error", None, type(exc).__name__)
        except Exception as exc:
            log.exception("Live coach call failed")
            self._status("error", None, type(exc).__name__)
        finally:
            self.in_flight = False

    def _status(self, state: str, latency: float | None, detail: str = "") -> None:
        if self.on_status is not None:
            self.on_status(state, latency, detail)


class Slot:
    """A single in-flight slot for a user-initiated call."""

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, coro: Awaitable[None]) -> bool:
        """Start coro if the slot is free. Return False if it is busy."""
        if self.busy:
            if asyncio.iscoroutine(coro):
                coro.close()
            return False
        self.task = asyncio.get_running_loop().create_task(coro)
        return True
