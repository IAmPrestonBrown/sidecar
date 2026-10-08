import asyncio
import json

from websockets.asyncio.server import serve

from coach.config import DeepgramConfig
from coach.stt_live import LiveSTT

SR = 16000
BLOCK = 1600


def result(start: float, end: float, speaker: int, word: str) -> str:
    w = {"word": word, "start": start, "end": end, "speaker": speaker, "punctuated_word": word}
    alt = {"transcript": word, "words": [w]}
    return json.dumps({"type": "Results", "is_final": True, "channel": {"alternatives": [alt]}})


async def run_with_drop(queue_blocks: int) -> tuple[int, list, list, list]:
    connections = 0

    async def handler(ws) -> None:
        nonlocal connections
        connections += 1
        n = connections
        received = 0
        async for msg in ws:
            if isinstance(msg, bytes):
                received += len(msg) // 2
                if received >= SR:
                    await ws.send(result(0.5, 0.9, 0, f"conn{n}"))
                    if n == 1:
                        await ws.close()
                        return
            elif json.loads(msg).get("type") == "CloseStream":
                await ws.close()
                return

    segs = []
    gaps = []
    statuses = []
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        stt = LiveSTT(
            DeepgramConfig(),
            "key",
            SR,
            [],
            on_segments=segs.extend,
            on_interim=lambda t: None,
            on_utterance_end=lambda: None,
            on_status=lambda s, d: statuses.append(s),
            on_gap=lambda a, b, c: gaps.append((a, b, c)),
            url=f"ws://127.0.0.1:{port}",
        )
        stt.queue = asyncio.Queue(maxsize=queue_blocks)
        task = asyncio.create_task(stt.run())
        sample = 0
        for _ in range(80):
            stt.put_block(sample, bytes(BLOCK * 2))
            sample += BLOCK
            await asyncio.sleep(0.03)
        await stt.close()
        await asyncio.wait_for(task, 5)

    return connections, segs, gaps, statuses


async def test_short_outage_loses_nothing() -> None:
    connections, segs, gaps, statuses = await run_with_drop(50)
    assert connections >= 2
    assert "reconnecting" in statuses
    assert [s.connection for s in segs[:2]] == [0, 1]
    assert abs(segs[0].start - 0.5) < 1e-6
    assert gaps == []


async def test_long_outage_inserts_gap_and_offsets() -> None:
    connections, segs, gaps, _ = await run_with_drop(3)
    assert connections >= 2
    assert abs(segs[0].start - 0.5) < 1e-6
    assert segs[1].connection == 1
    assert gaps
    assert gaps[0][2] == 1
    gap_start, gap_end, _ = gaps[0]
    assert gap_end - gap_start >= 1.0
    assert segs[1].start >= gap_end
