# listen-n-speak

A lightweight MCP server that gives agents ears and a mouth: transcription of audio into text, and synthesis of text into audio a human can hear.

## Language

### Artifacts

**Audio**:
The input to transcription, accepted three ways — a file path on disk, a base64 `data:` URI, or an `http(s)://` URL — and normalized server-side to one canonical form before an engine sees it.
_Avoid_: file (it may be a URI or URL), clip, recording (implies mic capture), media

**Transcript**:
The plain-text result of one transcription, plus metadata: detected language, audio duration, engine used.
_Avoid_: text (too generic), result, output

**Utterance**:
The audio file a synthesis call produces — the thing `speak` returns or plays. One utterance per call.
_Avoid_: audio file (ambiguous with input audio), speech, wav (format-specific)

### Directions

**Transcription**:
One pass of speech-to-text: audio in, a transcript out.
_Avoid_: STT (internal acronym), speech-to-text, recognition, ASR

**Synthesis**:
One pass of text-to-speech: text in, an utterance out.
_Avoid_: TTS (internal acronym), text-to-speech, generation, rendering

### Interaction

**Dialog**:
The small human-in-the-loop window `listen` opens on the host display: the agent's prompt, a red record button, a live-typed response box, Clear and Send. One dialog per listen call, run as a subprocess.
_Avoid_: prompt (the agent's text inside it), window (too generic), session

**Dismissal**:
Ending a dialog without sending — closing the window. Returns a structured not-an-error result (`{"text": null, "reason": "dismissed"}`).
_Avoid_: cancel (the agent has no cancel verb), abort

### Machinery

**Engine**:
A swappable implementation behind a transcription or synthesis call — a local library/binary or a cloud API. Selected per call via parameter; an env var names the default; failures walk a fallback chain.
_Avoid_: backend, provider, model (an engine has a model; it is not one)

**Voice**:
The persona a synthesis engine speaks with — a Piper voice file, an Edge voice name, or a cloud voice id. Engine-specific and not portable across engines.
_Avoid_: model, speaker, persona

**Playback**:
Sounding an utterance through the host's audio sink — best-effort, for the human present; agents never hear audio. `speak` includes playback; `synthesize` never does.
_Avoid_: playing (an agent action), output, stream
