# HANDOVER — listen-n-speak

Handover for the next agent session. Project: **listen-n-speak** — an MCP
server that gives agents **ears** and a **mouth**: transcription (audio →
text), synthesis (text → audio), and a human-in-the-loop `listen` dialog.
Fourth in the collection (look-n-see, scrape-n-search, store-n-recall).

## What this project is

- **Problem solved**: an agent in a harness receives audio the way it
  receives images (file path / data URI / URL) and has no mic or speaker;
  this stdio MCP server is its ears and mouth. Results come back as
  structured JSON the calling model can act on; file paths, never audio
  blobs.
- **Four tools**: `transcribe` (audio triple → text), `speak` (text →
  utterance + playback, blocking until finished), `synthesize` (text →
  utterance file, no sink required), `listen` (tkinter dialog: agent's
  prompt shown, red record button, live-typed transcript, 5 s silence
  auto-stop, Clear/Send; window close = structured dismissal).
- **Engine dispatcher** (the look-n-see OCR pattern): STT faster-whisper
  (local, offline, streaming-capable — serves live typing) + groq (cloud,
  batch only); TTS piper (local, offline), edge (cloud, no key,
  unofficial), openai-compatible `/audio/speech` (generic endpoint), 
  espeak-ng (zero-dep emergency floor). Per-call `engine=`, env default,
  fallback chain; missing engine/model/key degrades to a clear error.
- **Release variants from one package**: `TRANSCRIBE_ENABLED` /
  `SPEAK_ENABLED` / `LISTEN_ENABLED` gate tool registration at startup
  (`tools/list` advertises exactly the enabled surface). Core variant =
  `LISTEN_ENABLED=0` — file-based only, the "pure (A)" configuration.

## Current state (2026-10-22)

- **Spec complete; implementation NOT started.** All 8 design questions were
  resolved with the user (one at a time, each with problem context).
  Requirements: `BRIEF.md`. Design + 8-phase plan: `IMPLEMENTATION.md`.
  User-facing surface: `README.md`. Vocabulary: `CONTEXT.md`.
- Verified facts (not assumptions): system Python 3.14.7 is the only
  interpreter; cp314 wheels exist for ctranslate2 4.8.3 and onnxruntime
  1.31.0, and piper-tts 1.8.0 ships cp39-abi3 — details in
  `research/engine-availability.md`. kokoro-onnx requires Python <3.14
  (hard PyPI cap → deferred engine; out-of-VM evaluation only).
- Workstation: PipeWire present (sinks + sources + monitor; the dialog is
  mic-only per spec), arecord/aplay/ffmpeg/ffprobe/parecord/pw-record
  installed; sox absent; **tkinter broken until `pacman -S tk`** (~5.7 MiB).
- GitHub: `github.com/hughyyy/listen-n-speak` — repo exists, about set,
  pushed (docs only). Nothing on PyPI.
- Git history: `546a082` scaffold → `4dc9f86` one-question-at-a-time
  convention → `f85937e` listen dialog + variants → `78cea5b` benchmark-
  driven defaults → `be20f64` engine availability research → `674c0c2` TTS
  slate + Kokoro deferral → `9ddc8b8` speak/synthesize split → `68ef6ce`
  mic-only capture → `6167499` format policy → `bfb0e21` language policy →
  `af11e0c` BRIEF + IMPLEMENTATION → this handover.

## How to run

```bash
cd /mnt/shared/Source/listen-n-speak
python3 -m venv .venv && .venv/bin/pip install -e '.[stt,tts]'
.venv/bin/listen-n-speak    # stdio MCP server
```

**Not runnable yet — no source exists.** `IMPLEMENTATION.md` phases 1–8
define the order; each phase ends with green tests + a commit.

## Key files (spec of record)

- `BRIEF.md` — requirements (every user answer formalized)
- `IMPLEMENTATION.md` — module layout, env-var table (provisional defaults
  marked for benchmark override), dialog/subprocess/IPC design, phases
- `README.md` — user-facing surface; OMP register recipe (`"timeout":
  600000` for the full variant — human-paced dialog; OMP default is 30 s)
- `CONTEXT.md` — vocabulary: audio, transcript, utterance, transcription,
  synthesis, engine, voice, playback, dialog, dismissal
- `research/engine-availability.md` — wheel + pacman facts (2026-10-22)
- `scripts/download-kokoro-model.sh` — deferred-engine weights fetch
  (out-of-VM use only)

## Known issues / notes

- **Prerequisites for implementation**: `pacman -S tk` (dialog GUI),
  `pacman -S espeak-ng` (zero-dep TTS engine), `GROQ_API_KEY` at benchmark
  time.
- **Kokoro is deferred by user decision** — no adapter in v1; its weights
  are only fetched by `scripts/download-kokoro-model.sh` and evaluated
  outside this VM.
- **Provisional defaults** (`LISTEN_N_SPEAK_STT_ENGINE=faster-whisper`,
  `LISTEN_N_SPEAK_TTS_ENGINE=piper`) are placeholders until the benchmark
  protocol (README "Benchmarks") runs — defaults are set by evidence, and
  env always wins.
- `listen` calls are human-paced: the OMP registration needs
  `"timeout": 600000` or the harness kills a normal conversation's dialog.
- README "about" line and the GitHub repo description must stay in sync
  (same discipline as look-n-see).

## Open items / next steps

- **Implement phases 1–8** (`IMPLEMENTATION.md`): scaffold → audio
  normalization → STT → TTS → dialog → variants/docs sync → benchmarks →
  live smoke + OMP registration.
- **Benchmarks** decide engine defaults: STT batch (WER / latency / cost),
  dialog (real-time factor / partial latency / silence reliability), TTS
  (latency / size / user listening ranking — the user is the listener).
  Record verdicts in README.
- **Release & packaging**: deferred to post-v1; mirror look-n-see (CI,
  tag-triggered GitHub release, PyPI trusted publishing); `LICENSE` choice
  pending user decision.
