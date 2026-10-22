"""Text-to-speech dispatcher, engines, and host playback."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Callable

import httpx

from . import audio
from .config import (
    AUDIO_FORMATS,
    DEFAULT_EDGE_VOICE,
    DEFAULT_PIPER_VOICE,
    Config,
)

PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
HTTP_TIMEOUT = 120.0


class TtsError(RuntimeError):
    """User-facing synthesis/playback failure."""


def _output_path(cfg: Config, engine: str, fmt: str) -> Path:
    directory = Path(cfg.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{engine}-{uuid.uuid4().hex[:12]}.{fmt}"


def _ensure_piper_voice(cfg: Config, voice_id: str) -> Path:
    """Path to a Piper voice .onnx, downloading it (and its config) on first use."""
    base = Path(cfg.models_dir) / "piper"
    base.mkdir(parents=True, exist_ok=True)
    model = base / f"{voice_id}.onnx"
    conf = base / f"{voice_id}.onnx.json"
    if model.is_file() and conf.is_file():
        return model

    try:
        language, name, quality = voice_id.split("-", 2)
    except ValueError as exc:
        raise TtsError(
            f"piper voice id {voice_id!r} is not of the form "
            "<lang>-<name>-<quality>, e.g. en_US-lessac-medium"
        ) from exc
    lang_code = language.split("_")[0]
    url = f"{PIPER_BASE}/{lang_code}/{language}/{name}/{quality}/{voice_id}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            for suffix, dest in ((".onnx", model), (".onnx.json", conf)):
                with client.stream("GET", url + suffix) as response:
                    response.raise_for_status()
                    tmp = dest.with_name(dest.name + ".part")
                    with open(tmp, "wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                    tmp.replace(dest)
    except httpx.HTTPError as exc:
        raise TtsError(
            f"cannot download piper voice {voice_id!r}: {exc.__class__.__name__}"
        ) from exc
    return model


def _piper(cfg: Config, text: str, voice: str | None, fmt: str) -> tuple[Path, str]:
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise TtsError(
            "engine `piper` is not installed — `pip install 'listen-n-speak[tts]'`"
        ) from exc

    voice_id = voice or cfg.tts_voice or DEFAULT_PIPER_VOICE
    model_path = _ensure_piper_voice(cfg, voice_id)
    out = _output_path(cfg, "piper", "wav")
    try:
        piper_voice = PiperVoice.load(str(model_path))
        with wave.open(str(out), "wb") as wav_file:
            piper_voice.synthesize_wav(text, wav_file)
    except Exception as exc:
        raise TtsError(f"piper synthesis failed: {exc}") from exc
    return out, "wav"


def _run_async(coro) -> None:
    """Run a coroutine from sync code, even if this thread already has a loop."""
    try:
        asyncio.run(coro)
    except RuntimeError:
        import threading

        outcome: dict[str, BaseException | None] = {"error": None}

        def runner() -> None:
            try:
                asyncio.run(coro)
            except BaseException as exc:  # surfaced below
                outcome["error"] = exc

        thread = threading.Thread(target=runner)
        thread.start()
        thread.join()
        if outcome["error"] is not None:
            raise outcome["error"]


def _edge(cfg: Config, text: str, voice: str | None, fmt: str) -> tuple[Path, str]:
    try:
        import edge_tts
    except ImportError as exc:
        raise TtsError(
            "engine `edge` is not installed — `pip install 'listen-n-speak[tts]'`"
        ) from exc

    voice_id = voice or cfg.tts_voice or DEFAULT_EDGE_VOICE
    out = _output_path(cfg, "edge", "mp3")
    try:
        _run_async(edge_tts.Communicate(text, voice_id).save(str(out)))
    except Exception as exc:
        raise TtsError(f"edge synthesis failed: {exc}") from exc
    if not out.is_file():
        raise TtsError("edge synthesis produced no audio")
    return out, "mp3"


def _openai(cfg: Config, text: str, voice: str | None, fmt: str) -> tuple[Path, str]:
    if not cfg.tts_base_url or not cfg.tts_api_key:
        raise TtsError(
            "engine `openai` needs LISTEN_N_SPEAK_TTS_BASE_URL and "
            "LISTEN_N_SPEAK_TTS_API_KEY in the environment"
        )
    out = _output_path(cfg, "openai", fmt)
    payload = {
        "model": cfg.tts_model,
        "input": text,
        "voice": voice or cfg.tts_voice or "alloy",
        "response_format": fmt,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                f"{cfg.tts_base_url.rstrip('/')}/audio/speech",
                headers={"Authorization": f"Bearer {cfg.tts_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            out.write_bytes(response.content)
    except httpx.HTTPStatusError as exc:
        raise TtsError(
            f"speech API failed: HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise TtsError(f"speech API failed: {exc.__class__.__name__}: {exc}") from exc
    return out, fmt


def _espeak(cfg: Config, text: str, voice: str | None, fmt: str) -> tuple[Path, str]:
    exe = shutil.which("espeak-ng")
    if not exe:
        raise TtsError(
            "engine `espeak` needs the espeak-ng binary — install it (pacman -S espeak-ng)"
        )
    out = _output_path(cfg, "espeak", "wav")
    voice_id = voice or cfg.tts_voice or "en"
    proc = subprocess.run(
        [exe, "-w", str(out), "-v", voice_id, text], capture_output=True, text=True
    )
    if proc.returncode != 0 or not out.is_file():
        detail = (proc.stderr or proc.stdout).strip()[:300] or f"espeak-ng exited {proc.returncode}"
        raise TtsError(f"espeak-ng synthesis failed: {detail}")
    return out, "wav"


ENGINES: dict[str, Callable[[Config, str, str | None, str], tuple[Path, str]]] = {
    "piper": _piper,
    "edge": _edge,
    "openai": _openai,
    "espeak": _espeak,
}


class Dispatcher:
    """Chooses an engine, walks fallbacks, and normalizes the output format."""

    def __init__(
        self,
        cfg: Config,
        engines: dict[str, Callable[[Config, str, str | None, str], tuple[Path, str]]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.engines = engines or ENGINES

    def chain(self, engine: str | None) -> list[str]:
        primary = (engine or self.cfg.tts_engine).strip().lower()
        if engine:
            return [primary]
        return [primary, *self.cfg.tts_fallbacks]

    def synthesize(
        self,
        text: str,
        engine: str | None = None,
        voice: str | None = None,
        fmt: str | None = None,
    ) -> dict:
        if not text or not text.strip():
            raise TtsError("text is empty — nothing to synthesize")
        fmt = (fmt or "wav").strip().lower()
        if fmt not in AUDIO_FORMATS:
            raise TtsError(
                f"unsupported format {fmt!r} (expected one of: {', '.join(AUDIO_FORMATS)})"
            )

        errors: list[str] = []
        for name in self.chain(engine):
            fn = self.engines.get(name)
            if fn is None:
                known = ", ".join(sorted(self.engines))
                errors.append(f"{name}: unknown TTS engine (known: {known})")
                continue
            try:
                path, native = fn(self.cfg, text, voice, fmt)
            except TtsError as exc:
                errors.append(f"{name}: {exc}")
                continue
            if native != fmt:
                try:
                    path = audio.transcode(path, _output_path(self.cfg, name, fmt), fmt)
                except audio.AudioInputError as exc:
                    errors.append(f"{name}: {exc}")
                    continue
            try:
                duration = audio.probe_duration(path)
            except audio.AudioInputError as exc:
                errors.append(f"{name}: {exc}")
                continue
            return {
                "file": str(path),
                "duration_s": round(duration, 2),
                "engine": name,
                "voice": voice or self.cfg.tts_voice or _default_voice(name),
            }
        raise TtsError("; ".join(errors) if errors else "no TTS engine available")


def _default_voice(engine: str) -> str | None:
    return {
        "piper": DEFAULT_PIPER_VOICE,
        "edge": DEFAULT_EDGE_VOICE,
    }.get(engine)


def play_file(path: Path) -> tuple[bool, str | None]:
    """Play an audio file on the host sink (blocking). Best-effort."""
    for exe in ("aplay", "ffplay"):
        found = shutil.which(exe)
        if not found:
            continue
        args = (
            [found, "-q", str(path)]
            if exe == "aplay"
            else [found, "-nodisp", "-autoexit", "-loglevel", "error", str(path)]
        )
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode == 0:
            return True, None
        detail = (proc.stderr or proc.stdout).strip()[:300] or f"{exe} exited {proc.returncode}"
        return False, detail
    return False, "no playback binary found (aplay/ffplay) — file still written"
