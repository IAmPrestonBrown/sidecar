import asyncio

from coach.scheduler import ME_TURN_END, THEM_TURN_END, TIMER, LiveScheduler, Slot


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make(calls: list[str], clock: Clock, delay: float = 0.0, timeout: float = 15.0):
    statuses: list[str] = []

    async def run(reason: str) -> None:
        calls.append(reason)
        if delay:
            await asyncio.sleep(delay)

    sched = LiveScheduler(
        run,
        min_interval_s=6,
        timer_interval_s=25,
        them_trigger_words=12,
        timeout_s=timeout,
        clock=clock,
        on_status=lambda s, lat, detail: statuses.append(s),
    )
    sched.enabled = True
    return sched, statuses


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_them_turn_end_needs_words() -> None:
    calls: list[str] = []
    clock = Clock()
    s, _ = make(calls, clock)
    s.add_words(5)
    s.on_utterance_end(True, "")
    await settle()
    assert calls == []
    s.add_words(8)
    s.on_utterance_end(True, "")
    await settle()
    assert calls == [THEM_TURN_END]


async def test_me_turn_end_question_or_long() -> None:
    calls: list[str] = []
    clock = Clock()
    s, _ = make(calls, clock)
    s.add_words(3)
    s.on_utterance_end(False, "ok sure")
    await settle()
    assert calls == []
    s.on_utterance_end(False, "Do you use a spreadsheet?")
    await settle()
    assert calls == [ME_TURN_END]


async def test_timer_trigger() -> None:
    calls: list[str] = []
    clock = Clock()
    s, _ = make(calls, clock)
    s.add_words(25)
    s.tick()
    await settle()
    assert calls == [TIMER]
    s.add_words(25)
    clock.t += 10
    s.tick()
    await settle()
    assert calls == [TIMER]
    clock.t += 16
    s.tick()
    await settle()
    assert calls == [TIMER, TIMER]


async def test_min_interval_and_coalescing() -> None:
    calls: list[str] = []
    clock = Clock()
    s, _ = make(calls, clock)
    s.trigger(THEM_TURN_END)
    await settle()
    clock.t += 2
    s.trigger(THEM_TURN_END)
    s.trigger(ME_TURN_END)
    s.tick()
    await settle()
    assert calls == [THEM_TURN_END]
    clock.t += 5
    s.tick()
    await settle()
    assert calls == [THEM_TURN_END, ME_TURN_END]
    s.tick()
    await settle()
    assert len(calls) == 2


async def test_single_call_in_flight() -> None:
    calls: list[str] = []
    clock = Clock()
    s, _ = make(calls, clock, delay=0.05)
    s.trigger(THEM_TURN_END)
    await settle()
    clock.t += 10
    s.trigger(ME_TURN_END)
    s.tick()
    await settle()
    assert calls == [THEM_TURN_END]
    assert s.pending == ME_TURN_END
    await s.task
    s.tick()
    await settle()
    assert calls == [THEM_TURN_END, ME_TURN_END]


async def test_timeout_sets_slow_and_frees_slot() -> None:
    calls: list[str] = []
    clock = Clock()
    s, statuses = make(calls, clock, delay=1.0, timeout=0.05)
    s.trigger(THEM_TURN_END)
    await s.task
    assert statuses == ["slow"]
    assert not s.in_flight


async def test_disabled_until_mapping() -> None:
    calls: list[str] = []
    clock = Clock()
    s, _ = make(calls, clock)
    s.enabled = False
    s.add_words(50)
    s.trigger(THEM_TURN_END)
    s.tick()
    await settle()
    assert calls == []


async def test_slot_ignores_second_press() -> None:
    slot = Slot()
    done = asyncio.Event()

    async def work() -> None:
        await done.wait()

    assert slot.start(work())
    assert not slot.start(work())
    done.set()
    await slot.task
    assert slot.start(work())
    done.set()
    await slot.task
