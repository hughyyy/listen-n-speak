"""TTS dispatcher tests: engine selection, format normalization, playback."""

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from listen_n_speak.config import Config
from listen_n_speak.tts import Dispatcher, TtsError, play_file


def fake_engine(name: str, calls: list[str], *, native="wav", error=None):
    def run(_cfg, _text, _voice, _fmt):
        calls.append(name)
        if error:
            raise TtsError(error)
        return Path(f"/tmp/{name}.{native}"), native

    return run


class SynthesizeTests(unittest.TestCase):
    def test_default_engine_and_result_shape(self):
        calls: list[str] = []
        cfg = Config(tts_engine="piper", tts_fallbacks=())
        dispatcher = Dispatcher(cfg, engines={"piper": fake_engine("piper", calls)})
        with mock.patch("listen_n_speak.tts.audio.probe_duration", return_value=1.5):
            result = dispatcher.synthesize("hello")
        self.assertEqual(calls, ["piper"])
        self.assertEqual(result["engine"], "piper")
        self.assertEqual(result["duration_s"], 1.5)
        self.assertEqual(result["voice"], "en_US-lessac-medium")
        self.assertTrue(result["file"].endswith(".wav"))

    def test_format_mismatch_transcodes(self):
        calls: list[str] = []
        cfg = Config(tts_engine="piper", tts_fallbacks=())
        dispatcher = Dispatcher(cfg, engines={"piper": fake_engine("piper", calls)})
        with mock.patch(
            "listen_n_speak.tts.audio.transcode", return_value=Path("/tmp/out.mp3")
        ) as transcode, mock.patch(
            "listen_n_speak.tts.audio.probe_duration", return_value=1.0
        ):
            result = dispatcher.synthesize("hello", fmt="mp3")
        transcode.assert_called_once()
        self.assertEqual(result["file"], "/tmp/out.mp3")

    def test_invalid_format(self):
        dispatcher = Dispatcher(Config(), engines={})
        with self.assertRaises(TtsError):
            dispatcher.synthesize("hello", fmt="xyz")

    def test_empty_text(self):
        dispatcher = Dispatcher(Config(), engines={})
        with self.assertRaises(TtsError):
            dispatcher.synthesize("   ")

    def test_fallback_walk(self):
        calls: list[str] = []
        cfg = Config(tts_engine="piper", tts_fallbacks=("edge",))
        dispatcher = Dispatcher(
            cfg,
            engines={
                "piper": fake_engine("piper", calls, error="offline"),
                "edge": fake_engine("edge", calls, native="wav"),
            },
        )
        with mock.patch("listen_n_speak.tts.audio.probe_duration", return_value=1.0):
            result = dispatcher.synthesize("hello")
        self.assertEqual(calls, ["piper", "edge"])
        self.assertEqual(result["engine"], "edge")

    def test_unknown_engine(self):
        dispatcher = Dispatcher(Config(), engines={"piper": fake_engine("piper", [])})
        with self.assertRaises(TtsError) as ctx:
            dispatcher.synthesize("hello", engine="nope")
        self.assertIn("unknown TTS engine", str(ctx.exception))


class PlaybackTests(unittest.TestCase):
    def test_no_playback_binary(self):
        with mock.patch("listen_n_speak.tts.shutil.which", return_value=None):
            played, error = play_file(Path("/tmp/x.wav"))
        self.assertFalse(played)
        self.assertIn("no playback binary", error)

    def test_playback_success(self):
        with mock.patch(
            "listen_n_speak.tts.shutil.which",
            side_effect=lambda name: "/usr/bin/aplay" if name == "aplay" else None,
        ), mock.patch(
            "listen_n_speak.tts.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ):
            played, error = play_file(Path("/tmp/x.wav"))
        self.assertTrue(played)
        self.assertIsNone(error)

    def test_playback_failure_is_reported(self):
        with mock.patch(
            "listen_n_speak.tts.shutil.which",
            side_effect=lambda name: "/usr/bin/aplay" if name == "aplay" else None,
        ), mock.patch(
            "listen_n_speak.tts.subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", "no device"),
        ):
            played, error = play_file(Path("/tmp/x.wav"))
        self.assertFalse(played)
        self.assertEqual(error, "no device")


if __name__ == "__main__":
    unittest.main()
