"""Normalize audio inputs (file path, data URI, http(s) URL) to 16 kHz mono WAV."""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

import httpx

SAMPLE_RATE = 16000
MAX_AUDIO_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 5
_TRANSCODE_CODECS = {
    "wav": [],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "96k"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "4"],
    "flac": ["-c:a", "flac"],
}

_DATA_URI_RE = re.compile(r"^data:(?P<media>[^;,]*)(?P<params>[^,]*),(?P<data>.*)$", re.DOTALL)
_USERINFO_RE = re.compile(r"(://)[^/@\s]+@")


class AudioInputError(ValueError):
    """Raised when an audio input cannot be resolved or decoded."""


def _redact_url(url: str) -> str:
    """Mask embedded credentials (https://user:pass@...) in an echoed URL."""
    return _USERINFO_RE.sub(r"\1***@", url)


def _is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise AudioInputError(f"`{name}` not found on PATH — install ffmpeg (pacman -S ffmpeg)")
    return path


def _fetch_url(url: str, timeout: float = 120.0) -> bytes:
    """Fetch an http(s) URL, following only http(s) redirects, under a size cap."""
    current = url
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", current) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        location = resp.headers.get("location")
                        if not location:
                            raise AudioInputError(
                                f"redirect without a location header from {_redact_url(current)}"
                            )
                        current = urllib.parse.urljoin(current, location)
                        if not _is_http_url(current):
                            raise AudioInputError(
                                f"refusing non-http(s) redirect to {_redact_url(current)}"
                            )
                        continue
                    resp.raise_for_status()
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > MAX_AUDIO_BYTES:
                            raise AudioInputError(
                                f"audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MiB limit"
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.HTTPStatusError as exc:
                raise AudioInputError(
                    f"cannot fetch {_redact_url(current)}: HTTP {exc.response.status_code}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AudioInputError(
                    f"cannot fetch {_redact_url(current)}: {exc.__class__.__name__}"
                ) from exc
    raise AudioInputError(f"too many redirects fetching {_redact_url(url)}")


def load_audio(source: str, workdir: Path) -> Path:
    """Resolve path / data URI / URL to a local file (no transcoding yet)."""
    if not source or not source.strip():
        raise AudioInputError("empty audio source")
    source = source.strip()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if source.startswith("data:"):
        match = _DATA_URI_RE.match(source)
        if not match:
            raise AudioInputError("malformed data URI")
        if "base64" not in match.group("params"):
            raise AudioInputError("data URI must be base64-encoded")
        try:
            raw = base64.b64decode(match.group("data"), validate=True)
        except Exception as exc:  # binascii.Error et al.
            raise AudioInputError(f"invalid base64 audio payload: {exc}") from exc
        if len(raw) > MAX_AUDIO_BYTES:
            raise AudioInputError(
                f"audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MiB limit"
            )
        dest = workdir / "input.bin"
        dest.write_bytes(raw)
        return dest

    if _is_http_url(source):
        dest = workdir / "input.bin"
        dest.write_bytes(_fetch_url(source))
        return dest

    path = Path(source).expanduser()
    if not path.is_file():
        raise AudioInputError(f"audio file not found: {source}")
    return path


def to_wav(audio: Path, workdir: Path) -> Path:
    """Convert any decodable audio file to 16 kHz mono WAV."""
    ffmpeg = _require_binary("ffmpeg")
    dest = Path(workdir) / "audio.wav"
    proc = subprocess.run(
        [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(audio), "-ac", "1", "-ar", str(SAMPLE_RATE), "-vn",
            "-f", "wav", str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not dest.is_file():
        detail = (proc.stderr or proc.stdout).strip()[:300] or f"ffmpeg exited {proc.returncode}"
        raise AudioInputError(f"cannot convert audio ({audio.name}) to WAV: {detail}")
    return dest


def probe_duration(audio: Path) -> float:
    """Duration of a decodable audio file, in seconds."""
    ffprobe = _require_binary("ffprobe")
    proc = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(audio),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[:300] or f"ffprobe exited {proc.returncode}"
        raise AudioInputError(f"cannot decode audio ({audio.name}): {detail}")
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise AudioInputError(f"no duration reported for {audio.name}") from None


def prepare(source: str, workdir: Path | None = None) -> tuple[Path, float]:
    """Resolve and normalize `source` to (16 kHz mono WAV, duration seconds)."""
    workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="lns-"))
    workdir.mkdir(parents=True, exist_ok=True)
    local = load_audio(source, workdir)
    wav = to_wav(local, workdir)
    return wav, probe_duration(wav)


def transcode(src: Path, dest: Path, fmt: str) -> Path:
    """Transcode `src` to `fmt`, writing `dest`."""
    if fmt not in _TRANSCODE_CODECS:
        raise AudioInputError(f"unsupported format {fmt!r} (expected one of: {', '.join(_TRANSCODE_CODECS)})")
    ffmpeg = _require_binary("ffmpeg")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src), "-vn", *_TRANSCODE_CODECS[fmt], str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not dest.is_file():
        detail = (proc.stderr or proc.stdout).strip()[:300] or f"ffmpeg exited {proc.returncode}"
        raise AudioInputError(f"cannot transcode {src.name} to {fmt}: {detail}")
    return dest
