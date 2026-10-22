# AGENTS.md — listen-n-speak

## Project

MCP server giving agents speech I/O: transcription (audio → text) and
synthesis (text → audio). Fourth in the collection (look-n-see,
scrape-n-search, store-n-recall). **Status: design captured, implementation
not started** — the design lives in `README.md` (draft tool surface, engines,
config) and `CONTEXT.md` (vocabulary). The open design questions at the bottom
of README gate the spec; resolve them with the user before implementing.

## Conventions

- Use `CONTEXT.md` terms exactly: audio, transcript, utterance, transcription,
  synthesis, engine, voice. They are not synonyms for anything else.
- Python 3.10+. No Node/Cargo toolchains on this workstation; system Python is
  3.14 — verify wheel availability for local engines (CTranslate2, onnxruntime)
  before committing to one.
- Dependency-light: `mcp>=2` + `httpx` baseline — parity with look-n-see's
  `pyproject.toml`. Local engines go behind extras (`[stt]`, `[tts]`).
  Tests use stdlib `unittest`, zero dev deps.
- setuptools src layout: package `listen_n_speak`, console script
  `listen-n-speak` (stdio transport), module `listen_n_speak.server:main`.
- Engine pluggability follows look-n-see's OCR pattern: engine param per call,
  env-configured default, fallback chain; a missing engine/model/key degrades
  to a clear error, never a traceback.
- Every tool returns structured output the calling model can act on (JSON
  where it matters, not prose-only).
- Tool surface stays minimal (`transcribe`, `speak` as the draft core; `listen`
  reserved for a mic-capture tool). A new tool needs a README row and a reason
  it cannot be a param; a new engine or env var needs a README update in the
  same change.
- OMP's default MCP request timeout is 30 s — no tool call may block for
  minutes; long captures must be capped or moved out of the call.
- Config via environment variables (`LISTEN_N_SPEAK_*`) with sane defaults;
  secrets from env only, never hardcoded or committed.
- Workstation audio facts: PipeWire present (sinks, sources, monitor),
  arecord/aplay/ffmpeg/ffprobe/parecord/pw-record installed; sox, espeak-ng,
  piper, whisper binaries absent (install via pacman when an engine needs one).

## Workflow

- The design in `README.md` is the draft spec. Open questions are resolved
  with the user first. When implementation starts, create `BRIEF.md`
  (requirements) and `IMPLEMENTATION.md` (design + release plan) like
  look-n-see, and keep them in sync with decisions made during implementation.
- Requirements questions go to the user one at a time, each framed with its
  problem context, options, and recommendation — never batched.
- One commit per logical change; conventional commits, imperative subject.
  Docs-only changes say so.

## Verification

- `python -m compileall` / import smoke test after changes.
- `python -m unittest discover -s tests -q` — the offline suite.
- Server must start and register tools with no engines, models, or keys
  present (clear errors on use, no network required at startup).
- Local engines must work offline once their models/voices are cached. Live
  calls are manual smoke (script or a real MCP call through the harness), not
  part of the suite.
