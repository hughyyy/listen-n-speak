"""Environment-driven configuration with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

STT_ENGINES = ("faster-whisper", "groq")
TTS_ENGINES = ("piper", "edge", "openai", "espeak")
AUDIO_FORMATS = ("wav", "mp3", "ogg", "flac")

# Provisional defaults (see README "Benchmarks"): the benchmark protocol
# decides these; env always wins.
DEFAULT_STT_ENGINE = "faster-whisper"
DEFAULT_TTS_ENGINE = "piper"
DEFAULT_STT_FALLBACKS = ("groq",)
DEFAULT_TTS_FALLBACKS = ("edge", "espeak")
DEFAULT_WHISPER_MODEL = "base"
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
DEFAULT_EDGE_VOICE = "en-US-AriaNeural"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_GROQ_URL = "https://api.groq.com/openai/v1"


def cache_root() -> Path:
    """XDG cache root for this server (weights, generated audio)."""
    base = os.environ.get("XDG_CACHE_HOME")
    return Path(base) / "listen-n-speak" if base else Path.home() / ".cache" / "listen-n-speak"


@dataclass(frozen=True)
class Config:
    # STT
    stt_engine: str = DEFAULT_STT_ENGINE
    stt_model: str = DEFAULT_WHISPER_MODEL
    stt_fallbacks: tuple[str, ...] = DEFAULT_STT_FALLBACKS
    groq_api_key: str | None = None
    groq_base_url: str = DEFAULT_GROQ_URL
    # TTS
    tts_engine: str = DEFAULT_TTS_ENGINE
    tts_fallbacks: tuple[str, ...] = DEFAULT_TTS_FALLBACKS
    tts_voice: str | None = None
    tts_model: str = DEFAULT_TTS_MODEL
    tts_base_url: str | None = None
    tts_api_key: str | None = None
    # Paths and capture
    output_dir: Path = field(default_factory=lambda: cache_root() / "audio")
    models_dir: Path = field(default_factory=lambda: cache_root() / "models")
    input_device: str | None = None
    silence_s: float = 5.0
    max_s: float = 300.0
    # Tool-surface gates (release variants)
    transcribe_enabled: bool = True
    speak_enabled: bool = True
    listen_enabled: bool = True


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except ValueError:
        return default


def _parse_list(raw: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    parts = [p.strip().lower() for p in raw.replace(",", " ").split() if p.strip()]
    return tuple(parts)


def _parse_engine(raw: str | None, allowed: tuple[str, ...], default: str) -> str:
    engine = (raw or "").strip().lower()
    return engine if engine in allowed else default


def load_config() -> Config:
    return Config(
        stt_engine=_parse_engine(
            os.environ.get("LISTEN_N_SPEAK_STT_ENGINE"), STT_ENGINES, DEFAULT_STT_ENGINE
        ),
        stt_model=os.environ.get("LISTEN_N_SPEAK_STT_MODEL") or DEFAULT_WHISPER_MODEL,
        stt_fallbacks=_parse_list(
            os.environ.get("LISTEN_N_SPEAK_STT_FALLBACKS"), DEFAULT_STT_FALLBACKS
        ),
        groq_api_key=os.environ.get("GROQ_API_KEY") or None,
        groq_base_url=os.environ.get("GROQ_BASE_URL") or DEFAULT_GROQ_URL,
        tts_engine=_parse_engine(
            os.environ.get("LISTEN_N_SPEAK_TTS_ENGINE"), TTS_ENGINES, DEFAULT_TTS_ENGINE
        ),
        tts_fallbacks=_parse_list(
            os.environ.get("LISTEN_N_SPEAK_TTS_FALLBACKS"), DEFAULT_TTS_FALLBACKS
        ),
        tts_voice=os.environ.get("LISTEN_N_SPEAK_TTS_VOICE") or None,
        tts_model=os.environ.get("LISTEN_N_SPEAK_TTS_MODEL") or DEFAULT_TTS_MODEL,
        tts_base_url=os.environ.get("LISTEN_N_SPEAK_TTS_BASE_URL") or None,
        tts_api_key=os.environ.get("LISTEN_N_SPEAK_TTS_API_KEY") or None,
        output_dir=Path(
            os.environ.get("LISTEN_N_SPEAK_OUTPUT_DIR") or cache_root() / "audio"
        ),
        models_dir=Path(
            os.environ.get("LISTEN_N_SPEAK_MODELS_DIR") or cache_root() / "models"
        ),
        input_device=os.environ.get("LISTEN_N_SPEAK_INPUT") or None,
        silence_s=_env_float("LISTEN_N_SPEAK_SILENCE_S", 5.0),
        max_s=_env_float("LISTEN_N_SPEAK_MAX_S", 300.0),
        transcribe_enabled=_env_bool("TRANSCRIBE_ENABLED", True),
        speak_enabled=_env_bool("SPEAK_ENABLED", True),
        listen_enabled=_env_bool("LISTEN_ENABLED", True),
    )
