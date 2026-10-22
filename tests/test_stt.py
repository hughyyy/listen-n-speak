"""STT dispatcher tests: engine selection, fallback walk, error aggregation."""

import unittest
from pathlib import Path

from listen_n_speak.config import Config
from listen_n_speak.stt import Dispatcher, SttError

WAV = Path("/tmp/fake.wav")


def fake_engine(engine_name: str, calls: list[str], *, result=None, error=None):
    def run(_cfg, _wav, _language, _model):
        calls.append(engine_name)
        if error:
            raise SttError(error)
        return dict(result or {"text": "hello", "language": "en", "engine": engine_name})

    return run


class ChainTests(unittest.TestCase):
    def test_default_engine_then_fallbacks(self):
        calls: list[str] = []
        cfg = Config(stt_engine="a", stt_fallbacks=("b",))
        dispatcher = Dispatcher(
            cfg,
            engines={
                "a": fake_engine("a", calls, error="down"),
                "b": fake_engine("b", calls),
            },
        )
        result = dispatcher.transcribe(WAV, 1.25)
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(result["engine"], "b")
        self.assertEqual(result["duration_s"], 1.25)

    def test_explicit_engine_does_not_fall_back(self):
        calls: list[str] = []
        cfg = Config(stt_engine="a", stt_fallbacks=("b",))
        dispatcher = Dispatcher(
            cfg,
            engines={
                "a": fake_engine("a", calls, error="down"),
                "b": fake_engine("b", calls),
            },
        )
        with self.assertRaises(SttError):
            dispatcher.transcribe(WAV, 1.0, engine="a")
        self.assertEqual(calls, ["a"])

    def test_unknown_engine_reports_known_set(self):
        dispatcher = Dispatcher(Config(), engines={"a": fake_engine("a", [])})
        with self.assertRaises(SttError) as ctx:
            dispatcher.transcribe(WAV, 1.0, engine="zzz")
        self.assertIn("unknown STT engine", str(ctx.exception))
        self.assertIn("a", str(ctx.exception))

    def test_all_fail_aggregates_errors(self):
        calls: list[str] = []
        cfg = Config(stt_engine="a", stt_fallbacks=("b",))
        dispatcher = Dispatcher(
            cfg,
            engines={
                "a": fake_engine("a", calls, error="first"),
                "b": fake_engine("b", calls, error="second"),
            },
        )
        with self.assertRaises(SttError) as ctx:
            dispatcher.transcribe(WAV, 1.0)
        message = str(ctx.exception)
        self.assertIn("first", message)
        self.assertIn("second", message)

    def test_result_defaults_text(self):
        cfg = Config(stt_engine="a", stt_fallbacks=())
        dispatcher = Dispatcher(cfg, engines={"a": lambda *_a: {"engine": "a"}})
        result = dispatcher.transcribe(WAV, 0.5)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["duration_s"], 0.5)


if __name__ == "__main__":
    unittest.main()
