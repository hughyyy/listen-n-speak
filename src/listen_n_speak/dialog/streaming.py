"""Chunked partial transcription for the dialog's live typing.

The live view re-transcribes a rolling window of the recording (cheap enough
on CPU for the `base` tier). The final transcript after Send/stop is a
full-buffer transcription by the regular STT dispatcher.
"""

from __future__ import annotations

import threading

LIVE_WINDOW_S = 30.0
SAMPLE_RATE = 16000


class LiveTranscriber:
    """Rolling-window partial transcription over incoming s16le chunks."""

    def __init__(
        self,
        model_size: str = "base",
        language: str | None = None,
        window_s: float = LIVE_WINDOW_S,
    ) -> None:
        self.model_size = model_size
        self.language = language
        self.window_s = window_s
        self._model = None
        self._lock = threading.Lock()
        self._buffer = bytearray()

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def clear(self) -> None:
        """Reset the rolling window (Clear button)."""
        with self._lock:
            self._buffer.clear()

    def feed(self, chunk: bytes) -> None:
        """Append audio; the window keeps only the most recent `window_s`."""
        with self._lock:
            self._buffer.extend(chunk)
            limit = int(self.window_s * SAMPLE_RATE * 2)
            if len(self._buffer) > limit:
                del self._buffer[: len(self._buffer) - limit]

    def text(self) -> str:
        """Transcribe the current window (empty string while silent)."""
        with self._lock:
            data = bytes(self._buffer)
        if not data:
            return ""
        import numpy as np

        model = self._ensure_model()
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            samples,
            language=self.language or None,
            beam_size=1,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
