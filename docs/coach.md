# Interview coach

The coach records a phone interview through the Mac's built-in microphone while the
phone sits on speakerphone next to the laptop. It transcribes the call live with
Deepgram, sends the transcript to Claude, and shows short coaching cards in a local
browser page. After the call it re-transcribes the whole recording for a cleaner
final transcript.

Everything runs in one Python process bound to `127.0.0.1`, and it makes no sound.

## Setup

1. `uv sync`, then copy `.env.example` to `~/.config/sidecar/.env` and add
   `ANTHROPIC_API_KEY` and `DEEPGRAM_API_KEY`. Copy `config.example.toml` to
   `~/.config/sidecar/config.toml` and set `brief_path` to your research brief.
2. Give your terminal app microphone access in System Settings > Privacy & Security >
   Microphone, then restart the terminal.
3. Run `uv run coach preflight`. Every check should pass. A low level-meter warning
   is expected if nobody spoke during the check.

## Commands

```sh
uv run coach preflight
uv run coach run --interviewee "Dana Brooks" --org "Hearth & Crumb Bakery" --minutes 30 \
    [--notes notes/dana.md]
uv run coach finalize <session folder>    # rerun the batch transcription
uv run coach recover <session folder>     # rebuild files after a crash
```

Settings come from `~/.config/sidecar/config.toml` (copy `config.example.toml` to
start). It points at
the research brief and prompts the coach reads, sets the label used for you in the
transcript (`interviewer_label`), and holds Deepgram keyterms and model settings.
`--config other.toml` (before the subcommand) selects another study.

For testing, `--replay file.wav` feeds a recording instead of the microphone, and
the session ends on its own when the file runs out. Keep `--speed` at 1.0 when
testing transcription or coaching: Deepgram's live endpoint works at about real
time, so a faster replay leaves the live transcript behind. `--no-browser` and
`--autostart` help when running unattended, and `--debug` turns on verbose logging.

## Before a call

1. Plug in the laptop, close apps that make sounds, and turn on Do Not Disturb.
2. Run `uv run coach preflight` and play something through the phone speaker
   during the level check.
3. Put the phone on speakerphone next to the laptop. Headphones and AirPods off.
4. Start `uv run coach run ...`, get consent, and press Enter or click Start.

During the call: `M` marks a moment for deeper analysis, `Q` asks for the best next
question, `S` swaps the speaker labels, and `Esc` dismisses the pinned result. End
takes two clicks within three seconds. Ctrl-C in the terminal also ends the session;
a second Ctrl-C skips the batch transcription, which `coach finalize` can rerun.

## Session files

Each call is saved in a folder named `YYYY-MM-DD_HHMM_<slug>` inside the recordings
directory (`interviews_dir`, by default `~/Documents/Sidecar/recordings`):

| File | Contents |
|---|---|
| `audio.wav` | The full recording, 16 kHz mono. `audio.pcm` exists only during recording or after a crash. |
| `transcript.md` | Final transcript from the batch pass, or the live transcript with a note if the batch pass failed. |
| `transcript_live.md`, `transcript_live.jsonl` | Live transcript. |
| `transcript_deepgram.json` | Raw batch response. |
| `coach.jsonl` | Every Claude call: mode, trigger, latency, usage, cost, and output. |
| `marks.jsonl`, `asks.jsonl`, `evidence.jsonl` | MARK and ASK NEXT results and logged evidence. |
| `events.jsonl` | Button presses, speaker swaps, mapping changes, transcription gaps, status changes. |
| `session.json` | Interviewee, config snapshot (no keys), models, mapping history, costs, finalize status. |
| `session.log` | Process log. |

## How it works

```
mic -> sounddevice callback (16 kHz int16, 100 ms blocks) -> queue
  -> writer thread: audio.pcm (flush every 1 s, fsync every 5 s), loudness log
  -> bounded asyncio queue -> Deepgram live websocket
       -> segments -> speaker labels -> transcript store
            -> scheduler -> Claude (live, mark, ask next) -> UI websocket
```

The audio callback and writer thread never wait on the network, the event loop, or
the UI, so a failure in transcription, coaching, or the browser never stops the
recording. Each of those runs as a supervised task and reports its state in the
status bar.

### Speaker labels

The interviewer sits next to the microphone and the interviewee comes through the
phone speaker, so the interviewer's words are much louder. After about 20 words the labeler
learns two loudness clusters and labels each Deepgram fragment by its own median
loudness. Deepgram's live speaker ids are only used before that, because the live
diarizer often merges both voices at the start of a call and flips ids word by word
later on. `S` flips all labels, including in the saved transcripts.

### Coaching

- Claude is called with `tool_choice: auto`, `strict` tool schemas, and a prompt
  that requires the tool call, because Sonnet 5.5 rejects forced tool choice. A
  response without a valid tool call is logged and dropped.
- Live updates and ASK NEXT use the lowest thinking setting (`between_tools`) at low
  effort; MARK uses adaptive thinking at medium effort.
- Live calls stream, and cards are shown as soon as the cards array is complete,
  before the evidence list finishes.
- The request is laid out for prompt caching: tools and system prompt first, then
  closed transcript chunks (cached), then the open chunk and per-call instructions.
  A `max_tokens: 0` request at the start of a session warms the cache.
- `live_activity` in the config sets how often cards appear: `quiet` (a few per
  interview), `balanced` (about one every one to two minutes), or `active`.

### Transcription

- The live connection sends a KeepAlive during silence and reconnects with
  exponential backoff. The send queue holds five seconds of audio, so a short
  outage loses nothing. A longer one is marked as a gap in the transcript; the audio
  is still on disk and the batch pass covers it.
- The batch pass uses Deepgram's newer diarizer, then maps its speakers to the live
  labels by time overlap, so manual swaps carry over.

## Known limitations

- The first 30 to 60 seconds of the live transcript may carry a single label,
  because Deepgram returns that stretch as one fragment. Press `S` if the labels are
  backwards after the first minute. The final transcript is more reliable.
- Moving the phone or the laptop changes the loudness levels; the labeler adapts
  over the next few dozen words.
- Talk share and the TALKING TOO MUCH card depend on the live labels.
- `caffeinate` prevents idle sleep but not lid-close sleep. Keep the lid open and
  the charger connected during a call.
