"""Config tests: defaults, env parsing, gates, engine validation."""

import os
import unittest
from unittest import mock

from listen_n_speak.config import (
    DEFAULT_STT_ENGINE,
    DEFAULT_TTS_ENGINE,
    load_config,
)


class DefaultTests(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.stt_engine, DEFAULT_STT_ENGINE)
        self.assertEqual(cfg.tts_engine, DEFAULT_TTS_ENGINE)
        self.assertEqual(cfg.stt_fallbacks, ("groq",))
        self.assertEqual(cfg.tts_fallbacks, ("edge", "espeak"))
        self.assertEqual(cfg.silence_s, 5.0)
        self.assertEqual(cfg.max_s, 300.0)
        self.assertIsNone(cfg.groq_api_key)
        self.assertIsNone(cfg.input_device)
        self.assertTrue(cfg.transcribe_enabled)
        self.assertTrue(cfg.speak_enabled)
        self.assertTrue(cfg.listen_enabled)


class EnvTests(unittest.TestCase):
    def test_overrides(self):
        env = {
            "LISTEN_N_SPEAK_STT_ENGINE": "groq",
            "LISTEN_N_SPEAK_TTS_ENGINE": "espeak",
            "LISTEN_N_SPEAK_STT_FALLBACKS": "",
            "LISTEN_N_SPEAK_TTS_FALLBACKS": "edge, piper",
            "LISTEN_N_SPEAK_SILENCE_S": "2.5",
            "LISTEN_N_SPEAK_MAX_S": "60",
            "LISTEN_N_SPEAK_TTS_VOICE": "af_heart",
            "LISTEN_N_SPEAK_TTS_BASE_URL": "https://example.test/v1",
            "LISTEN_N_SPEAK_TTS_API_KEY": "k",
            "GROQ_API_KEY": "g",
            "LISTEN_N_SPEAK_INPUT": "mic1",
            "LISTEN_N_SPEAK_OUTPUT_DIR": "/tmp/lns-out",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.stt_engine, "groq")
        self.assertEqual(cfg.tts_engine, "espeak")
        self.assertEqual(cfg.stt_fallbacks, ())
        self.assertEqual(cfg.tts_fallbacks, ("edge", "piper"))
        self.assertEqual(cfg.silence_s, 2.5)
        self.assertEqual(cfg.max_s, 60.0)
        self.assertEqual(cfg.tts_voice, "af_heart")
        self.assertEqual(cfg.tts_base_url, "https://example.test/v1")
        self.assertEqual(cfg.tts_api_key, "k")
        self.assertEqual(cfg.groq_api_key, "g")
        self.assertEqual(cfg.input_device, "mic1")
        self.assertEqual(str(cfg.output_dir), "/tmp/lns-out")

    def test_gates_off(self):
        env = {"TRANSCRIBE_ENABLED": "0", "SPEAK_ENABLED": "false", "LISTEN_ENABLED": "no"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertFalse(cfg.transcribe_enabled)
        self.assertFalse(cfg.speak_enabled)
        self.assertFalse(cfg.listen_enabled)

    def test_unknown_engine_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {"LISTEN_N_SPEAK_STT_ENGINE": "bogus"}, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.stt_engine, DEFAULT_STT_ENGINE)

    def test_bad_float_keeps_default(self):
        with mock.patch.dict(os.environ, {"LISTEN_N_SPEAK_SILENCE_S": "abc"}, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.silence_s, 5.0)


if __name__ == "__main__":
    unittest.main()
