import json

from coach.session import load_live_segments, update_session_json
from coach.transcript import Segment, gap_segment


def write_live(tmp_path) -> None:
    segs = [
        Segment(0, 1, 0, 0, "S0", "hello", [(0, 1)]),
        Segment(1, 2, 0, 1, "S1", "hi", [(1, 2)]),
        gap_segment(2, 5, 0),
    ]
    with open(tmp_path / "transcript_live.jsonl", "w") as fh:
        for s in segs:
            fh.write(json.dumps(s.to_json()) + "\n")


def mapping_event(mapping: dict) -> str:
    return json.dumps({"kind": "mapping", "history": [{"kind": "x", "mapping": mapping}]})


def test_crash_recovery_uses_last_mapping_event(tmp_path) -> None:
    write_live(tmp_path)
    events = [
        mapping_event({"0:0": "INTERVIEWER", "0:1": "GUEST"}),
        mapping_event({"0:0": "GUEST", "0:1": "INTERVIEWER"}),
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(events) + "\n")
    segs = load_live_segments(tmp_path)
    assert [s.label for s in segs] == ["GUEST", "INTERVIEWER", "GAP"]


def test_session_json_final_mapping_wins(tmp_path) -> None:
    write_live(tmp_path)
    (tmp_path / "events.jsonl").write_text(mapping_event({"0:0": "GUEST"}) + "\n")
    update_session_json(tmp_path, final_mapping={"0:0": "INTERVIEWER", "0:1": "GUEST"})
    segs = load_live_segments(tmp_path)
    assert [s.label for s in segs[:2]] == ["INTERVIEWER", "GUEST"]


def test_no_mapping_keeps_stored_labels(tmp_path) -> None:
    write_live(tmp_path)
    assert [s.label for s in load_live_segments(tmp_path)][:2] == ["S0", "S1"]


def test_loudness_sides_follow_final_loud_label(tmp_path) -> None:
    segs = [
        Segment(0, 1, 0, 0, "INTERVIEWER", "loud words", [(0, 1)], side="loud"),
        Segment(1, 2, 0, 0, "GUEST", "quiet words", [(1, 2)], side="quiet"),
    ]
    with open(tmp_path / "transcript_live.jsonl", "w") as fh:
        for s in segs:
            fh.write(json.dumps(s.to_json()) + "\n")
    update_session_json(
        tmp_path,
        interviewee="Dana",
        labels={"interviewer": "INTERVIEWER", "interviewee": "GUEST"},
        final_mapping={"0:0": "INTERVIEWER"},
        final_loud_label="GUEST",
    )
    assert [s.label for s in load_live_segments(tmp_path)] == ["GUEST", "INTERVIEWER"]


def test_crash_recovery_reads_loud_label_from_events(tmp_path) -> None:
    seg = Segment(0, 1, 0, 0, "INTERVIEWER", "x", [(0, 1)], side="loud")
    (tmp_path / "transcript_live.jsonl").write_text(json.dumps(seg.to_json()) + "\n")
    event = {"kind": "mapping", "history": [{"mapping": {}, "loud_label": "INTERVIEWEE"}]}
    (tmp_path / "events.jsonl").write_text(json.dumps(event) + "\n")
    assert load_live_segments(tmp_path)[0].label == "INTERVIEWEE"
