# listen-n-speak

A lightweight [MCP](https://modelcontextprotocol.io) server that gives agents
**ears** and a **mouth**: **transcribe** turns audio into text (STT), **speak**
turns text into audio the human can hear (TTS). Fourth in the collection —
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
own. listen-n-speak closes that gap with two verbs:

- **transcribe** — hand it audio (a user's voice memo, a recording, a call
  excerpt) and get back text the calling model can act on.
- **speak** — hand it text and the host says it out loud for the human present
  (and/or returns an audio file).

Both directions are engine-pluggable, the same pattern as look-n-see's OCR
engines: one engine per call, an env-configured default, a fallback chain on
failure. Local engines work offline; cloud engines degrade to clear errors
without keys.

## How an agent uses this from a harness

The calling model only ever sees the tool descriptions, so those descriptions
are the contract — they must teach the model the input triple (path / data URI
/ URL), the fact that it cannot hear playback (playback is for the human
present), and that results arrive as JSON, not prose. Harness realities that
shape the surface:

- OMP's default MCP request timeout is 30 s (look-n-see raises it to 120 s).
  No tool call may block for minutes; in-call mic recording needs a hard cap.
- Tools are one-shot request/response. No streaming, no sessions.
- Return file paths and metadata, never base64 audio blobs — audio in context
  is a pure token tax.

## Draft tool surface

| Tool | Params | Returns |
| --- | --- | --- |
| `transcribe` | `audio` (required: path / data URI / URL), `engine`?, `language`?, `model`? | `{"text", "language", "duration_s", "engine"}` |
| `speak` | `text` (required), `engine`?, `voice`?, `play`? | `{"file", "played", "duration_s", "engine", "voice"}` |

- `transcribe` normalizes input exactly like look-n-see normalizes images,
  then probes via `ffprobe` and converts through `ffmpeg` to one canonical
  form (16 kHz mono) before handing to an engine.
- `speak` synthesizes to a file under a configurable output dir, then plays it
  through the host audio sink when asked. Playback is best-effort: no sink →
  clear error, file still returned.
- `listen` is the reserved name for a mic-capture tool if one is added (open
  question 1) — never reused for anything else.
- Every tool returns structured output the calling model can act on (JSON
  where it matters, not prose-only) — house rule.

## Draft engines

| Direction | Engine | How | Needs |
| --- | --- | --- | --- |
| STT | local faster-whisper | CTranslate2, CPU; models cached under XDG cache | `[stt]` extra; Python 3.14 wheel support to verify |
| STT | cloud Groq | OpenAI-compatible `/audio/transcriptions`, `whisper-large-v3-turbo` | `GROQ_API_KEY` |
| TTS | local Piper | piper-tts + onnxruntime, per-language voice files | `[tts]` extra; voice download on first use |
| TTS | cloud Edge TTS | free Microsoft neural voices, no key, unofficial | network |
| TTS | espeak-ng | system binary, robotic, zero deps | pacman install |

Selection per call via `engine=`, default via env, fallback chain after
failure — identical semantics to look-n-see's OCR dispatcher.

## Configuration (draft)

| Variable | Default | Purpose |
| --- | --- | --- |
| `LISTEN_N_SPEAK_STT_ENGINE` | cloud default | default STT engine |
| `LISTEN_N_SPEAK_TTS_ENGINE` | local default | default TTS engine |
| `LISTEN_N_SPEAK_STT_FALLBACKS` | engine-dependent | fallback chain tried after the default fails |
| `LISTEN_N_SPEAK_TTS_FALLBACKS` | engine-dependent | same, for synthesis |
| `LISTEN_N_SPEAK_OUTPUT_DIR` | XDG cache or tmp | where synthesized files land |
| `LISTEN_N_SPEAK_INPUT` | system default | audio capture source (if mic capture is added) |

Full set finalized after the open questions are answered.

## Install

Collection parity: Python 3.10+, venv, `pip install -e .`, console script
`listen-n-speak`, stdio transport.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .

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
      "timeout": 120000
    }
  }
}
```

## Non-goals (draft)

- No streaming/websocket transport, no VAD turn detection, no barge-in — the
  MCP surface here is one-shot request/response.
- No diarization, no word-level timestamps in v1 (engines may offer them; the
  tool schema does not expose them yet).
- No duplex real-time voice loop — that is a harness/skill concern; this
  server stays one-shot: audio in → text, text → audio.
- No speech translation, no audio-conversion tool surface (ffmpeg exists on
  the host; agents can be told to use it directly).

## Open design questions (gating the spec)

1. **STT input** — file/URI/URL only, or also a mic-capture tool on the host
   (capped duration), or a start/stop recording pair for long dictation?
2. **STT default engine** — cloud-first (Groq), offline-first
   (faster-whisper), or pluggable with cloud default?
3. **TTS default engine** — Piper (offline), Kokoro (quality), Edge TTS
   (no-key cloud), cloud API (keyed), or espeak-ng (zero-dep fallback)?
4. **`speak` delivery** — synthesize + play, synthesize-only, or both tools?
5. **Capture source** — host mic, monitor (what the machine plays), both?
6. **Formats** — WAV-only policy, or WAV default + optional mp3/ogg via ffmpeg?
7. **Language policy** — English-only catalog in v1, or multilingual param
   surface from day one?
8. **Non-goals** — confirm the list above as v1 non-goals.
