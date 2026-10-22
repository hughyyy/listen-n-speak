"""Microphone capture and silence-based auto-stop (PulseAudio/PipeWire)."""

from __future__ import annotations

import array
import math
import shutil
import subprocess
import threading
import wave
from pathlib import Path
from typing import Callable

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
FRAME_SECONDS = 0.1
FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * FRAME_SECONDS)  # 3200 = 100 ms
# s16le full scale is 32768; 300 ≈ -41 dBFS — below speech, above room tone.
SILENCE_RMS = 300.0


class CaptureError(RuntimeError):
    """Microphone capture failed (no device, no capture tool, ...)."""


def rms(frame: bytes) -> float:
    """Root-mean-square amplitude of an s16le frame (0..32767)."""
    if not frame:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % BYTES_PER_SAMPLE)])
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


class SilenceTracker:
    """Accumulates silence duration; tells the recorder when to stop."""

    def __init__(self, silence_s: float, threshold: float = SILENCE_RMS) -> None:
        self.silence_s = silence_s
        self.threshold = threshold
        self.silent_s = 0.0

    def feed(self, frame: bytes, duration_s: float) -> bool:
        """Feed one frame; True once silence has lasted `silence_s`."""
        if rms(frame) < self.threshold:
            self.silent_s += duration_s
        else:
            self.silent_s = 0.0
        # Frame durations are floats (0.1 s); without tolerance, ten silent
        # frames sum to 0.9999... and miss a 1.0 s threshold.
        return self.silent_s >= self.silence_s - 1e-6


def capture_command(device: str | None) -> list[str]:
    """The capture command for this host (parecord preferred, arecord fallback)."""
    parecord = shutil.which("parecord")
    if parecord:
        command = [
            parecord, "--raw", "--format=s16le",
            f"--rate={SAMPLE_RATE}", "--channels=1",
        ]
        if device:
            command += ["--device", device]
        return command
    arecord = shutil.which("arecord")
    if arecord:
        command = [
            arecord, "-q", "-t", "raw", "-f", "S16_LE",
            "-r", str(SAMPLE_RATE), "-c", "1",
        ]
        if device:
            command += ["-D", device]
        return command
    raise CaptureError(
        "no capture tool found — install pulseaudio-utils (parecord) or alsa-utils (arecord)"
    )


def record(
    workdir: Path,
    silence_s: float = 5.0,
    max_s: float = 300.0,
    device: str | None = None,
    on_chunk: Callable[[bytes], None] | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[Path, float, str]:
    """Record to a 16 kHz mono WAV until `silence_s` of silence or `max_s`.

    Returns (wav path, duration seconds, stop reason) where reason is
    `silence`, `max_duration`, or `device_closed`.
    """
    command = capture_command(device)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    wav_path = workdir / "capture.wav"
    tracker = SilenceTracker(silence_s)
    stop_event = stop_event or threading.Event()
    total_bytes = 0
    reason = "max_duration"

    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert proc.stdout is not None
        with wave.open(str(wav_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(BYTES_PER_SAMPLE)
            wav_file.setframerate(SAMPLE_RATE)
            while not stop_event.is_set():
                frame = proc.stdout.read(FRAME_BYTES)
                if not frame:
                    reason = "device_closed"
                    break
                wav_file.writeframes(frame)
                total_bytes += len(frame)
                if on_chunk:
                    on_chunk(frame)
                frame_s = len(frame) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
                if tracker.feed(frame, frame_s):
                    reason = "silence"
                    break
                if total_bytes / (SAMPLE_RATE * BYTES_PER_SAMPLE) >= max_s:
                    reason = "max_duration"
                    break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    duration = total_bytes / (SAMPLE_RATE * BYTES_PER_SAMPLE)
    if total_bytes == 0:
        detail = ""
        if proc.stderr is not None:
            try:
                detail = proc.stderr.read().decode(errors="replace").strip()[:300]
            except Exception:
                detail = ""
        raise CaptureError(f"no audio captured{': ' + detail if detail else ''}")
    return wav_path, duration, reason
