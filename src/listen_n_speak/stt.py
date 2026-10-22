"""Speech-to-text dispatcher and engines.

Same semantics as look-n-see's OCR dispatcher: an explicit `engine=` is
honoured or fails loudly; an omitted engine starts at the env default and
walks `LISTEN_N_SPEAK_STT_FALLBACKS` on hard failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx

from .config import Config

GROQ_TIMEOUT = 120.0

# WhisperModel instances are expensive to load; one per model tier per process.
_MODEL_CACHE: dict[str, object] = {}


class SttError(RuntimeError):
    """User-facing transcription failure."""


def _read_wav_samples(wav: Path):
    """Read a canonical 16 kHz mono WAV into float32 samples (-1..1).

    faster-whisper decodes file paths through PyAV, whose `av.open` signature
    changed in PyAV 14+; passing a numpy array skips that decode path
    entirely. Our normalizer guarantees the 16 kHz mono format.
    """
    import wave

    import numpy as np

    try:
        with wave.open(str(wav), "rb") as handle:
            if handle.getnchannels() != 1 or handle.getframerate() != 16000:
                raise SttError(
                    "expected 16 kHz mono WAV input (audio normalizer guarantees this)"
                )
            frames = handle.readframes(handle.getnframes())
    except (OSError, wave.Error) as exc:
        raise SttError(f"cannot read WAV input: {exc}") from exc
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _faster_whisper(
    cfg: Config, wav: Path, language: str | None, model: str | None
) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SttError(
            "engine `faster-whisper` is not installed — `pip install 'listen-n-speak[stt]'`"
        ) from exc

    name = model or cfg.stt_model
    if name not in _MODEL_CACHE:
        try:
            _MODEL_CACHE[name] = WhisperModel(name, device="cpu", compute_type="int8")
        except Exception as exc:
            raise SttError(f"cannot load whisper model {name!r}: {exc}") from exc
    whisper = _MODEL_CACHE[name]

    try:
        samples = _read_wav_samples(wav)
        segments, info = whisper.transcribe(
            samples, language=language or None, vad_filter=False
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except SttError:
        raise
    except Exception as exc:
        raise SttError(f"faster-whisper failed: {exc}") from exc

    return {
        "text": text,
        "language": getattr(info, "language", None) or (language or "unknown"),
        "engine": "faster-whisper",
    }


def _groq(cfg: Config, wav: Path, language: str | None, model: str | None) -> dict:
    if not cfg.groq_api_key:
        raise SttError("engine `groq` needs GROQ_API_KEY in the environment")

    data = {"model": model or "whisper-large-v3-turbo", "response_format": "verbose_json"}
    if language:
        data["language"] = language
    try:
        with httpx.Client(timeout=GROQ_TIMEOUT) as client:
            with open(wav, "rb") as handle:
                response = client.post(
                    f"{cfg.groq_base_url.rstrip('/')}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {cfg.groq_api_key}"},
                    files={"file": (Path(wav).name, handle, "audio/wav")},
                    data=data,
                )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise SttError(
            f"groq transcription failed: HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SttError(f"groq transcription failed: {exc.__class__.__name__}: {exc}") from exc

    return {
        "text": (payload.get("text") or "").strip(),
        "language": payload.get("language") or (language or "unknown"),
        "engine": "groq",
    }


ENGINES: dict[str, Callable[[Config, Path, str | None, str | None], dict]] = {
    "faster-whisper": _faster_whisper,
    "groq": _groq,
}


class Dispatcher:
    """Chooses an engine, walks fallbacks, and normalizes the result shape."""

    def __init__(
        self,
        cfg: Config,
        engines: dict[str, Callable[[Config, Path, str | None, str | None], dict]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.engines = engines or ENGINES

    def chain(self, engine: str | None) -> list[str]:
        """Engine chain: explicit request (no fallbacks) or default + fallbacks."""
        primary = (engine or self.cfg.stt_engine).strip().lower()
        if engine:
            return [primary]
        return [primary, *self.cfg.stt_fallbacks]

    def transcribe(
        self,
        wav: Path,
        duration: float,
        engine: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ) -> dict:
        errors: list[str] = []
        for name in self.chain(engine):
            fn = self.engines.get(name)
            if fn is None:
                known = ", ".join(sorted(self.engines))
                errors.append(f"{name}: unknown STT engine (known: {known})")
                continue
            try:
                result = fn(self.cfg, wav, language, model)
            except SttError as exc:
                errors.append(f"{name}: {exc}")
                continue
            result.setdefault("text", "")
            result["duration_s"] = round(duration, 2)
            return result
        raise SttError("; ".join(errors) if errors else "no STT engine available")
