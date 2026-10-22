# AGENTS.md — listen-n-speak

## Project

MCP server giving agents speech I/O: transcription (audio → text), synthesis
(text → audio), and a human-in-the-loop listening dialog. Fourth in the
collection (look-n-see, scrape-n-search, store-n-recall). **Status:
requirements settled 2026-10-22; implementation not started** — requirements
in `BRIEF.md`, design + phased plan in `IMPLEMENTATION.md`, user-facing
surface in `README.md`, vocabulary in `CONTEXT.md`.

## Conventions

- Use `CONTEXT.md` terms exactly: audio, transcript, utterance, transcription,
  synthesis, engine, voice. They are not synonyms for anything else.
- Python 3.10+. No Node/Cargo toolchains on this workstation; system Python is
  3.14 — local-engine wheel availability was verified 2026-10-22 (see
  `research/engine-availability.md`); kokoro-onnx hard-caps at Python <3.14.
- Dependency-light: `mcp>=2` + `httpx` baseline — parity with look-n-see's
  `pyproject.toml`. Local engines go behind extras (`[stt]`, `[tts]`).
  Tests use stdlib `unittest`, zero dev deps.
- setuptools src layout: package `listen_n_speak`, console script
  `listen-n-speak` (stdio transport), module `listen_n_speak.server:main`.
- Engine pluggability follows look-n-see's OCR pattern: engine param per call,
  env-configured default, fallback chain; a missing engine/model/key degrades
  to a clear error, never a traceback.
- Kokoro is deferred: no adapter in v1. `scripts/download-kokoro-model.sh`
  fetches its weights for evaluation outside this VM (kokoro-onnx supports
  Python ≤3.13; this workstation has only 3.14) — never built or tested in-VM.
- Every tool returns structured output the calling model can act on (JSON
  where it matters, not prose-only).
- Tool surface stays minimal: `transcribe`, `speak`, `synthesize`, `listen`.
  A new tool needs a README row and a reason it cannot be a param; a new
  engine or env var needs a README update in the same change.
- OMP's default MCP request timeout is 30 s — no tool call may block for
  minutes; long captures must be capped or moved out of the call.
- Config via environment variables (`LISTEN_N_SPEAK_*`) with sane defaults;
  secrets from env only, never hardcoded or committed.
- Workstation audio facts: PipeWire present (sinks, sources, monitor),
  arecord/aplay/ffmpeg/ffprobe/parecord/pw-record installed; sox absent.
  Pacman offers: espeak-ng 1.52, whisper.cpp 1.9.5, piper 0.8, tk 5.7 MiB
  (tk fixes the VM's broken tkinter — needed by the listen dialog).

## Workflow

- `BRIEF.md` (requirements) and `IMPLEMENTATION.md` (design + phased plan)
  are the spec of record, settled with the user 2026-10-22; keep both in
  sync with decisions made during implementation, and keep README matching
  the shipped surface.
- Requirements questions go to the user one at a time, each framed with its
  problem context, options, and recommendation — never batched.
- Engine defaults are set from benchmark evidence (see Benchmarks in README),
  not assertion — same discipline as look-n-see's model sweep.
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
