from coach.transcript import Segment, TranscriptStore, gap_segment, load_jsonl, render_turns


def seg(start: float, end: float, label: str, text: str, spk: int = 0) -> Segment:
    return Segment(start, end, 0, spk, label, text, [(start, end)])


def test_render_merges_same_speaker() -> None:
    out = render_turns([seg(0, 1, "A", "hi"), seg(1, 2, "A", "there"), seg(65, 66, "B", "yo")])
    assert out == "[00:00] A: hi there\n[01:05] B: yo"


def test_closed_chunks_stay_byte_identical(tmp_path) -> None:
    store = TranscriptStore(chunk_seconds=30, jsonl_path=tmp_path / "t.jsonl")
    t = 0.0
    snapshots: list[list[str]] = []
    for i in range(40):
        label = "INTERVIEWER" if i % 3 == 0 else "GUEST"
        store.append(seg(t, t + 4, label, f"words {i}", spk=0 if label == "INTERVIEWER" else 1))
        t += 5
        closed, _ = store.chunks()
        snapshots.append(closed)
    final = snapshots[-1]
    assert len(final) >= 4
    for snap in snapshots:
        assert snap == final[: len(snap)]
    assert len(load_jsonl(tmp_path / "t.jsonl")) == 40


def test_chunk_closes_at_turn_boundary_only() -> None:
    store = TranscriptStore(chunk_seconds=10)
    for i in range(6):
        store.append(seg(i * 5, i * 5 + 4, "A", f"a{i}"))
    closed, open_chunk = store.chunks()
    assert closed == []
    store.append(seg(30, 31, "B", "b"))
    closed, open_chunk = store.chunks()
    assert len(closed) == 1
    assert open_chunk.startswith("[00:30] B:")


def test_only_mapping_change_rewrites_closed_chunks() -> None:
    store = TranscriptStore(chunk_seconds=10)
    for i in range(10):
        label = "S0" if i % 2 else "S1"
        store.append(Segment(i * 5, i * 5 + 4, 0, i % 2, label, f"w{i}", [(i * 5, i * 5 + 4)]))
    before, _ = store.chunks()
    assert store.relabel(lambda s: "INTERVIEWER" if s.speaker_id == 1 else "GUEST")
    after, _ = store.chunks()
    assert before != after
    assert "INTERVIEWER" in after[0]
    assert not store.relabel(lambda s: "INTERVIEWER" if s.speaker_id == 1 else "GUEST")
    assert store.chunks()[0] == after


def test_gap_marker_and_talk_share() -> None:
    store = TranscriptStore(chunk_seconds=120)
    store.append(seg(0, 10, "INTERVIEWER", "a"))
    store.append(gap_segment(10, 40, 0))
    store.append(seg(40, 70, "GUEST", "b"))
    assert "[live transcription gap 00:10-00:40]" in store.chunks()[1]
    assert abs(store.talk_share("INTERVIEWER") - 0.25) < 1e-9
    assert store.talk_share("INTERVIEWER", since_s=40) == 0.0
