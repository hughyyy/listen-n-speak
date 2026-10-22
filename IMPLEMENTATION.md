# listen-n-speak — Implementation Plan

## Goal

A stdio MCP server giving agents transcription, synthesis/playback, and a
human-in-the-loop listening dialog. See `BRIEF.md` for requirements.

## Stack

- Python 3.10+ (3.14.7 is the only interpreter on this workstation)
- `mcp` 2.x (MCPServer) + `httpx` — baseline deps
- Extras: `[stt]` = `faster-whisper` (pulls CTranslate2 — cp314 wheels
  verified 2026-10-22), `[tts]` = `piper-tts` (+ onnxruntime — cp314
  verified); tkinter is stdlib but needs system `tk` (`pacman -S tk`)
- ffmpeg/ffprobe/parecord/aplay via subprocess — preinstalled
- Tests: stdlib `unittest`, zero dev deps

## Layout

```
pyproject.toml
README.md            # user-facing: tools, engines, config, benchmarks
BRIEF.md             # requirements baseline
IMPLEMENTATION.md    # this file: design + phased plan
CONTEXT.md           # vocabulary
AGENTS.md            # conventions
research/
  engine-availability.md   # wheel + pacman facts (2026-10-22)
scripts/
  download-kokoro-model.sh # deferred-engine weights fetch (out-of-VM use)
src/listen_n_speak/
  __init__.py
  __main__.py        # python -m listen_n_speak
  config.py          # env parsing + defaults + variant gates
  audio.py           # input triple → canonical 16 kHz mono WAV (ffprobe/ffmpeg)
  stt.py             # STT dispatcher + faster-whisper / groq engines
  tts.py             # TTS dispatcher + piper / edge / openai / espeak engines + playback
  dialog/
    __init__.py
    app.py           # tkinter dialog: prompt, record button, live box, clear/send
    capture.py       # parecord spawn, chunk tap, silence detection
    streaming.py     # chunked faster-whisper partials for live typing
  server.py          # MCP app + variant-gated registration + dialog spawn + main()
tests/
  test_audio.py
  test_config.py     # env parsing, variant gates, fallback chain parsing
  test_stt.py        # engines (mocked httpx / mocked whisper model), dispatcher
  test_tts.py        # engines (mocked), format normalization, playback
  test_dialog.py     # IPC contract, silence logic (mocked capture), degrade paths
  test_server.py     # registration smoke incl. variant gating
benchmarks/
  *.py               # committed: benchmark scripts
  results/           # gitignored: dated run data
```

## Config (env vars)

| Var | Default | Purpose |
|---|---|---|
| `LISTEN_N_SPEAK_STT_ENGINE` | `faster-whisper` * | default STT engine |
| `LISTEN_N_SPEAK_STT_MODEL` | `base` | whisper model tier (weights under `LISTEN_N_SPEAK_MODELS_DIR`) |
| `LISTEN_N_SPEAK_STT_FALLBACKS` | `groq` | chain tried after the default fails |
| `LISTEN_N_SPEAK_TTS_ENGINE` | `piper` * | default TTS engine |
| `LISTEN_N_SPEAK_TTS_FALLBACKS` | `edge espeak` | same, for synthesis |
| `LISTEN_N_SPEAK_TTS_VOICE` | per-engine default | voice id / voice file |
| `LISTEN_N_SPEAK_TTS_BASE_URL` | — | OpenAI-compatible `/audio/speech` endpoint |
| `LISTEN_N_SPEAK_TTS_API_KEY` | — | key for that endpoint |
| `LISTEN_N_SPEAK_OUTPUT_DIR` | tmp under XDG cache | synthesized utterances + dialog audio |
| `LISTEN_N_SPEAK_MODELS_DIR` | `~/.cache/listen-n-speak` | whisper/piper weight + voice cache |
| `LISTEN_N_SPEAK_INPUT` | system default | which microphone the dialog records |
| `LISTEN_N_SPEAK_SILENCE_S` / `LISTEN_N_SPEAK_MAX_S` | `5` / `300` | dialog defaults (params override) |
| `GROQ_API_KEY` | — | groq STT engine |
| `TRANSCRIBE_ENABLED` / `SPEAK_ENABLED` / `LISTEN_ENABLED` | `1` | tool registration gates (variants) |

\* Provisional defaults — **benchmarks decide** (see BRIEF "Benchmarking");
env always wins over the default.

## Design

### Input normalization (`audio.py`)
Pure function: input triple → local canonical file. URL fetched via httpx to
temp, data URI decoded, path used as-is — then `ffprobe` sanity check and
`ffmpeg -ac 1 -ar 16000` to 16 kHz mono WAV. Mirrors look-n-see's
`images.py` discipline: normalization before any engine; engines only ever
see canonical files. Testable with a tiny generated wav + ffprobe mocks.

### STT dispatcher (`stt.py`)
`transcribe(wav_path, engine, language, model) → dict`. Engines:
- `faster-whisper`: lazy import; `WhisperModel` cached per process (per
  model tier); `language=None` → autodetect; joins segments, returns text +
  detected language + duration.
- `groq`: httpx multipart `POST {GROQ_BASE}/audio/transcriptions` with the
  wav file, `model=whisper-large-v3-turbo`, optional `language`;
  `GROQ_API_KEY` required or a clear error.
Hard failure walks the fallback chain; missing extra → `EngineError` with
the install hint; missing key → clear error. Same shape as look-n-see's
`OcrDispatcher`.

### TTS dispatcher (`tts.py`)
`synthesize(text, engine, voice, fmt) → (utterance_path, metadata)`. Engines
emit their native form (piper/espeak → wav, edge/openai → mp3 by default);
the dispatcher normalizes: when the requested `fmt` differs from native, one
ffmpeg transcode. WAV mono is the default contract.
- `piper`: lazy import; voice file from `LISTEN_N_SPEAK_MODELS_DIR` (or
  auto-download on first use); → wav.
- `edge`: `edge-tts` (async API) driven from the server's event loop; →
  24 kHz mp3.
- `openai`: httpx `POST {base}/audio/speech` with `response_format=fmt`,
  Bearer key; → requested format directly (no transcode when the API
  supplies it).
- `espeak-ng`: subprocess `espeak-ng -w out.wav <text>` (binary check at
  call time, clear hint if absent).
Playback (`speak` only): subprocess `aplay <file>` — blocks for the utterance
duration, best-effort (no sink → clear error, file still returned).

### Dialog (`dialog/`, spawned subprocess)
The `listen` handler spawns
`[sys.executable, "-m", "listen_n_speak.dialog.app", "--prompt", ...,
"--out", <tmp.json>, "--silence-s", N, "--max-s", N]` and waits for exit,
then reads the result JSON. Why a subprocess: the Tk mainloop and its quirks
stay isolated from the stdio server; the server keeps zero GUI/capture state
(statelessness preserved); a dialog crash yields a clean tool error.

Inside the dialog (`app.py`): prompt label; **red record button** (disabled
while recording); response box; Clear/Send buttons; window close = dismissal.
Recording thread (`capture.py`): `parecord` (honors `LISTEN_N_SPEAK_INPUT`)
streaming raw 16 kHz mono s16le on stdout → fixed-size chunks → ring buffer
+ silence detector. Silence: RMS gate always (no deps); Silero VAD via
faster-whisper when `[stt]` is present — which one is the default gets
settled by the dialog benchmark. `silence_s` of silence → stop; `max_s` hard
cap → stop.
Live typing (`streaming.py`): chunks feed faster-whisper incrementally;
partial texts posted to the Tk thread via a queue consumed with `after()`
polling (Tkinter is single-threaded — never touch widgets from the
recording thread). Degraded (no `[stt]`): "recording…" state; the audio is
batch-transcribed at stop through any engine (cloud usable).
IPC contract: dialog writes `{"text", "audio", "duration_s", "engine"}`
(or `{"text": null, "reason": "dismissed"}`) to `--out` and exits 0;
non-zero exit / missing file / timeout (`max_s` + margin) → tool error.

### Variants
`config.py` parses the three gates; `server.py` registers exactly the
enabled tools (MCP spec-sanctioned — same pattern as look-n-see's role
gating and scrape-n-search's `ENABLED_TOOLS`). Core (`LISTEN_ENABLED=0`)
never touches tkinter, parecord, or capture.

## Error handling

- Missing extra / engine / key / binary → `EngineError` naming the fix
  (`pip install 'listen-n-speak[stt]'`, `pacman -S espeak-ng`, key hint).
- No capture device / no sink → clear tool error; file results still
  returned where applicable.
- ffmpeg/ffprobe absent → startup check with an install hint.
- `listen`: dialog timeout → clear error; dismissal → structured
  `{"text": null, "reason": "dismissed"}` result (not an error).
- Never a traceback across the MCP boundary — every failure is a readable
  message the calling model can act on.

## Oh My Pi (OMP) integration

- `~/.omp/agent/mcp.json`: `listen-n-speak` (stdio, `.venv/bin/
  listen-n-speak`), `"timeout": 600000` for the full variant (human-paced
  dialog); the Core variant runs fine at defaults. `GROQ_API_KEY` via the
  `!` `omp token` indirection if used.
- `/mcp reload` → `/mcp test listen-n-speak` → `/mcp list` in an OMP
  session; then real in-session tool calls.
- User-scoped so every agent and subagent gets speech I/O from any cwd.

## Release & packaging plan

**Deferred to post-v1** — mirror look-n-see / scrape-n-search (CI + tag-
triggered GitHub release + PyPI trusted publishing) once the surface
stabilizes; `LICENSE` choice pending user decision, like look-n-see's.
GitHub repo: `github.com/hughyyy/listen-n-speak` — exists (2026-10-22);
nothing published to PyPI.

## Verification

- Offline: `python -m compileall`; `python -m unittest discover -s tests
  -q` (input parsing, config + variants, dispatchers + engines with mocked
  deps, dialog IPC + silence logic with mocked capture, server registration
  incl. gating). The server must start and register tools with no engines,
  models, or keys present.
- Live (manual): `scripts/live_smoke.py` — transcribe a sample wav
  (faster-whisper + groq), synthesize a line (piper + edge + espeak),
  `speak` it through the sink, one `listen` dialog session end-to-end.
- Harness: `/mcp test` + real in-session tool calls from OMP.
- Benchmarks: STT batch (WER / latency / cost), dialog (RTF / partial
  latency / silence reliability), TTS (latency / size / listening ranking) —
  verdicts recorded in README; defaults updated to match.

## Phases (each ends with its tests green + a commit)

1. **Scaffold** — `pyproject.toml` (extras, console script), `config.py`,
   `server.py` skeleton; offline tests pass (registration with all gates
   on).
2. **Audio** — `audio.py` normalization + tests.
3. **STT** — `stt.py` dispatcher, faster-whisper + groq engines, `transcribe`
   tool + tests.
4. **TTS** — `tts.py` dispatcher, piper/edge/openai/espeak engines,
   `speak`/`synthesize` tools + tests.
5. **Dialog** — `dialog/` (app, capture, streaming), `listen` tool, subprocess
   IPC + tests (mocked GUI/capture; manual GUI check).
6. **Variants + docs sync** — gates exercised in tests; README config table
   final; CONTEXT/AGENTS aligned.
7. **Benchmarks** — scripts, runs, verdict → defaults updated in README.
8. **Live smoke + OMP** — `live_smoke.py`, registration, in-harness exercise.

Order rationale: the file-based core (2–4) is independent of the GUI; the
dialog (5) builds on a stable STT path; benchmarks (7) need every engine in
place to compare.
