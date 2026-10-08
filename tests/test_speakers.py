from coach.speakers import LOUD, QUIET, LoudnessClusters, SpeakerMapper, map_batch_speakers
from coach.transcript import Segment


def seg(conn: int, spk: int, start: float, n_words: int, word_s: float = 0.5) -> Segment:
    words = [(start + i * word_s, start + (i + 1) * word_s) for i in range(n_words)]
    return Segment(start, words[-1][1], conn, spk, "", "w " * n_words, words)


def rms(level: float, n_words: int) -> list[list[float]]:
    return [[level]] * n_words


def observe(m: SpeakerMapper, s: Segment, level: float) -> bool:
    return m.observe(s, rms(level, len(s.words)))


def test_louder_speaker_becomes_interviewer() -> None:
    m = SpeakerMapper("INTERVIEWER", "GUEST")
    assert not observe(m, seg(0, 0, 0, 12), 0.02)
    assert m.label_for_key((0, 0)) == "S0"
    assert observe(m, seg(0, 1, 10, 12), 0.2)
    assert m.label_for_key((0, 1)) == "INTERVIEWER"
    assert m.label_for_key((0, 0)) == "GUEST"
    assert m.refs["INTERVIEWER"] > m.refs["GUEST"]


def test_new_id_gets_nearest_reference() -> None:
    m = SpeakerMapper("INTERVIEWER", "GUEST")
    observe(m, seg(0, 0, 0, 12), 0.02)
    observe(m, seg(0, 1, 10, 12), 0.2)
    observe(m, seg(1, 0, 30, 3), 0.18)
    observe(m, seg(1, 1, 40, 3), 0.025)
    assert m.label_for_key((1, 0)) == "INTERVIEWER"
    assert m.label_for_key((1, 1)) == "GUEST"


def test_fallback_after_sixty_seconds_single_speaker() -> None:
    m = SpeakerMapper("INTERVIEWER", "GUEST")
    observe(m, seg(0, 0, 0, 130), 0.1)
    assert m.mapped
    assert m.label_for_key((0, 0)) == "INTERVIEWER"


def test_lock_and_swap() -> None:
    m = SpeakerMapper("INTERVIEWER", "GUEST")
    observe(m, seg(0, 0, 0, 130), 0.02)
    observe(m, seg(0, 1, 70, 130), 0.2)
    assert m.locked
    observe(m, seg(0, 0, 140, 20), 0.5)
    assert m.label_for_key((0, 0)) == "GUEST"
    m.swap()
    assert m.label_for_key((0, 0)) == "INTERVIEWER"
    assert m.label_for_key((0, 1)) == "GUEST"
    assert m.history[-1]["kind"] == "swap"


def test_clusters_need_words_and_separation() -> None:
    c = LoudnessClusters()
    c.add([-24.0] * 10)
    assert c.midpoint() is None
    c.add([-25.0] * 10)
    assert c.midpoint() is None
    c.add([-38.0] * 20)
    mid = c.midpoint()
    assert mid is not None
    assert -35 < mid < -27


def test_fragments_labeled_by_own_loudness_despite_diarizer_id() -> None:
    m = SpeakerMapper("INTERVIEWER", "GUEST")
    observe(m, seg(0, 0, 0, 12), 0.06)
    observe(m, seg(0, 1, 10, 12), 0.012)
    assert m.midpoint is not None
    loud_wrong_id = seg(0, 1, 30, 1)
    quiet_wrong_id = seg(0, 0, 31, 1)
    observe(m, loud_wrong_id, 0.07)
    observe(m, quiet_wrong_id, 0.01)
    assert loud_wrong_id.side == LOUD
    assert quiet_wrong_id.side == QUIET
    assert m.label_for(loud_wrong_id) == "INTERVIEWER"
    assert m.label_for(quiet_wrong_id) == "GUEST"
    m.swap()
    assert m.label_for(loud_wrong_id) == "GUEST"
    assert m.history[-1]["loud_label"] == "GUEST"


def test_first_fragments_fall_back_to_id_mapping() -> None:
    m = SpeakerMapper("INTERVIEWER", "GUEST")
    first = seg(0, 0, 0, 5)
    observe(m, first, 0.06)
    assert first.side is None
    assert m.label_for(first) == "S0"


def test_batch_mapping_by_overlap_and_loudness() -> None:
    live = [seg(0, 0, 0, 10), seg(0, 1, 6, 10)]
    live[0].label, live[1].label = "INTERVIEWER", "GUEST"
    batch = [seg(0, 5, 0, 10), seg(0, 7, 6, 10), seg(0, 9, 100, 4)]
    levels = {0: 0.2, 6: 0.02, 100: 0.03}

    def window(a: float, b: float) -> list[float]:
        key = max(k for k in levels if k <= a)
        return [levels[key]]

    labels = map_batch_speakers(batch, live, window, "INTERVIEWER", "GUEST")
    assert labels[5] == "INTERVIEWER"
    assert labels[7] == "GUEST"
    assert labels[9] == "GUEST"
