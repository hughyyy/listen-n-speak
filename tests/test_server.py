"""Server tests: registration gating, tool behavior, error paths."""

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from listen_n_speak.config import Config
from listen_n_speak.server import create_server
from listen_n_speak.stt import SttError
from listen_n_speak.tts import TtsError

ALL_TOOLS = {"transcribe", "speak", "synthesize", "listen"}


class FakeStt:
    def __init__(self, result=None, error=None):
        self.result = result or {"text": "hello", "language": "en", "duration_s": 1.5, "engine": "fake"}
        self.error = error
        self.calls = []

    def transcribe(self, wav, duration, engine=None, language=None, model=None):
        self.calls.append({"engine": engine, "language": language, "model": model})
        if self.error:
            raise SttError(self.error)
        return dict(self.result)


class FakeTts:
    def __init__(self, result=None, error=None):
        self.result = result or {"file": "/tmp/x.wav", "duration_s": 1.0, "engine": "fake", "voice": "v"}
        self.error = error
        self.calls = []

    def synthesize(self, text, engine=None, voice=None, fmt=None):
        self.calls.append({"text": text, "engine": engine, "voice": voice, "fmt": fmt})
        if self.error:
            raise TtsError(self.error)
        return dict(self.result)


def tool_names(mcp) -> set[str]:
    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def call(mcp, name, arguments) -> str:
    result = asyncio.run(mcp.call_tool(name, arguments))
    return result.content[0].text


class RegistrationTests(unittest.TestCase):
    def test_all_tools_by_default(self):
        mcp = create_server(Config(), FakeStt(), FakeTts())
        self.assertEqual(tool_names(mcp), ALL_TOOLS)

    def test_listen_disabled(self):
        mcp = create_server(Config(listen_enabled=False), FakeStt(), FakeTts())
        self.assertEqual(tool_names(mcp), {"transcribe", "speak", "synthesize"})

    def test_transcribe_disabled(self):
        mcp = create_server(Config(transcribe_enabled=False), FakeStt(), FakeTts())
        self.assertEqual(tool_names(mcp), {"speak", "synthesize", "listen"})

    def test_speak_disabled_removes_both_speech_output_tools(self):
        mcp = create_server(Config(speak_enabled=False), FakeStt(), FakeTts())
        self.assertEqual(tool_names(mcp), {"transcribe", "listen"})

    def test_tool_descriptions_present(self):
        mcp = create_server(Config(), FakeStt(), FakeTts())
        tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
        for name in ALL_TOOLS:
            self.assertTrue(tools[name].description, f"{name} lacks a description")


class TranscribeToolTests(unittest.TestCase):
    def test_success_shape(self):
        stt = FakeStt()
        mcp = create_server(Config(), stt, FakeTts())
        with mock.patch(
            "listen_n_speak.server.prepare", return_value=(Path("/tmp/a.wav"), 1.5)
        ):
            payload = json.loads(call(mcp, "transcribe", {"audio": "/tmp/a.wav", "language": "en"}))
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(stt.calls[0]["language"], "en")

    def test_engine_error_becomes_json_error(self):
        mcp = create_server(Config(), FakeStt(error="no engine"), FakeTts())
        with mock.patch(
            "listen_n_speak.server.prepare", return_value=(Path("/tmp/a.wav"), 1.5)
        ):
            payload = json.loads(call(mcp, "transcribe", {"audio": "/tmp/a.wav"}))
        self.assertEqual(payload["error"], "no engine")

    def test_input_error_becomes_json_error(self):
        mcp = create_server(Config(), FakeStt(), FakeTts())
        payload = json.loads(call(mcp, "transcribe", {"audio": "/nonexistent/x.wav"}))
        self.assertIn("error", payload)


class SpeakToolTests(unittest.TestCase):
    def test_speak_plays_and_reports(self):
        tts = FakeTts()
        mcp = create_server(Config(), FakeStt(), tts)
        with mock.patch("listen_n_speak.server.play_file", return_value=(True, None)):
            payload = json.loads(call(mcp, "speak", {"text": "hi"}))
        self.assertTrue(payload["played"])
        self.assertEqual(tts.calls[0]["text"], "hi")

    def test_speak_playback_failure_is_reported(self):
        mcp = create_server(Config(), FakeStt(), FakeTts())
        with mock.patch(
            "listen_n_speak.server.play_file", return_value=(False, "no sink")
        ):
            payload = json.loads(call(mcp, "speak", {"text": "hi"}))
        self.assertFalse(payload["played"])
        self.assertEqual(payload["playback_error"], "no sink")

    def test_speak_engine_error(self):
        mcp = create_server(Config(), FakeStt(), FakeTts(error="no voice"))
        payload = json.loads(call(mcp, "speak", {"text": "hi"}))
        self.assertEqual(payload["error"], "no voice")


class SynthesizeToolTests(unittest.TestCase):
    def test_synthesize_does_not_play(self):
        mcp = create_server(Config(), FakeStt(), FakeTts())
        with mock.patch("listen_n_speak.server.play_file") as play:
            payload = json.loads(call(mcp, "synthesize", {"text": "hi"}))
        play.assert_not_called()
        self.assertNotIn("played", payload)
        self.assertEqual(payload["file"], "/tmp/x.wav")


class ListenToolTests(unittest.TestCase):
    def test_dialog_failure_becomes_json_error(self):
        mcp = create_server(Config(), FakeStt(), FakeTts())
        failed = subprocess.CompletedProcess([], 2, "", "tkinter unavailable\n")
        with mock.patch("listen_n_speak.server.subprocess.run", return_value=failed):
            payload = json.loads(call(mcp, "listen", {"prompt": "Name?"}))
        self.assertIn("listen dialog failed", payload["error"])
        self.assertIn("tkinter unavailable", payload["error"])

    def test_dialog_result_is_returned(self):
        workdir = Path(tempfile.mkdtemp(prefix="lns-srv-"))
        (workdir / "result.json").write_text(
            json.dumps({"text": "ada", "audio": "/tmp/a.wav", "duration_s": 1.2, "engine": "fake"})
        )
        ok = subprocess.CompletedProcess([], 0, "", "")
        mcp = create_server(Config(), FakeStt(), FakeTts())
        with mock.patch(
            "listen_n_speak.server.tempfile.mkdtemp", return_value=str(workdir)
        ), mock.patch("listen_n_speak.server.subprocess.run", return_value=ok):
            payload = json.loads(call(mcp, "listen", {"prompt": "Name?"}))
        self.assertEqual(payload["text"], "ada")


if __name__ == "__main__":
    unittest.main()
