import json
from pathlib import Path

from coach.config import DeepgramConfig
from coach.stt_live import LiveSTT, live_query, words_to_segments

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def make_stt(collected: dict) -> LiveSTT:
    return LiveSTT(
        DeepgramConfig(),
        "key",
        16000,
        [],
        on_segments=lambda segs: collected.setdefault("segs", []).extend(segs),
        on_interim=lambda text: collected.setdefault("interim", []).append(text),
        on_utterance_end=lambda: collected.__setitem__("ue", collected.get("ue", 0) + 1),
        on_status=lambda s, d: None,
        on_gap=lambda a, b, c: collected.setdefault("gaps", []).append((a, b, c)),
    )


def test_multi_speaker_message_splits_by_speaker() -> None:
    words = load("dg_final_multi.json")["channel"]["alternatives"][0]["words"]
    segs = words_to_segments(words, offset_s=0.0, connection=0)
    assert [s.speaker_id for s in segs] == [0, 1]
    assert segs[0].text == "So how do you track it?"
    assert segs[1].text == "I use a spreadsheet."
    assert segs[0].start == 10.0
    assert segs[0].end == 11.0
    assert len(segs[1].words) == 4


def test_offsets_across_two_connections() -> None:
    first = words_to_segments(
        load("dg_final_multi.json")["channel"]["alternatives"][0]["words"], 0.0, 0
    )
    second = words_to_segments(
        load("dg_final_conn2.json")["channel"]["alternatives"][0]["words"], 120.0, 1
    )
    assert first[-1].connection == 0
    assert second[0].connection == 1
    assert second[0].start == 121.0
    assert second[0].words[-1] == (121.8, 122.1)
    assert second[0].key == (1, 0)


def test_handle_routes_message_types() -> None:
    got: dict = {}
    stt = make_stt(got)
    stt.connection = 0
    interim = load("dg_final_multi.json") | {"is_final": False}
    stt._handle(interim, 0.0)
    stt._handle(load("dg_final_multi.json"), 5.0)
    stt._handle(load("dg_utterance_end.json"), 5.0)
    stt._handle({"type": "Metadata", "request_id": "x"}, 0.0)
    assert got["interim"][0].startswith("So how")
    assert got["interim"][-1] == ""
    assert got["segs"][0].start == 15.0
    assert got["ue"] == 1


def test_live_query_params() -> None:
    q = live_query(DeepgramConfig(keyterms=["Hearth & Crumb", "sourdough"]), 16000, ["sourdough"])
    assert "model=nova-3" in q
    assert "utterance_end_ms=1500" in q
    assert "interim_results=true" in q
    assert "mip_opt_out=true" in q
    assert "keyterm=sourdough" in q
    assert "endpointing=300" in q
