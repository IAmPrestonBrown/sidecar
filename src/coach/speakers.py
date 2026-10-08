"""Label live transcript segments as the interviewer or the interviewee.

Each segment is labeled by its own loudness against two loudness clusters
learned during the call. Until the clusters exist, diarization speaker ids
are mapped to labels instead.
"""

import array
import math
import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from coach.transcript import Segment

MIN_WORDS_TO_MAP = 10
FALLBACK_SPEECH_S = 60.0
LOCK_SPEECH_S = 60.0
MIN_CLUSTER_WORDS = 20
MIN_SEPARATION_DB = 6.0
CLUSTER_HISTORY = 2000
CLUSTER_ITERATIONS = 10
LOUD = "loud"
QUIET = "quiet"
_EPS = 1e-6


def word_db(block_rms: list[float]) -> float | None:
    """Loudness of one word in dB from the RMS of the blocks it covers."""
    values = [v for v in block_rms if v > 0]
    if not values:
        return None
    return 10 * math.log10(sum(v * v for v in values) / len(values) + 1e-12)


class LoudnessClusters:
    """Two-cluster split of recent word loudness: near-mic voice and phone voice."""

    def __init__(self) -> None:
        self._db: deque[float] = deque(maxlen=CLUSTER_HISTORY)

    def add(self, values: list[float]) -> None:
        self._db.extend(values)

    def midpoint(self) -> float | None:
        """dB threshold between the clusters, or None if they are not separable."""
        if len(self._db) < MIN_CLUSTER_WORDS:
            return None
        h = np.fromiter(self._db, dtype=np.float64)
        lo, hi = float(np.percentile(h, 25)), float(np.percentile(h, 75))
        for _ in range(CLUSTER_ITERATIONS):
            mid = (lo + hi) / 2
            above, below = h[h > mid], h[h <= mid]
            if above.size == 0 or below.size == 0:
                return None
            hi, lo = float(above.mean()), float(below.mean())
        if hi - lo < MIN_SEPARATION_DB:
            return None
        return (lo + hi) / 2


@dataclass
class SpeakerStats:
    words: int = 0
    speech_s: float = 0.0
    rms: array.array = field(default_factory=lambda: array.array("f"))

    def median_rms(self) -> float | None:
        if not self.rms:
            return None
        return statistics.median(self.rms)


class SpeakerMapper:
    """Loudness-based speaker labeling.

    The interviewer sits next to the laptop mic, so their speech is louder than the
    interviewee coming through the phone speaker. loud_label is the label of
    the loud side and flips on a manual swap.
    """

    def __init__(self, interviewer_label: str, them_label: str) -> None:
        self.interviewer = interviewer_label
        self.them = them_label
        self.stats: dict[tuple[int, int], SpeakerStats] = {}
        self.mapping: dict[tuple[int, int], str] = {}
        self.refs: dict[str, float] = {}
        self.locked = False
        self.history: list[dict] = []
        self._anchors: dict[str, tuple[int, int]] = {}
        self._speech_total = 0.0
        self.clusters = LoudnessClusters()
        self.loud_label = interviewer_label
        self.midpoint: float | None = None

    @property
    def mapped(self) -> bool:
        return bool(self.mapping) or self.midpoint is not None

    def label_for(self, seg: Segment) -> str:
        if seg.side == LOUD:
            return self.loud_label
        if seg.side == QUIET:
            return self.other(self.loud_label)
        return self.label_for_key(seg.key)

    def label_for_key(self, key: tuple[int, int]) -> str:
        label = self.mapping.get(key)
        if label is not None:
            return label
        return f"S{key[1]}"

    def other(self, label: str) -> str:
        return self.them if label == self.interviewer else self.interviewer

    def observe(self, seg: Segment, word_rms: list[list[float]]) -> bool:
        """Set seg.side from its loudness and record its words.

        word_rms holds the block RMS values covering each word. The segment is
        classified against clusters built from earlier words only. Return True
        if the id mapping changed or the loudness clusters became ready.
        """
        dbs = [db for v in word_rms if (db := word_db(v)) is not None]
        if self.midpoint is not None and dbs:
            seg.side = LOUD if statistics.median(dbs) > self.midpoint else QUIET
        was_ready = self.midpoint is not None
        self.clusters.add(dbs)
        self.midpoint = self.clusters.midpoint()
        st = self.stats.setdefault(seg.key, SpeakerStats())
        st.words += len(seg.words)
        dur = sum(b - a for a, b in seg.words)
        st.speech_s += dur
        st.rms.extend(v for values in word_rms for v in values if v > 0)
        self._speech_total += dur
        before = dict(self.mapping)
        self._update()
        changed = before != self.mapping
        if changed:
            self._record("auto")
        if self.midpoint is not None and not was_ready:
            self._record("loudness_ready")
            changed = True
        return changed

    def swap(self) -> None:
        """Flip the label of every mapped id."""
        self.mapping = {k: self.other(v) for k, v in self.mapping.items()}
        self.refs = {self.other(k): v for k, v in self.refs.items()}
        self._anchors = {self.other(k): v for k, v in self._anchors.items()}
        self.loud_label = self.other(self.loud_label)
        self._record("swap")

    def label_speech(self) -> dict[str, float]:
        out = {self.interviewer: 0.0, self.them: 0.0}
        for key, label in self.mapping.items():
            out[label] = out.get(label, 0.0) + self.stats[key].speech_s
        return out

    def _record(self, kind: str) -> None:
        self.history.append(
            {
                "t": time.time(),
                "kind": kind,
                "locked": self.locked,
                "loud_label": self.loud_label,
                "mapping": {f"{c}:{s}": v for (c, s), v in sorted(self.mapping.items())},
            }
        )

    def _update(self) -> None:
        if not self.mapping or (not self.locked and len(self._anchors) < 2):
            self._initial_map()
        if not self.mapping:
            return
        if not self.locked:
            self._refresh_refs()
        for key, st in self.stats.items():
            if self.locked and key in self.mapping:
                continue
            if key in self._anchors.values():
                continue
            median = st.median_rms()
            if median is None:
                continue
            label = self._nearest(median)
            self.mapping[key] = label
            if label not in self.refs and st.words >= MIN_WORDS_TO_MAP:
                self._anchors[label] = key
                self.refs[label] = median
        speech = self.label_speech()
        if not self.locked and all(v >= LOCK_SPEECH_S for v in speech.values()):
            self.locked = True
            self._record("lock")

    def _initial_map(self) -> None:
        ready = [
            (k, st.median_rms())
            for k, st in self.stats.items()
            if st.words >= MIN_WORDS_TO_MAP and st.median_rms() is not None
        ]
        if len(ready) >= 2:
            ready.sort(key=lambda kv: kv[1], reverse=True)
            (loud, loud_rms), (quiet, quiet_rms) = ready[0], ready[1]
            self._anchors = {self.interviewer: loud, self.them: quiet}
            self.mapping = {loud: self.interviewer, quiet: self.them}
            self.refs = {self.interviewer: loud_rms, self.them: quiet_rms}
            return
        if not self.mapping and self._speech_total >= FALLBACK_SPEECH_S:
            cands = [(k, st.median_rms()) for k, st in self.stats.items()]
            cands = [(k, m) for k, m in cands if m is not None]
            if not cands:
                return
            loud, loud_rms = max(cands, key=lambda kv: kv[1])
            self._anchors = {self.interviewer: loud}
            self.mapping = {loud: self.interviewer}
            self.refs = {self.interviewer: loud_rms}

    def _refresh_refs(self) -> None:
        for label, key in self._anchors.items():
            if self.mapping.get(key) != label:
                continue
            median = self.stats[key].median_rms()
            if median is not None:
                self.refs[label] = median

    def _nearest(self, rms: float) -> str:
        if len(self.refs) < 2:
            known = next(iter(self.refs))
            missing = self.other(known)
            if rms < self.refs[known] * 0.7:
                return missing
            return known
        log_rms = math.log(rms + _EPS)
        return min(self.refs, key=lambda lab: abs(math.log(self.refs[lab] + _EPS) - log_rms))


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def map_batch_speakers(
    batch: list[Segment],
    live: list[Segment],
    rms_window: Callable[[float, float], list[float]],
    interviewer: str,
    them: str,
) -> dict[int, str]:
    """Map batch speaker ids to labels by time overlap with live labels.

    Speakers with no overlap get the label whose live median loudness is
    closest. With no live labels at all, the loudest speaker is the interviewer.
    """
    live_labeled = [s for s in live if s.label in (interviewer, them)]
    votes: dict[int, dict[str, float]] = {}
    for seg in batch:
        tally = votes.setdefault(seg.speaker_id, {interviewer: 0.0, them: 0.0})
        for ls in live_labeled:
            if ls.end < seg.start or ls.start > seg.end:
                continue
            tally[ls.label] += _overlap(seg.start, seg.end, ls.start, ls.end)

    def median_rms(segs: list[Segment]) -> float | None:
        values: list[float] = []
        for s in segs:
            for a, b in s.words:
                values.extend(rms_window(a, b))
        values = [v for v in values if v > 0]
        return statistics.median(values) if values else None

    refs = {
        lab: m
        for lab in (interviewer, them)
        if (m := median_rms([s for s in live_labeled if s.label == lab])) is not None
    }
    out: dict[int, str] = {}
    uncovered: dict[int, float] = {}
    for spk, tally in votes.items():
        if max(tally.values()) > 0:
            out[spk] = max(tally, key=lambda lab: tally[lab])
            continue
        m = median_rms([s for s in batch if s.speaker_id == spk])
        uncovered[spk] = m if m is not None else 0.0
    if uncovered and len(refs) == 2:
        for spk, m in uncovered.items():
            log_m = math.log(m + _EPS)
            out[spk] = min(refs, key=lambda lab: abs(math.log(refs[lab] + _EPS) - log_m))
    elif uncovered:
        loudest = max(uncovered, key=lambda k: uncovered[k])
        for spk in uncovered:
            out[spk] = interviewer if spk == loudest else them
    return out
