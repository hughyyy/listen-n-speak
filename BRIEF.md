# listen-n-speak — Project Brief

## Purpose

An MCP server giving agents speech I/O — transcription (audio → text),
synthesis (text → audio), and a human-in-the-loop listening dialog. Fourth in
the collection (look-n-see, scrape-n-search, store-n-recall). An agent inside
a harness receives audio the way it receives images — a file path, a base64
`data:` URI, or a URL — and has no microphone or speaker of its own; this
server is its ears and its mouth.

## Refined requirements (from concept Q&A, 2026-10-22)

### Audio input
- `transcribe` accepts all three, auto-detected (same triple as look-n-see
  images): file path on disk, base64 data URI, `http(s)://` URL.
- Normalization: `ffprobe` probe → `ffmpeg` convert to one canonical form
  (16 kHz mono WAV) before any engine sees the audio — engines never see
  format variety.

### Transport
- **stdio** only (local MCP client spawns the server as a subprocess).
- Tool calls are one-shot request/response. No protocol-level streaming:
  streaming may exist inside a process (the dialog's live transcription) but
  never crosses the MCP boundary. Escape hatch if agent-side partials ever
  matter: a polling trio (start/status/stop) — never a transport change.

### Tools
- `transcribe(audio, engine?, language?, model?)` → `{"text", "language",
  "duration_s", "engine"}`. `language` passes through to the engine
  (auto-detect default).
- `speak(text, engine?, voice?, format?)` → `{"file", "played",
  "duration_s", "engine", "voice"}` — synthesis + playback; **blocks until
  playback finishes** so consecutive utterances stay ordered; playback is
  best-effort (no sink → clear error, file still returned).
- `synthesize(text, engine?, voice?, format?)` → `{"file", "duration_s",
  "engine", "voice"}` — synthesis without playback; no sink required
  (headless-safe, works in every variant).
- `listen(prompt, silence_s?, max_s?, engine?)` → `{"text", "audio",
  "duration_s", "engine"}`; dismissal → `{"text": null, "reason":
  "dismissed"}`. `silence_s` default 5; `max_s` default 300.
- Every tool returns structured JSON the calling model can act on (house
  rule); file paths, never base64 audio blobs.

### The listen dialog (human-in-the-loop)
- Small window on the host display (X11 today; tkinter, stdlib; one-time
  `pacman -S tk` fixes the workstation's missing `libtk8.6.so`). The dialog
  runs as a spawned subprocess per call so a GUI crash never takes down the
  server and the server stays stateless.
- The agent's required `prompt` is displayed in the window; **recording does
  not start until the human clicks the red record button**.
- Live transcription: words typed into a response box as they arrive
  (requires the streaming-capable local engine).
- Recording auto-stops after `silence_s` of silence; absolute cap `max_s`.
- Then **Clear** (empty the box, record again) or **Send** (return the
  transcript to the calling agent). Closing the window counts as dismissal.
- Capture: host **microphone only** (`LISTEN_N_SPEAK_INPUT` picks which);
  the PipeWire monitor (system output) is out of scope for v1.
- Graceful degradation: no streaming engine → record with ffmpeg-level
  silence detection and batch-transcribe at the end (cloud engines usable;
  live typing becomes a "recording…" state); no capture device → clear
  error.
- The result keeps the saved audio (path + duration) so the agent can
  re-transcribe with a different engine if needed.

### Engines (dispatcher: per-call `engine=`, env default, fallback chain —
the look-n-see OCR pattern; missing engine/model/key degrades to a clear
error, never a traceback)
- STT `faster-whisper` (local, offline; CTranslate2, CPU; Silero VAD for the
  dialog's silence stop; models cached under XDG cache; streaming-capable —
  serves the dialog's live typing). cp314 wheels verified 2026-10-22
  (`research/engine-availability.md`). whisper.cpp (pacman 1.9.5) is the
  designated local alternative if chunked faster-whisper underperforms.
- STT `groq` (cloud; OpenAI-compatible `/audio/transcriptions`;
  whisper-large-v3-turbo; `GROQ_API_KEY`). Batch only — cannot serve live
  typing.
- TTS `piper` (local, offline; piper-tts + onnxruntime; per-language voice
  files). cp314 wheels verified.
- TTS `edge` (cloud; free Microsoft neural voices; no key; unofficial API —
  usable, but never the default).
- TTS `openai` (cloud; generic OpenAI-compatible `/audio/speech` adapter —
  `LISTEN_N_SPEAK_TTS_BASE_URL` + `LISTEN_N_SPEAK_TTS_API_KEY`, so it also
  reaches Groq PlayAI or local compatible endpoints).
- TTS `espeak-ng` (system binary; robotic; zero-dep emergency floor).
- **Engine defaults are set by benchmark evidence, not assertion** — both
  local and cloud paths are benchmarked before being relied on.
- Kokoro-82M **deferred**: no adapter in v1;
  `scripts/download-kokoro-model.sh` fetches weights for evaluation
  **outside this VM** (kokoro-onnx requires Python <3.14 — hard PyPI cap;
  this VM has only 3.14). Never built or tested in-VM.

### Formats
- Synthesized utterances: WAV (mono) by default; `format=mp3|ogg|flac`
  transcodes via ffmpeg when it differs from the engine's native output
  (edge emits mp3, piper/espeak emit wav, the openai route takes a format
  argument).
- Dialog recordings: WAV 16 kHz mono — internal artifacts, never surfaced.

### Languages
- Multilingual param surface from day one (`language` on `transcribe` is a
  free pass-through on whisper-family engines); the **shipped, benchmarked
  voice catalog is English-only**. Other languages pass through untested —
  supported plumbing, unadvertised quality.

### Release variants (one package, env-gated registration)
- **Full (default)**: all four tools.
- **Core (file-based only)**: `LISTEN_ENABLED=0` — no dialog, no capture
  device, no GUI deps. This is the "pure (A)" configuration the collection
  starts with; the dialog and extras are additive.
- STT only: `SPEAK_ENABLED=0`. TTS only: `TRANSCRIBE_ENABLED=0`.
- `tools/list` advertises exactly the enabled surface.

### Benchmarking (defaults set by evidence)
- STT batch (`transcribe`): latency, accuracy (WER against reference
  transcripts), cost per call — local (faster-whisper; whisper.cpp plan B)
  vs cloud (Groq), same recordings through both.
- STT dialog (`listen`): chunked-transcription real-time factor on CPU,
  partial-transcript latency, silence-stop reliability at the 5 s threshold.
- TTS: synthesis latency, output size, human listening ranking on a fixed
  sample set (announcement, technical sentence with code-like tokens,
  paragraph) — the user is the listener.
- Scripts + results live in `benchmarks/`; tradeoffs in `research/`;
  verdict tables land in README. Manual/scripted — not part of the offline
  unittest suite.

### Deployment
- Local stdio subprocess via console script `listen-n-speak`; user-level OMP
  registration (`~/.omp/agent/mcp.json`), full variant with
  `"timeout": 600000` (human-paced dialog), core fine at defaults.
- Config via `LISTEN_N_SPEAK_*` env vars with sane defaults; secrets from
  env only (OMP `!` indirection supported).

## Stack

- Python 3.10+ (system interpreter 3.14.7 is the only toolchain here)
- `mcp` 2.x + `httpx` baseline — parity with look-n-see's `pyproject.toml`
- Extras: `[stt]` (faster-whisper), `[tts]` (piper-tts + onnxruntime)
- stdlib for input parsing (urllib, base64, mimetypes) and tkinter for the
  dialog; ffmpeg/ffprobe/parecord/aplay via subprocess (already installed)
- setuptools src layout, `pyproject.toml`, console script
- Tests: stdlib `unittest`, zero dev deps

## Non-goals (v1)

- No protocol-level streaming across the MCP boundary; transport stays stdio
  (see Transport for the polling-trio escape hatch).
- No diarization, no word-level timestamps — engines may offer them; the
  tool schemas don't expose them.
- No duplex real-time voice loop — harness-level composition of
  `listen` → think → `speak` covers conversational use; this server refuses
  to be the real-time engine for it.
- No speech translation, no audio-conversion tool surface (ffmpeg exists on
  the host; agents are told to use it directly).
- No monitor/system-output capture — the dialog is mic-only; a passive
  `capture` tool is a future addition if that workflow materializes.
- No Kokoro adapter in v1 (deferred; out-of-VM evaluation first).
- No release/packaging infrastructure in v1 (mirrors look-n-see /
  scrape-n-search after the surface stabilizes).
