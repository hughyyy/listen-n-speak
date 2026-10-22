"""Dialog tests: silence detection, capture command, recording, result IPC."""

import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from listen_n_speak.dialog import ipc
from listen_n_speak.dialog.capture import (
    FRAME_BYTES,
    CaptureError,
    SilenceTracker,
    capture_command,
    record,
    rms,
)

FRAME_SECONDS = FRAME_BYTES / (16000 * 2)


def silent_frame() -> bytes:
    return b"\x00" * FRAME_BYTES


def loud_frame(amplitude: int = 12000) -> bytes:
    return struct.pack("<1600h", *([amplitude] * 1600))


class RmsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(rms(b""), 0.0)

    def test_silence(self):
        self.assertEqual(rms(silent_frame()), 0.0)

    def test_speech_level(self):
        self.assertGreater(rms(loud_frame()), 300.0)


class SilenceTrackerTests(unittest.TestCase):
    def test_stops_after_threshold(self):
        tracker = SilenceTracker(silence_s=5.0)
        stopped_at = None
        for index in range(60):
            if tracker.feed(silent_frame(), FRAME_SECONDS):
                stopped_at = index + 1
                break
        self.assertIsNotNone(stopped_at)
        self.assertAlmostEqual(stopped_at * FRAME_SECONDS, 5.0, delta=0.11)

    def test_speech_resets_counter(self):
        tracker = SilenceTracker(silence_s=1.0)
        for _ in range(5):
            tracker.feed(silent_frame(), FRAME_SECONDS)
        self.assertFalse(tracker.feed(loud_frame(), FRAME_SECONDS))
        self.assertEqual(tracker.silent_s, 0.0)
        for _ in range(9):
            self.assertFalse(tracker.feed(silent_frame(), FRAME_SECONDS))
        self.assertTrue(tracker.feed(silent_frame(), FRAME_SECONDS))


class CaptureCommandTests(unittest.TestCase):
    def test_parecord_preferred(self):
        with mock.patch(
            "listen_n_speak.dialog.capture.shutil.which",
            side_effect=lambda name: "/usr/bin/parecord" if name == "parecord" else None,
        ):
            command = capture_command(None)
        self.assertTrue(command[0].endswith("parecord"))
        self.assertIn("--rate=16000", command)

    def test_device_passed(self):
        with mock.patch(
            "listen_n_speak.dialog.capture.shutil.which",
            side_effect=lambda name: "/usr/bin/parecord" if name == "parecord" else None,
        ):
            command = capture_command("mic1")
        self.assertIn("--device", command)
        self.assertIn("mic1", command)

    def test_arecord_fallback(self):
        with mock.patch(
            "listen_n_speak.dialog.capture.shutil.which",
            side_effect=lambda name: "/usr/bin/arecord" if name == "arecord" else None,
        ):
            command = capture_command(None)
        self.assertTrue(command[0].endswith("arecord"))
        self.assertIn("S16_LE", command)

    def test_no_tool(self):
        with mock.patch("listen_n_speak.dialog.capture.shutil.which", return_value=None):
            with self.assertRaises(CaptureError):
                capture_command(None)


class FakePopen:
    def __init__(self, frames):
        self.stdout = io.BytesIO(b"".join(frames))
        self.stderr = io.BytesIO(b"")
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class RecordTests(unittest.TestCase):
    def test_stops_on_silence_and_writes_wav(self):
        workdir = Path(tempfile.mkdtemp(prefix="lns-rec-"))
        frames = [silent_frame() for _ in range(60)]
        with mock.patch(
            "listen_n_speak.dialog.capture.shutil.which",
            side_effect=lambda name: "/usr/bin/parecord" if name == "parecord" else None,
        ), mock.patch(
            "listen_n_speak.dialog.capture.subprocess.Popen",
            return_value=FakePopen(frames),
        ):
            wav, duration, reason = record(workdir, silence_s=5.0, max_s=300.0)
        self.assertEqual(reason, "silence")
        self.assertTrue(wav.is_file())
        self.assertAlmostEqual(duration, 5.0, delta=0.2)

    def test_empty_capture_raises(self):
        workdir = Path(tempfile.mkdtemp(prefix="lns-rec-"))
        with mock.patch(
            "listen_n_speak.dialog.capture.shutil.which",
            side_effect=lambda name: "/usr/bin/parecord" if name == "parecord" else None,
        ), mock.patch(
            "listen_n_speak.dialog.capture.subprocess.Popen",
            return_value=FakePopen([]),
        ):
            with self.assertRaises(CaptureError):
                record(workdir, silence_s=5.0, max_s=300.0)


class IpcTests(unittest.TestCase):
    def test_roundtrip(self):
        path = Path(tempfile.mkdtemp(prefix="lns-ipc-")) / "result.json"
        payload = {"text": "hello", "audio": "/tmp/a.wav", "duration_s": 1.5, "engine": "fake"}
        ipc.write_result(path, payload)
        self.assertEqual(ipc.read_result(path), payload)

    def test_missing_returns_none(self):
        self.assertIsNone(ipc.read_result(Path("/nonexistent/result.json")))

    def test_malformed_returns_none(self):
        path = Path(tempfile.mkdtemp(prefix="lns-ipc-")) / "result.json"
        path.write_text("{not json")
        self.assertIsNone(ipc.read_result(path))


if __name__ == "__main__":
    unittest.main()
