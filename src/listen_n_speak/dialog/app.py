"""The `listen` dialog: prompt, red record button, live transcript, Clear/Send.

Run as a subprocess (`python -m listen_n_speak.dialog.app`) by the server so a
GUI crash cannot take the stdio server down. Recording starts only when the
human clicks the red record button; it auto-stops after `silence_s` of
silence, and the transcript is returned when the human clicks Send.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from ..config import Config, load_config
from ..stt import Dispatcher as SttDispatcher, SttError
from . import ipc
from .capture import CaptureError, record
from .streaming import LiveTranscriber

LIVE_REFRESH_S = 1.5


class Dialog:
    """Modal window: prompt + record + live text + Clear/Send."""

    def __init__(self, args: argparse.Namespace, cfg: Config) -> None:
        import tkinter as tk

        self.tk = tk
        self.args = args
        self.cfg = cfg
        self.root = tk.Tk()
        self.root.title("listen-n-speak")
        self.root.attributes("-topmost", True)
        self.queue: queue.Queue = queue.Queue()
        self.out_path = Path(args.out)
        self.workdir = self.out_path.parent
        self.recording = False
        self.sent = False
        self.live: LiveTranscriber | None = None
        self.live_pending = threading.Event()
        self.live_stop = threading.Event()
        self.live_unavailable: str | None = None
        self.audio_path: Path | None = None
        self.duration_s: float | None = None
        self.engine: str | None = None
        self.auto_send = bool(getattr(args, "auto_send", False))
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._dismiss)

    # -- widgets ---------------------------------------------------------
    def _build(self) -> None:
        tk = self.tk
        frame = tk.Frame(self.root, padx=16, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text=self.args.prompt,
            wraplength=520,
            justify="left",
            font=("Sans", 11),
        ).pack(anchor="w")
        controls = tk.Frame(frame)
        controls.pack(fill="x", pady=(12, 6))
        self.record_btn = tk.Button(
            controls,
            text="\u25cf Record",
            bg="#c62828",
            fg="white",
            activebackground="#8e0000",
            activeforeground="white",
            width=12,
            command=self._start_recording,
        )
        self.record_btn.pack(side="left")
        self.status_label = tk.Label(
            controls, text="Click Record and speak.", anchor="w", fg="#555"
        )
        self.status_label.pack(side="left", padx=(12, 0))
        self.text = tk.Text(frame, height=6, width=64, wrap="word")
        self.text.pack(fill="both", expand=True)
        buttons = tk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))
        tk.Button(buttons, text="Clear", width=10, command=self._clear).pack(side="left")
        tk.Button(
            buttons, text="Send", width=10, default="active", command=self._send
        ).pack(side="right")
        self.root.bind("<Escape>", lambda _event: self._dismiss())

    # -- lifecycle -------------------------------------------------------
    def run(self) -> int:
        self.root.lift()
        self.root.after(120, self._poll)
        if self.auto_send:
            # Smoke hook: acts as if the record button were clicked.
            self.root.after(400, self._start_recording)
        self.root.mainloop()
        return 0

    def _set_status(self, message: str) -> None:
        self.status_label.config(text=message)

    def _text_value(self) -> str:
        return self.text.get("1.0", "end").strip()

    def _set_text(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)

    # -- recording -------------------------------------------------------
    def _start_recording(self) -> None:
        if self.recording:
            return
        self.recording = True
        self.record_btn.config(state="disabled")
        self.live_pending.clear()
        if self.live is None and self.live_unavailable is None:
            try:
                import faster_whisper  # noqa: F401  (availability probe)

                self.live = LiveTranscriber(self.cfg.stt_model)
                threading.Thread(target=self._live_loop, daemon=True).start()
            except ImportError:
                self.live_unavailable = (
                    "live transcription unavailable (install 'listen-n-speak[stt]')"
                )
        self._set_status(
            f"Recording — speak; stops after {self.cfg.silence_s:.0f}s of silence."
        )
        threading.Thread(target=self._record_thread, daemon=True).start()

    def _on_audio(self, chunk: bytes) -> None:
        """Called from the capture thread — never touches widgets."""
        if self.live is not None and not self.live_stop.is_set():
            self.live.feed(chunk)
            self.live_pending.set()

    def _record_thread(self) -> None:
        try:
            wav, duration, reason = record(
                self.workdir,
                silence_s=self.cfg.silence_s,
                max_s=self.cfg.max_s,
                device=self.cfg.input_device,
                on_chunk=self._on_audio,
            )
            self.queue.put(("recorded", (wav, duration, reason)))
        except CaptureError as exc:
            self.queue.put(("error", str(exc)))
        except Exception as exc:  # never let the thread die silently
            self.queue.put(("error", f"recording failed: {exc}"))

    def _live_loop(self) -> None:
        while not self.live_stop.is_set():
            if not self.live_pending.wait(timeout=0.2):
                continue
            self.live_pending.clear()
            time.sleep(LIVE_REFRESH_S)
            if self.live is None or self.live_stop.is_set():
                return
            try:
                text = self.live.text()
            except Exception as exc:
                self.queue.put(("status", f"live transcription stopped: {exc}"))
                return
            if text:
                self.queue.put(("live", text))

    # -- final transcription --------------------------------------------
    def _on_recorded(self, wav: Path, duration: float, reason: str) -> None:
        self.recording = False
        self.record_btn.config(state="normal")
        self.audio_path = wav
        self.duration_s = duration
        self._set_status(
            "Silence detected. Transcribing…" if reason == "silence" else "Transcribing…"
        )
        threading.Thread(
            target=self._final_thread, args=(wav, duration), daemon=True
        ).start()

    def _final_thread(self, wav: Path, duration: float) -> None:
        dispatcher = SttDispatcher(self.cfg)
        try:
            result = dispatcher.transcribe(
                wav, duration, engine=self.args.engine, model=self.args.model
            )
            self.queue.put(("final", result))
        except SttError as exc:
            self.queue.put(("final_error", str(exc)))

    # -- actions ---------------------------------------------------------
    def _send(self) -> None:
        text = self._text_value()
        if not text:
            self._set_status("Nothing to send — press Record and speak first.")
            return
        ipc.write_result(
            self.out_path,
            {
                "text": text,
                "audio": str(self.audio_path) if self.audio_path else None,
                "duration_s": round(self.duration_s, 2) if self.duration_s else None,
                "engine": self.engine or "unknown",
            },
        )
        self.sent = True
        self.live_stop.set()
        self.root.destroy()

    def _clear(self) -> None:
        self._set_text("")
        self._set_status("Cleared — press Record and speak again.")
        if self.live is not None:
            self.live.clear()
        self.audio_path = None
        self.duration_s = None
        self.engine = None

    def _dismiss(self) -> None:
        if not self.sent:
            ipc.write_result(self.out_path, {"text": None, "reason": "dismissed"})
        self.live_stop.set()
        self.root.destroy()

    def _auto_finalize(self) -> None:
        """Smoke mode: send the transcript (or an empty result) immediately."""
        text = self._text_value()
        if text:
            self._send()
            return
        ipc.write_result(
            self.out_path,
            {
                "text": "",
                "audio": str(self.audio_path) if self.audio_path else None,
                "duration_s": round(self.duration_s, 2) if self.duration_s else None,
                "engine": self.engine or "unknown",
            },
        )
        self.sent = True
        self.live_stop.set()
        self.root.destroy()

    # -- UI pump ---------------------------------------------------------
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "live":
                    if payload:
                        self._set_text(payload)
                elif kind == "recorded":
                    self._on_recorded(*payload)
                elif kind == "final":
                    self._set_text(payload.get("text", ""))
                    self.engine = payload.get("engine")
                    if payload.get("text"):
                        self._set_status("Press Send to return this to the agent.")
                    else:
                        self._set_status(
                            "No speech recognized — press Record to try again."
                        )
                    if self.auto_send:
                        self._auto_finalize()
                elif kind == "final_error":
                    self.live_stop.set()
                    self._set_status(f"Transcription failed: {payload}")
                elif kind == "status":
                    self._set_status(payload)
                elif kind == "error":
                    self.recording = False
                    self.record_btn.config(state="normal")
                    self._set_status(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="listen-n-speak-dialog")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--silence-s", type=float, default=None)
    parser.add_argument("--max-s", type=float, default=None)
    parser.add_argument("--engine", default=None)
    parser.add_argument("--model", default=None)
    # Smoke hook for hosts without input-injection tools: start recording
    # immediately and send the transcript when recording stops.
    parser.add_argument("--auto-send", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.silence_s is not None:
        cfg = replace(cfg, silence_s=args.silence_s)
    if args.max_s is not None:
        cfg = replace(cfg, max_s=args.max_s)

    try:
        import tkinter as tk
    except ImportError as exc:
        print(
            f"listen-n-speak: tkinter unavailable ({exc}); install tk (pacman -S tk)",
            file=sys.stderr,
        )
        return 2

    try:
        dialog = Dialog(args, cfg)
    except tk.TclError as exc:
        print(f"listen-n-speak: cannot open a display: {exc}", file=sys.stderr)
        return 2
    return dialog.run()


if __name__ == "__main__":
    raise SystemExit(main())
