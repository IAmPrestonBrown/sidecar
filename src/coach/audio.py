"""Audio capture, disk writing, level metering, and PCM to WAV conversion."""

import array
import logging
import os
import queue
import threading
import time
import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

BlockSink = Callable[[int, bytes], None]
LevelSink = Callable[[float, float], None]

_STOP = object()


def find_input_device(name: str) -> int | None:
    """Return the index of the first input device whose name contains name.

    An empty name selects the system default and returns None.
    """
    if not name:
        return None
    import sounddevice as sd

    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name.lower() in dev["name"].lower():
            return idx
    raise ValueError(f"No input device matches {name!r}")


def block_levels(block: bytes) -> tuple[float, float]:
    """Return (rms, peak) of an int16 block, both scaled to 0..1."""
    samples = np.frombuffer(block, dtype=np.int16)
    if samples.size == 0:
        return 0.0, 0.0
    floats = samples.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(floats * floats)))
    peak = float(np.max(np.abs(floats)))
    return rms, peak


class RmsLog:
    """Per-block RMS values indexed by block start sample.

    The writer thread appends. Other threads only read. Blocks have a fixed size.
    """

    def __init__(self, block_frames: int, sample_rate: int) -> None:
        self.block_frames = block_frames
        self.sample_rate = sample_rate
        self._values = array.array("f")

    def append(self, rms: float) -> None:
        self._values.append(rms)

    def __len__(self) -> int:
        return len(self._values)

    def window(self, start_s: float, end_s: float) -> list[float]:
        """Return RMS values for blocks overlapping [start_s, end_s]."""
        per_block = self.block_frames / self.sample_rate
        first = max(0, int(start_s / per_block))
        last = min(len(self._values), int(end_s / per_block) + 1)
        return list(self._values[first:last])


class MicSource:
    """Captures the microphone into a thread-safe queue."""

    def __init__(self, device: str, sample_rate: int, block_frames: int) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.overflow = False
        self._stream = None

    def start(self, out: queue.Queue[object]) -> None:
        import sounddevice as sd

        def callback(indata: np.ndarray, frames: int, time_info: object, status: object) -> None:
            if status and getattr(status, "input_overflow", False):
                self.overflow = True
            out.put_nowait(bytes(indata))

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.block_frames,
            device=find_input_device(self.device),
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def read_wav_mono16k(path: Path, sample_rate: int) -> np.ndarray:
    """Read a PCM WAV file and return mono int16 samples at sample_rate."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width}")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != sample_rate:
        n_out = int(len(data) * sample_rate / rate)
        x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        data = np.interp(x_new, x_old, data)
    return (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)


class FileSource:
    """Feeds a WAV file into the queue at real-time pace times speed."""

    def __init__(self, path: Path, sample_rate: int, block_frames: int, speed: float) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.speed = speed
        self.overflow = False
        self.finished = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, out: queue.Queue[object]) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(out,), name="file-source", daemon=True
        )
        self._thread.start()

    def _blocks(self) -> Iterator[bytes]:
        """Yield int16 blocks. Native 16-bit mono files stream from disk."""
        with wave.open(str(self.path), "rb") as wf:
            native = (
                wf.getnchannels() == 1
                and wf.getsampwidth() == 2
                and wf.getframerate() == self.sample_rate
            )
            if native:
                while chunk := wf.readframes(self.block_frames):
                    yield chunk
                return
        samples = read_wav_mono16k(self.path, self.sample_rate)
        for i in range(0, len(samples), self.block_frames):
            yield samples[i : i + self.block_frames].tobytes()

    def _run(self, out: queue.Queue[object]) -> None:
        interval = self.block_frames / self.sample_rate / self.speed
        next_t = time.monotonic()
        for block in self._blocks():
            if self._stop.is_set():
                break
            out.put_nowait(block)
            next_t += interval
            delay = next_t - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
        self.finished.set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


class Recorder:
    """Owns the capture queue and the writer thread.

    The writer appends every block to audio.pcm. Disk writes never drop data.
    Each block is also offered to the STT sink and the level sink. Those sinks
    must not block.
    """

    def __init__(
        self,
        source: MicSource | FileSource,
        pcm_path: Path,
        sample_rate: int,
        block_frames: int,
    ) -> None:
        self.source = source
        self.pcm_path = pcm_path
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.rms_log = RmsLog(block_frames, sample_rate)
        self.samples_written = 0
        self.stt_sink: BlockSink | None = None
        self.level_sink: LevelSink | None = None
        self.error: str | None = None
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def seconds(self) -> float:
        return self.samples_written / self.sample_rate

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._thread = threading.Thread(target=self._write_loop, name="audio-writer", daemon=False)
        self._running = True
        self._thread.start()
        self.source.start(self._queue)

    def stop(self) -> None:
        """Stop capture, drain the queue, flush, fsync, and close the file."""
        if not self._running:
            return
        self.source.stop()
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join()
        self._running = False

    def _write_loop(self) -> None:
        last_flush = last_sync = time.monotonic()
        with open(self.pcm_path, "ab") as fh:
            while True:
                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    item = None
                if item is _STOP:
                    break
                if isinstance(item, bytes):
                    fh.write(item)
                    start = self.samples_written
                    self.samples_written += len(item) // 2
                    self._offer(start, item)
                now = time.monotonic()
                if now - last_flush >= 1.0:
                    fh.flush()
                    last_flush = now
                if now - last_sync >= 5.0:
                    os.fsync(fh.fileno())
                    last_sync = now
            fh.flush()
            os.fsync(fh.fileno())

    def _offer(self, start: int, block: bytes) -> None:
        rms, peak = block_levels(block)
        self.rms_log.append(rms)
        for sink, args in ((self.stt_sink, (start, block)), (self.level_sink, (rms, peak))):
            if sink is None:
                continue
            try:
                sink(*args)
            except Exception:
                log.exception("Audio sink failed")


def pcm_to_wav(pcm_path: Path, wav_path: Path, sample_rate: int) -> int:
    """Write wav_path from raw int16 mono PCM and return the sample count.

    A trailing partial sample is dropped. The WAV is read back to verify the
    sample count before returning.
    """
    size = pcm_path.stat().st_size
    n_samples = size // 2
    tmp = wav_path.with_suffix(".wav.tmp")
    with open(pcm_path, "rb") as src, wave.open(str(tmp), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(sample_rate)
        remaining = n_samples * 2
        while remaining > 0:
            chunk = src.read(min(remaining, 1 << 20))
            if not chunk:
                break
            dst.writeframes(chunk)
            remaining -= len(chunk)
    with wave.open(str(tmp), "rb") as check:
        written = check.getnframes()
    if written != n_samples:
        raise OSError(f"WAV verify failed: {written} != {n_samples} samples")
    os.replace(tmp, wav_path)
    return n_samples
