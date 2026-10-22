# HANDOVER — listen-n-speak

Handover for the next agent session. Project: **listen-n-speak** — an MCP
server that gives agents **ears** and a **mouth**: transcription (audio →
text), synthesis (text → audio), and a human-in-the-loop `listen` dialog.
Fourth in the collection (look-n-see, scrape-n-search, store-n-recall).

## What this project is

- **Problem solved**: an agent in a harness receives audio the way it
  receives images (file path / data URI / URL) and has no mic or speaker;
  this stdio MCP server is its ears and mouth. Results are structured JSON;
  file paths, never audio blobs.
- **Four tools**: `transcribe` (audio triple → text), `speak` (text →
  utterance + playback, blocks until finished), `synthesize` (text →
  utterance file, no sink needed), `listen` (tkinter dialog: agent prompt,
  red record button, live-typed transcript, 5 s silence auto-stop,
  Clear/Send; window close = structured dismissal).
- **Engine dispatcher** (look-n-see OCR pattern): STT `faster-whisper`
  (local, offline, streaming-capable) + `groq` (cloud, batch only); TTS
  `piper` (local), `edge` (cloud, no key, unofficial), `openai`-compatible
  `/audio/speech`, `espeak` (zero-dep floor). Per-call `engine=`, env
  default, fallback chain.
- **Variants from one package**: `TRANSCRIBE_ENABLED` / `SPEAK_ENABLED`
  (both speech-output tools) / `LISTEN_ENABLED` gate registration;
  `LISTEN_ENABLED=0` is the file-based Core variant.

## Current state (verified 2026-10-23)

- **Implemented end to end.** 60 offline tests pass; live round-trip
  (piper → faster-whisper) matched the spoken sentence at **100% word
  similarity** with playback working; `scripts/mcp_smoke.py` spawned the
  server over stdio and exercised all four tools.
- **Dialog verified for real (2026-10-23, after the `tk` install):**
  `scripts/dialog_smoke.py` synthesizes a sentence, plays it into a PipeWire
  null sink, points capture at that monitor source, and drives `listen`
  through recording → silence auto-stop (8.3 s capture) → final transcript →
  auto-send; the MCP call returned a **100% matching transcript**.
- Benchmarks (README table): piper 1.38–1.57 s for 3–7 s speech; edge
  1.57–2.01 s; espeak 0.05 s but 7.7–33.3% WER when transcribed (robotic);
  whisper base int8 RTF 0.05–0.48, WER 0–7.7%; dialog live refresh
  1.35–1.54 s per rolling window (~3 s UI cadence).
- Registered with OMP: `~/.omp/agent/mcp.json` → `listen-n-speak` (stdio,
  `/mnt/shared/Source/listen-n-speak/.venv/bin/listen-n-speak`,
  `timeout: 600000`). **Restart the OMP client (or `/mcp reload`) to load
  it**, then `/mcp test listen-n-speak`.
- GitHub: `github.com/hughyyy/listen-n-speak` (private, branch `main`,
  about set). Nothing on PyPI.

## Environment facts (this VM)

- Python 3.14.7 only; cp314 wheels confirmed for ctranslate2 4.8.3,
  onnxruntime 1.31.0, piper-tts 1.8.0 (abi3), av 19 (abi3), tokenizers
  (abi3) — `research/engine-availability.md`.
- `tk` **installed** (user-admin action, 2026-10-23): tkinter 8.6 imports
  and the dialog was verified end to end via a null sink.
- `espeak-ng` **installed** (1.52.0): synthesis takes ~0.05 s, but
  intelligibility when transcribed is poor (7.7–33.3% WER), so it remains
  the zero-dep floor only.
- `GROQ_API_KEY` absent → the groq STT path is coded but unexercised.
  `LISTEN_N_SPEAK_TTS_BASE_URL`/`_API_KEY` absent → the `openai` TTS path is
  unexercised.
- PipeWire provides sinks, sources, and a monitor; the dialog is mic-only per
  spec. `ffmpeg`/`ffprobe`/`parecord`/`aplay`/`ffplay` are present.
- Weights cached under `~/.cache/listen-n-speak/` (piper voice ~63 MB,
  whisper base ~145 MB).

## How to run

```bash
cd /mnt/shared/Source/listen-n-speak
.venv/bin/python -m unittest discover -s tests -q   # offline suite (60)
.venv/bin/python scripts/live_smoke.py              # piper → whisper → aplay
.venv/bin/python scripts/mcp_smoke.py               # stdio MCP, all tools
.venv/bin/python scripts/dialog_smoke.py            # listen dialog, real audio
.venv/bin/listen-n-speak                            # stdio MCP server
```

## Key files

- `src/listen_n_speak/server.py` — MCPServer + gated registration + dialog spawn
- `src/listen_n_speak/audio.py` — input triple → 16 kHz mono WAV, transcode
- `src/listen_n_speak/stt.py` — dispatcher + faster-whisper / groq
- `src/listen_n_speak/tts.py` — dispatcher + piper / edge / openai / espeak + playback
- `src/listen_n_speak/dialog/{app,capture,streaming,ipc}.py` — the dialog
- `src/listen_n_speak/config.py` — env parsing + variant gates
- `BRIEF.md` (requirements), `IMPLEMENTATION.md` (design + results),
  `README.md` (user surface + benchmark table), `CONTEXT.md` (vocabulary)

## Known issues / notes

- **Do not pass file paths to faster-whisper** — PyAV 14+ renamed
  `av.open`'s `metadata_errors` and faster-whisper 1.2.1 fails on 1.2.x
  path decoding. `stt._read_wav_samples` feeds a float32 numpy array instead;
  keep it that way.
- **Playback under sanitized envs**: clients that whitelist the child
  environment drop `XDG_RUNTIME_DIR`, and aplay fails with "Host is down".
  `play_file` restores `/run/user/<uid>` when absent; OMP passes the session
  env.
- Live typing re-transcribes a rolling 30 s window every ~1.5 s; the UI
  updates roughly every 3 s on this CPU. Earlier words scroll out of the live
  view, but the final transcript (Send/auto-stop) re-transcribes the whole
  recording.
- `listen` is human-paced: keep `"timeout": 600000` in the harness config or
  normal dialogs get killed at 30 s.
- README benchmark numbers are from synthesized speech — they flatter every
  engine equally; treat them as relative.
- The repo is **private**; flipping public is a user decision
  (`gh repo edit --visibility public`).

## Open items / next steps

- **Groq STT**: set `GROQ_API_KEY` and run `bench_stt.py --engines
  faster-whisper,groq` for the cloud comparison.
- **OpenAI-compatible TTS**: point `LISTEN_N_SPEAK_TTS_BASE_URL`/`_API_KEY`
  at a provider and benchmark it; the adapter is coded and unit-tested.
- **Live dialog by hand** (optional): run `listen` from an OMP session to
  confirm the interactive button path and live typing feel; automation covers
  the flow, and the literal mouse click is the only untested step.
- **Listening ranking**: blind-rank `benchmarks/results/tts-*/` and record
  the verdict in README before changing the TTS default.
- **Live typists**: if 3 s cadence is too slow, shorten `LIVE_REFRESH_S`
  and/or drop to the `tiny` tier for the live view only.
- **Release & packaging**: deferred; mirror look-n-see (CI, tag-triggered
  release, PyPI trusted publishing); `LICENSE` choice pending user decision.
