import wave

import numpy as np

from coach.audio import pcm_to_wav
from coach.schemas import CoachUpdate, MarkAnalysis, validate_output


def card(**over: object) -> dict:
    base = {
        "kind": "DIG_HERE",
        "headline": "Why the notebook",
        "ask": "Why do you write that in the notebook?",
        "why": "Tests H3 vs H5",
        "tags": ["H3", "H5"],
        "quote": "I keep it in my notebook",
    }
    return base | over


def test_valid_output_passes() -> None:
    out = validate_output("live", {"intervene": True, "cards": [card()], "evidence": []})
    assert isinstance(out, CoachUpdate)
    assert out.cards[0].kind == "DIG_HERE"


def test_over_length_fields_are_truncated() -> None:
    long_ask = " ".join(f"w{i}" for i in range(40))
    data = {
        "intervene": True,
        "cards": [card(ask=long_ask, headline="one two three four five six seven eight nine ten")]
        * 4,
        "evidence": [],
    }
    out = validate_output("live", data)
    assert out is not None
    assert len(out.cards) == 2
    assert out.cards[0].ask.split()[:20] == long_ask.split()[:20]
    assert out.cards[0].ask.endswith(" ...")
    assert len(out.cards[0].headline.split()) == 9


def test_malformed_output_is_discarded() -> None:
    assert validate_output("live", {"intervene": "maybe", "cards": "x"}) is None
    assert validate_output("live", {"intervene": True, "cards": [card(kind="PITCH")]}) is None
    assert validate_output("mark", {"headline": "x"}) is None


def test_mark_analysis_valid() -> None:
    out = validate_output(
        "mark",
        {
            "headline": "Stopped tracking leftovers",
            "claim": "Stopped counting leftovers after the first year",
            "evidence_type": "PAST_INCIDENT",
            "hypotheses": [{"id": "H5", "direction": "CONTRADICTS"}],
            "contradiction": None,
            "unknown": "How leftovers are judged now",
            "ask": "What were you using before, and what changed?",
            "why": "Capability versus adoption",
        },
    )
    assert isinstance(out, MarkAnalysis)


def test_pcm_to_wav_with_truncated_final_block(tmp_path) -> None:
    pcm = tmp_path / "audio.pcm"
    samples = (np.arange(16000 * 2) % 2000 - 1000).astype(np.int16)
    pcm.write_bytes(samples.tobytes() + b"\x01")
    wav = tmp_path / "audio.wav"
    n = pcm_to_wav(pcm, wav, 16000)
    assert n == len(samples)
    with wave.open(str(wav), "rb") as wf:
        assert wf.getnframes() == len(samples)
        assert wf.getframerate() == 16000
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    assert np.array_equal(data, samples)


def write_wav(path, samples: np.ndarray, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_file_source_streams_all_samples(tmp_path) -> None:
    import queue

    from coach.audio import FileSource

    samples = (np.arange(16000 * 3 + 123) % 3000 - 1500).astype(np.int16)
    path = tmp_path / "in.wav"
    write_wav(path, samples)
    q: queue.Queue = queue.Queue()
    src = FileSource(path, 16000, 1600, speed=1000.0)
    src.start(q)
    assert src.finished.wait(5)
    got = b"".join(q.get_nowait() for _ in range(q.qsize()))
    assert got == samples.tobytes()


def test_wav_rms_window_reads_in_chunks(tmp_path) -> None:
    from coach.session import wav_rms_window

    loud = np.full(16000, 16384, dtype=np.int16)
    quiet = np.full(16000, 1638, dtype=np.int16)
    path = tmp_path / "a.wav"
    write_wav(path, np.concatenate([loud, quiet]))
    window = wav_rms_window(path, 16000, 1600)
    assert abs(window(0.0, 0.5)[0] - 0.5) < 1e-3
    assert abs(window(1.2, 1.5)[0] - 0.05) < 1e-3
