"""Command line entry point: preflight, run, finalize, recover."""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import numpy as np

from coach.audio import block_levels, find_input_device, pcm_to_wav
from coach.config import Config, load_config
from coach.session import (
    LiveSession,
    describe_error,
    load_live_segments,
    new_session_dir,
    read_json,
    run_batch,
    setup_session_logging,
    update_session_json,
    wav_duration,
    write_fallback_transcript,
    write_live_markdown,
)
from coach.stt_live import LIVE_URL, live_query

log = logging.getLogger("coach")

RISKY_DEVICE_WORDS = ("iphone", "airpods", "bluetooth")
MIC_PERMISSION_HINT = (
    "System Settings > Privacy & Security > Microphone: enable the terminal app "
    "you run this from (Terminal, iTerm, VS Code, ...), then restart that app."
)
LOW_PEAK = 0.05
MIN_FREE_BYTES = 1 << 30
SIGNAL_DEBOUNCE_S = 1.0


def _result(name: str, ok: bool, detail: str = "", warn: bool = False) -> dict:
    return {"name": name, "ok": ok, "warn": warn, "detail": detail}


def _print_result(res: dict) -> None:
    tag = "PASS" if res["ok"] and not res["warn"] else ("WARN" if res["ok"] else "FAIL")
    print(f"{tag:4}  {res['name']}: {res['detail']}", flush=True)


def check_device(cfg: Config) -> dict:
    import sounddevice as sd

    try:
        idx = find_input_device(cfg.audio.input_device)
        dev = (
            sd.query_devices(idx, kind="input")
            if idx is not None
            else sd.query_devices(kind="input")
        )
    except (ValueError, sd.PortAudioError) as exc:
        return _result("input device", False, str(exc))
    name = dev["name"]
    risky = any(word in name.lower() for word in RISKY_DEVICE_WORDS)
    detail = f"{name}" + (" (not the built-in mic: check this is intended)" if risky else "")
    return _result("input device", True, detail, warn=risky)


def list_devices() -> None:
    import sounddevice as sd

    print("Input devices:")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            print(f"  [{idx}] {dev['name']} ({int(dev['default_samplerate'])} Hz)")


def record_seconds(cfg: Config, seconds: float) -> np.ndarray:
    import sounddevice as sd

    sr = cfg.audio.sample_rate
    data = sd.rec(
        int(seconds * sr),
        samplerate=sr,
        channels=1,
        dtype="int16",
        device=find_input_device(cfg.audio.input_device),
    )
    sd.wait()
    return data.reshape(-1)


def check_recording(cfg: Config, seconds: float) -> tuple[dict, bytes]:
    import sounddevice as sd

    try:
        data = record_seconds(cfg, seconds)
    except (sd.PortAudioError, ValueError) as exc:
        return _result("mic capture", False, f"{exc}. {MIC_PERMISSION_HINT}"), b""
    if not np.any(data):
        return _result("mic capture", False, f"all zeros. {MIC_PERMISSION_HINT}"), b""
    _, peak = block_levels(data.tobytes())
    return _result("mic capture", True, f"{seconds:.0f}s recorded, peak {peak:.2f}"), data.tobytes()


def check_level_meter(cfg: Config, seconds: float = 10.0) -> dict:
    import sounddevice as sd

    print("Talk normally, and play audio through the phone speaker, for 10 seconds.")
    peak_max = 0.0
    sr, bf = cfg.audio.sample_rate, cfg.audio.block_frames
    try:
        with sd.InputStream(
            samplerate=sr,
            channels=1,
            dtype="int16",
            blocksize=bf,
            device=find_input_device(cfg.audio.input_device),
        ) as stream:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                block, _ = stream.read(bf)
                rms, peak = block_levels(bytes(block))
                peak_max = max(peak_max, peak)
                bar = "#" * min(50, int(rms * 400))
                print(f"\r  level |{bar:<50}| peak {peak:.2f}", end="", flush=True)
    except sd.PortAudioError as exc:
        print()
        return _result("level meter", False, str(exc))
    print()
    if peak_max < LOW_PEAK:
        return _result("level meter", True, f"peak {peak_max:.2f} is low: move closer", warn=True)
    return _result("level meter", True, f"peak {peak_max:.2f}")


def check_disk(cfg: Config) -> dict:
    cfg.interviews_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(cfg.interviews_dir).free
    return _result("disk space", free >= MIN_FREE_BYTES, f"{free / 1e9:.1f} GB free")


def check_port(cfg: Config) -> dict:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", cfg.server.port))
        except OSError:
            return _result("port", False, f"127.0.0.1:{cfg.server.port} is in use")
    return _result("port", True, f"127.0.0.1:{cfg.server.port} free")


async def check_anthropic(cfg: Config) -> dict:
    import anthropic

    if not cfg.anthropic_api_key:
        return _result("anthropic", False, "ANTHROPIC_API_KEY missing in .env")
    client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key, timeout=20.0, max_retries=0)
    t0 = time.monotonic()
    try:
        resp = await client.messages.create(
            model=cfg.coach.live_model,
            max_tokens=64,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the word OK."}],
        )
    except anthropic.APIError as exc:
        return _result("anthropic", False, f"{type(exc).__name__}: {exc}"[:200])
    finally:
        await client.close()
    return _result("anthropic", True, f"{resp.model} answered in {time.monotonic() - t0:.1f}s")


async def check_deepgram(cfg: Config, audio: bytes) -> dict:
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus, WebSocketException

    if not cfg.deepgram_api_key:
        return _result("deepgram live", False, "DEEPGRAM_API_KEY missing in .env")
    sr, bf = cfg.audio.sample_rate, cfg.audio.block_frames
    if not audio:
        audio = bytes(sr * 2 * 3)
    url = f"{LIVE_URL}?{live_query(cfg.deepgram, sr, list(cfg.deepgram.keyterms))}"
    got: list[str] = []
    try:
        async with asyncio.timeout(20):
            async with connect(
                url, additional_headers={"Authorization": f"Token {cfg.deepgram_api_key}"}
            ) as ws:
                for i in range(0, len(audio), bf * 2):
                    await ws.send(audio[i : i + bf * 2])
                await ws.send(json.dumps({"type": "CloseStream"}))
                async for raw in ws:
                    if isinstance(raw, str):
                        got.append(json.loads(raw).get("type", "?"))
    except InvalidStatus as exc:
        return _result("deepgram live", False, f"HTTP {exc.response.status_code}")
    except (OSError, WebSocketException, TimeoutError) as exc:
        return _result("deepgram live", False, f"{type(exc).__name__}: {exc}"[:200])
    if not got:
        return _result("deepgram live", False, "no response messages")
    kinds = ", ".join(sorted(set(got)))
    return _result("deepgram live", True, f"received {len(got)} messages ({kinds})")


def cmd_preflight(cfg: Config) -> int:
    list_devices()
    results = [check_device(cfg)]
    _print_result(results[-1])
    rec, audio = check_recording(cfg, 3.0)
    results.append(rec)
    _print_result(rec)
    if rec["ok"]:
        results.append(check_level_meter(cfg))
        _print_result(results[-1])
    for res in (asyncio.run(check_anthropic(cfg)), asyncio.run(check_deepgram(cfg, audio))):
        results.append(res)
        _print_result(res)
    for res in (check_disk(cfg), check_port(cfg)):
        results.append(res)
        _print_result(res)
    failed = [r for r in results if not r["ok"]]
    print("\nPREFLIGHT " + ("PASS" if not failed else f"FAIL ({len(failed)} failed)"))
    return 0 if not failed else 1


async def quiet_preflight(cfg: Config, replay: bool) -> list[dict]:
    results: list[dict] = []
    audio = b""
    if not replay:
        results.append(check_device(cfg))
        rec, audio = await asyncio.to_thread(check_recording, cfg, 1.0)
        results.append(rec)
    results.append(await check_anthropic(cfg))
    results.append(await check_deepgram(cfg, audio))
    results.append(check_disk(cfg))
    for res in results:
        _print_result(res)
    return results


def setup_console_logging(debug: bool) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    for noisy in ("httpx2", "httpcore", "websockets", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def run_session(cfg: Config, args: argparse.Namespace) -> int:
    from coach.server import Hub, create_app, make_server

    port_check = check_port(cfg)
    if not port_check["ok"]:
        _print_result(port_check)
        return 1
    replay = Path(args.replay) if args.replay else None
    notes = Path(args.notes) if args.notes else None
    session_dir = new_session_dir(cfg, args.interviewee)
    setup_session_logging(session_dir)
    print(f"Session directory: {session_dir}")
    session = LiveSession(
        cfg,
        session_dir,
        args.interviewee,
        args.org,
        args.minutes,
        notes,
        replay=replay,
        speed=args.speed,
    )
    print("Preflight:")
    session.preflight = await quiet_preflight(cfg, replay is not None)
    hub = Hub()
    session.broadcast = hub.broadcast
    server = make_server(create_app(session, hub), cfg.server.port)
    loop = asyncio.get_running_loop()
    sigints = 0
    last_signal = 0.0

    def on_signal(sig: signal.Signals) -> None:
        nonlocal sigints, last_signal
        now = time.monotonic()
        if now - last_signal < SIGNAL_DEBOUNCE_S:
            return
        last_signal = now
        if sig == signal.SIGINT:
            sigints += 1
        if sigints >= 2:
            print("\nSkipping batch transcription. Finishing audio and live transcript.")
            session.skip_batch.set()
            return
        print("\nEnding session. Press Ctrl-C again to skip batch transcription.")
        session.request_end()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_signal, sig)

    def on_ended() -> None:
        loop.call_later(1.0, setattr, server, "should_exit", True)

    session.on_ended = on_ended
    caffeinate = subprocess.Popen(
        ["caffeinate", "-dimsu", "-w", str(os.getpid())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{cfg.server.port}/"
    serve = asyncio.create_task(server.serve())
    while not server.started and not serve.done():
        await asyncio.sleep(0.05)
    print(f"UI: {url}")
    if not args.no_browser:
        webbrowser.open(url)
    if args.autostart:
        session.start()
    await serve
    if not session.finalized.is_set():
        await session.finalize()
    caffeinate.terminate()
    return 0


def cmd_finalize(cfg: Config, session_dir: Path) -> int:
    wav = session_dir / "audio.wav"
    if (session_dir / "audio.pcm").exists():
        print("audio.pcm found. Run `coach recover` first.")
        return 1
    if not wav.exists():
        print(f"No audio.wav in {session_dir}")
        return 1
    try:
        asyncio.run(run_batch(cfg, session_dir))
        status = "ok"
        print(f"Wrote {session_dir / 'transcript.md'}")
    except Exception as exc:  # noqa: BLE001 - report any batch failure and fall back
        status = f"failed: {describe_error(exc)}"
        write_fallback_transcript(session_dir, wav_duration(wav), status)
        print(f"Batch transcription failed: {status}")
    steps = read_json(session_dir / "session.json").get("finalize_steps", {})
    steps["batch"] = status
    update_session_json(session_dir, finalize_steps=steps)
    return 0 if status == "ok" else 1


def cmd_recover(cfg: Config, session_dir: Path, assume_yes: bool) -> int:
    pcm = session_dir / "audio.pcm"
    wav = session_dir / "audio.wav"
    if pcm.exists():
        n = pcm_to_wav(pcm, wav, cfg.audio.sample_rate)
        pcm.unlink()
        print(f"Rebuilt {wav} ({n / cfg.audio.sample_rate:.1f}s)")
    elif wav.exists():
        print(f"{wav} already exists")
    else:
        print("No audio.pcm or audio.wav found")
    segments = load_live_segments(session_dir)
    duration = wav_duration(wav) if wav.exists() else 0.0
    write_live_markdown(session_dir, segments, duration)
    print(f"Rebuilt {session_dir / 'transcript_live.md'} from {len(segments)} segments")
    update_session_json(session_dir, recovered=True)
    if not wav.exists():
        return 1
    if not assume_yes:
        answer = input("Run batch finalize now? [y/N] ").strip().lower()
        if answer != "y":
            print(f"Later: uv run coach finalize {session_dir}")
            return 0
    return cmd_finalize(cfg, session_dir)


def main() -> None:
    parser = argparse.ArgumentParser(prog="coach")
    parser.add_argument("--debug", action="store_true", help="verbose console logging")
    parser.add_argument("--config", default=None, help="TOML config file (default config.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="check mic, keys, network, disk, port")
    run = sub.add_parser("run", help="run a live interview session")
    run.add_argument("--interviewee", required=True)
    run.add_argument("--org", default="")
    run.add_argument("--minutes", type=int, default=None)
    run.add_argument("--notes", default=None, help="path to interviewee notes markdown")
    run.add_argument("--replay", default=None, help="WAV file to replay instead of the mic")
    run.add_argument("--speed", type=float, default=1.0)
    run.add_argument("--no-browser", action="store_true", help="do not open the browser")
    run.add_argument("--autostart", action="store_true", help="start recording immediately")
    fin = sub.add_parser("finalize", help="rerun batch transcription for a session")
    fin.add_argument("dir")
    rec = sub.add_parser("recover", help="rebuild files after a crash")
    rec.add_argument("dir")
    rec.add_argument("--yes", action="store_true", help="run finalize without asking")
    args = parser.parse_args()

    cfg = load_config(config_path=Path(args.config) if args.config else None)
    setup_console_logging(args.debug)
    if args.command == "preflight":
        sys.exit(cmd_preflight(cfg))
    if args.command == "run":
        if args.minutes is None:
            args.minutes = cfg.session.default_planned_minutes
        with contextlib.suppress(KeyboardInterrupt):
            sys.exit(asyncio.run(run_session(cfg, args)))
    if args.command == "finalize":
        sys.exit(cmd_finalize(cfg, Path(args.dir)))
    if args.command == "recover":
        sys.exit(cmd_recover(cfg, Path(args.dir), args.yes))
