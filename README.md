# listen-n-speak

A lightweight [MCP](https://modelcontextprotocol.io) server that gives agents
**ears** and a **mouth**: **transcribe** turns audio into text (STT), **speak**
turns text into audio the human can hear (TTS), and **listen** opens a small
dialog where the human answers the agent by voice. Fourth in the collection —
[look-n-see](../look-n-see) (vision/OCR), [scrape-n-search](../scrape-n-search)
(web), [store-n-recall](../store-n-recall) (project memory), listen-n-speak
(speech).

> **Status: planned** — design captured, implementation not started. This
> README is the draft spec; the open design questions at the bottom gate the
> final surface. When implementation starts, `BRIEF.md` (requirements) and
> `IMPLEMENTATION.md` (design + release plan) are added, like look-n-see.

## The idea

An agent inside a harness receives audio the way it receives images — a file
path, a base64 `data:` URI, or a URL — and has no microphone or speaker of its
own. listen-n-speak closes that gap with three verbs:

- **transcribe** — hand it audio (a user's voice memo, a recording, a call
  excerpt) and get back text the calling model can act on.
- **speak** — hand it text and the host says it out loud for the human present
  (and/or returns an audio file).
- **listen** — open a dialog on the host's display; the human speaks an answer,
  and the agent receives the transcript. The agent supplies a text prompt that
  is displayed in the window, so the human always knows what is being asked.

All three are engine-pluggable, the same pattern as look-n-see's OCR engines:
one engine per call, an env-configured default, a fallback chain on failure.
Local engines work offline; cloud engines degrade to clear errors without keys.

## How an agent uses this from a harness

The calling model only ever sees the tool descriptions, so those descriptions
are the contract — they must teach the model the input triple (path / data URI
/ URL), that it cannot hear playback (playback is for the human present), and
that results arrive as JSON, not prose. Harness realities that shape the
surface:

- OMP's default MCP request timeout is 30 s (look-n-see raises it to 120 s).
  `transcribe`/`speak` stay fast; `listen` is human-paced and needs a long
  registration timeout (see the variant table).
- Tools are one-shot request/response. No streaming, no sessions.
- Return file paths and metadata, never base64 audio blobs — audio in context
  is a pure token tax.

## The `listen` dialog

A small window on the host display (X11 today; tkinter, stdlib — one-time
`pacman -S tk` fixes the missing `libtk8.6.so`). The dialog process is spawned
per call so a GUI crash never takes down the server, and the server stays
stateless.

1. The agent calls `listen` with a required `prompt` — the question to show.
2. The window shows the prompt. **Recording does not start until the human
   clicks the red record button.**
3. While recording, words are live-transcribed and typed into a response box
   as they arrive (when a streaming-capable local engine is present).
4. Recording auto-stops after **5 seconds of silence** (`silence_s` param,
   default 5; absolute cap `max_s`, default 300).
5. The human then either **Clear** (empty the box, record again) or **Send**
   (return the transcript to the calling agent). Closing the window counts as
   a dismissal.

Graceful degradation: with no local streaming engine the dialog records with
silence detection via ffmpeg levels and batch-transcribes at the end (cloud
engines usable; live typing becomes a "recording…" state); with no capture
device it errors clearly. The result carries the transcript, the saved audio
path, and duration — the audio is kept so the agent can re-transcribe with a
different engine if needed.

## Release variants

One package; the tool surface is selected at startup by env flags
(`tools/list` advertises exactly what is registered) — same mechanism as
look-n-see:

| Variant | Install | Env |
| --- | --- | --- |
| **Full (default)** | `pip install 'listen-n-speak[stt,tts]'` | *(defaults)* |
| **Core (file-based only)** | `pip install listen-n-speak` | `LISTEN_ENABLED=0` — no dialog, no capture device, no GUI deps |
| STT only | `pip install 'listen-n-speak[stt]'` | `SPEAK_ENABLED=0` |
| TTS only | `pip install 'listen-n-speak[tts]'` | `TRANSCRIBE_ENABLED=0` |

`LISTEN_ENABLED=0` is the "pure (A)" configuration the collection starts with;
the extras and the dialog are additive. OMP registration for the full variant
needs `"timeout": 600000` (human-paced dialog); core runs fine at defaults.

## Draft tool surface

| Tool | Params | Returns |
| --- | --- | --- |
| `transcribe` | `audio` (required: path / data URI / URL), `engine`?, `language`?, `model`? | `{"text", "language", "duration_s", "engine"}` |
| `speak` | `text` (required), `engine`?, `voice`? | `{"file", "played", "duration_s", "engine", "voice"}` — synthesis + playback; blocks until finished |
| `synthesize` | `text` (required), `engine`?, `voice`? | `{"file", "duration_s", "engine", "voice"}` — synthesis without playback; no sink required |
| `listen` | `prompt` (required), `silence_s`? (default 5), `max_s`? (default 300), `engine`? | `{"text", "audio", "duration_s", "engine"}`; dismissal returns `{"text": null, "reason": "dismissed"}` |

- `transcribe` normalizes input exactly like look-n-see normalizes images,
  then probes via `ffprobe` and converts through `ffmpeg` to one canonical
  form (16 kHz mono) before handing to an engine.
- `speak` synthesizes to a file under a configurable output dir, then plays
  it through the host audio sink; the call blocks until playback finishes so
  consecutive utterances stay ordered. Playback is best-effort: no sink →
  clear error, file still returned.
- `synthesize` is the same synthesis without playback — no sink required, so
  it works on every variant including headless hosts.
- Every tool returns structured output the calling model can act on (JSON
  where it matters, not prose-only) — house rule.

## Draft engines

| Direction | Engine | How | Needs |
| --- | --- | --- | --- |
| STT | local faster-whisper | CTranslate2, CPU; models cached under XDG cache; Silero VAD for the dialog's silence stop; whisper.cpp (pacman 1.9.5) is the alternative local engine | `[stt]` extra; cp314 wheels verified — see `research/engine-availability.md` |
| STT | cloud Groq | OpenAI-compatible `/audio/transcriptions`, `whisper-large-v3-turbo` | `GROQ_API_KEY` |
| TTS | local Piper | piper-tts + onnxruntime, per-language voice files | `[tts]` extra; voice download on first use; cp314 wheels verified |
| TTS | cloud Edge TTS | free Microsoft neural voices, no key, unofficial | network |
| TTS | cloud OpenAI-compatible | generic `/audio/speech` adapter — OpenAI, Groq PlayAI, or any compatible endpoint | `LISTEN_N_SPEAK_TTS_BASE_URL` + `LISTEN_N_SPEAK_TTS_API_KEY` |
| TTS | espeak-ng | system binary, robotic, zero deps | pacman install |
| TTS | local Kokoro (deferred) | **not implemented in v1** — weights via `scripts/download-kokoro-model.sh`, to be evaluated **outside this VM** (kokoro-onnx requires Python <3.14, cap confirmed on PyPI; this VM has only 3.14) | future candidate |

Selection per call via `engine=`, default via env, fallback chain after
failure — identical semantics to look-n-see's OCR dispatcher. Live typing in
the `listen` dialog requires a streaming-capable local engine (faster-whisper
chunked transcription); cloud engines only serve batch transcription. Defaults
are set from benchmark evidence, not assertion (see Benchmarks).

## Benchmarks

Engine defaults are decided by evidence, not assertion — the same discipline
as look-n-see's vision-model sweep. `benchmarks/` holds the scripts and dated
results; `research/` holds tradeoff notes. Both paths are benchmarked before
they are relied on:

- **STT batch** (`transcribe`): latency, accuracy (WER against reference
  transcripts), cost per call — local (faster-whisper, whisper.cpp as
  alternative) vs cloud (Groq), same recordings through both.
- **STT dialog** (`listen`): chunked-transcription real-time factor on CPU,
  partial-transcript latency (how quickly words appear), silence-stop
  reliability at the 5 s threshold.
- **TTS**: synthesis latency, output size, and a human listening ranking on a
  fixed set of sample texts (announcement, technical sentence with code-like
  tokens, paragraph). Kokoro is benchmarked only after its weights are
  evaluated outside this VM (see `scripts/download-kokoro-model.sh`).

Results land as a summary table in this README. The benchmark suite is
manual/scripted and is not part of the offline unittest suite.

## Configuration (draft)

| Variable | Default | Purpose |
| --- | --- | --- |
| `LISTEN_N_SPEAK_STT_ENGINE` | — | default STT engine |
| `LISTEN_N_SPEAK_TTS_ENGINE` | — | default TTS engine |
| `LISTEN_N_SPEAK_STT_FALLBACKS` | engine-dependent | fallback chain tried after the default fails |
| `LISTEN_N_SPEAK_TTS_FALLBACKS` | engine-dependent | same, for synthesis |
| `LISTEN_N_SPEAK_OUTPUT_DIR` | XDG cache or tmp | where synthesized/captured files land |
| `LISTEN_N_SPEAK_INPUT` | system default | capture source for the dialog |
| `TRANSCRIBE_ENABLED` / `SPEAK_ENABLED` / `LISTEN_ENABLED` | `1` | tool registration gates (release variants) |

Full set finalized after the open questions are answered.

## Install

Collection parity: Python 3.10+, venv, `pip install -e .`, console script
`listen-n-speak`, stdio transport.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[stt,tts]'

# run as a stdio MCP server
.venv/bin/listen-n-speak
```

### Register with Oh My Pi

Add to `~/.omp/agent/mcp.json` (adjust paths; `!` env indirection resolves
tokens from OMP's credential store — same recipe as look-n-see):

```json
{
  "mcpServers": {
    "listen-n-speak": {
      "type": "stdio",
      "command": "/absolute/path/to/listen-n-speak/.venv/bin/listen-n-speak",
      "timeout": 600000
    }
  }
}
```

## Non-goals

- No protocol-level streaming (websocket/SSE), no barge-in, no server-side
  session state — MCP here stays one-shot request/response. The only VAD-like
  feature is the dialog's silence auto-stop, local to the dialog process.
- No diarization, no word-level timestamps in v1 (engines may offer them; the
  tool schema does not expose them yet).
- No duplex real-time voice loop — the dialog is the human-in-the-loop answer,
  and it is still one-shot from the agent's side.
- No speech translation, no audio-conversion tool surface (ffmpeg exists on
  the host; agents can be told to use it directly).

## Open design questions (gating the spec)

1. **`speak` delivery** — synthesize + play, synthesize-only, or both tools?
2. **Capture source** — host mic, monitor (what the machine plays), both?
3. **Formats** — WAV-only policy, or WAV default + optional mp3/ogg via ffmpeg?
4. **Language policy** — English-only catalog in v1, or multilingual param
   surface from day one?
5. **Non-goals** — confirm the list above as v1 non-goals.
