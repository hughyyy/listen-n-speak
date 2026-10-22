"""MCPServer exposing the speech I/O tools."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import config as config_mod
from .audio import AudioInputError, prepare
from .dialog import ipc
from .stt import Dispatcher as SttDispatcher, SttError
from .tts import Dispatcher as TtsDispatcher, TtsError, play_file


def create_server(
    cfg: config_mod.Config | None = None,
    stt: SttDispatcher | None = None,
    tts: TtsDispatcher | None = None,
) -> MCPServer:
    cfg = cfg or config_mod.load_config()
    stt = stt or SttDispatcher(cfg)
    tts = tts or TtsDispatcher(cfg)
    mcp = MCPServer(name="listen-n-speak")

    # Variant gates: tools/list advertises exactly what is registered, which
    # is what MCP clients display. SPEAK_ENABLED covers both speech-output
    # tools (speak and synthesize); LISTEN_ENABLED gates the dialog.
    if cfg.transcribe_enabled:
        _register_transcribe(mcp, stt)
    if cfg.speak_enabled:
        _register_speak(mcp, cfg, tts)
        _register_synthesize(mcp, tts)
    if cfg.listen_enabled:
        _register_listen(mcp, cfg)
    return mcp


def _register_transcribe(mcp: MCPServer, stt: SttDispatcher) -> None:
    @mcp.tool()
    def transcribe(
        audio: str,
        engine: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ) -> str:
        """Transcribe an audio file to text (speech-to-text).

        Pass the audio as a file path on disk, a base64 `data:` URI, or an
        http(s) URL; any format ffmpeg can decode is accepted. Returns JSON:
        {"text", "language", "duration_s", "engine"}. On failure returns
        {"error": "<reason>"}.

        Args:
            audio: File path, base64 data URI, or http(s) URL of the audio.
            engine: `faster-whisper` (local, offline) or `groq` (cloud).
                Omitted -> the server default, with fallbacks.
            language: ISO language hint such as `en`; omitted -> auto-detect.
            model: Engine-specific model override (whisper tier or Groq id).
        """
        try:
            workdir = Path(tempfile.mkdtemp(prefix="lns-transcribe-"))
            wav, duration = prepare(audio, workdir)
            result = stt.transcribe(
                wav, duration, engine=engine, language=language, model=model
            )
        except (AudioInputError, SttError) as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(result, ensure_ascii=False)


def _register_speak(mcp: MCPServer, cfg: config_mod.Config, tts: TtsDispatcher) -> None:
    @mcp.tool()
    def speak(
        text: str,
        engine: str | None = None,
        voice: str | None = None,
        format: str | None = None,
    ) -> str:
        """Synthesize text and play it aloud on the host's speakers.

        Use this to say something to the human at the machine: you cannot
        hear the audio yourself, and the call blocks until playback finishes
        (consecutive utterances stay in order). Returns JSON: {"file",
        "played", "duration_s", "engine", "voice"} plus `playback_error` when
        the host could not play it. The file is written either way; use
        `synthesize` when you only need a file. On failure returns
        {"error": "<reason>"}.

        Args:
            text: What to say.
            engine: `piper` (local), `edge` (cloud, no key), `openai`
                (compatible `/audio/speech` endpoint), or `espeak`.
                Omitted -> the server default, with fallbacks.
            voice: Engine-specific voice id or Piper voice file name.
            format: Output format: `wav` (default), `mp3`, `ogg`, `flac`.
        """
        try:
            result = tts.synthesize(text, engine=engine, voice=voice, fmt=format)
        except TtsError as exc:
            return json.dumps({"error": str(exc)})
        played, playback_error = play_file(Path(result["file"]))
        result["played"] = played
        if playback_error:
            result["playback_error"] = playback_error
        return json.dumps(result, ensure_ascii=False)


def _register_synthesize(mcp: MCPServer, tts: TtsDispatcher) -> None:
    @mcp.tool()
    def synthesize(
        text: str,
        engine: str | None = None,
        voice: str | None = None,
        format: str | None = None,
    ) -> str:
        """Synthesize text to an audio file without playing it.

        Use this to produce an audio artifact (a voice memo, a clip to attach
        or move elsewhere). No audio sink is required. Returns JSON: {"file",
        "duration_s", "engine", "voice"}. On failure returns
        {"error": "<reason>"}.

        Args:
            text: What to say.
            engine: `piper` (local), `edge` (cloud, no key), `openai`
                (compatible `/audio/speech` endpoint), or `espeak`.
                Omitted -> the server default, with fallbacks.
            voice: Engine-specific voice id or Piper voice file name.
            format: Output format: `wav` (default), `mp3`, `ogg`, `flac`.
        """
        try:
            result = tts.synthesize(text, engine=engine, voice=voice, fmt=format)
        except TtsError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(result, ensure_ascii=False)


def _register_listen(mcp: MCPServer, cfg: config_mod.Config) -> None:
    @mcp.tool()
    def listen(
        prompt: str,
        silence_s: float | None = None,
        max_s: float | None = None,
        engine: str | None = None,
    ) -> str:
        """Ask the human at the machine a question and capture their spoken answer.

        Opens a small dialog showing `prompt`. Recording starts only when the
        human clicks the red record button, live-transcribes their speech,
        and stops after a few seconds of silence. The human then clicks Send
        (transcript returns to you) or closes the window (dismissal). This
        call blocks until one of those happens — it is human-paced, so expect
        long waits. Returns JSON: {"text", "audio", "duration_s", "engine"};
        a dismissal returns {"text": null, "reason": "dismissed"}; a failure
        returns {"error": "<reason>"}. The audio file is kept so you can
        re-transcribe it with a different engine.

        Args:
            prompt: The question to display to the human. Required.
            silence_s: Seconds of silence before recording auto-stops
                (default 5).
            max_s: Hard cap on recording length in seconds (default 300).
            engine: STT engine override for the final transcript.
        """
        limit = max_s if max_s is not None else cfg.max_s
        silence = silence_s if silence_s is not None else cfg.silence_s
        out_path = Path(tempfile.mkdtemp(prefix="lns-listen-")) / "result.json"
        command = [
            sys.executable, "-m", "listen_n_speak.dialog.app",
            "--prompt", prompt,
            "--out", str(out_path),
            "--silence-s", f"{silence}",
            "--max-s", f"{limit}",
        ]
        if engine:
            command += ["--engine", engine]
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=limit + 30
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {"error": f"listen dialog timed out after {limit + 30:.0f}s"}
            )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            message = detail[-1] if detail else f"exit {proc.returncode}"
            return json.dumps({"error": f"listen dialog failed: {message[:300]}"})
        payload = ipc.read_result(out_path)
        if payload is None:
            return json.dumps({"error": "listen dialog produced no result"})
        return json.dumps(payload, ensure_ascii=False)


def main() -> None:
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
