#!/usr/bin/env python3
"""Dialog smoke: drive `listen` end-to-end with real audio, no human.

Routes synthesized speech into a PipeWire/PulseAudio null sink and points the
dialog's capture at that sink's monitor source. The dialog auto-starts
recording (the `--auto-send` smoke hook), the speech plays into the sink,
silence auto-stops the capture, the final transcript is auto-sent, and the
MCP `listen` call returns it — exercising capture, live typing, final
transcription, IPC, and the tool handler without clicking anything.

Requires: tk, parecord, paplay, pactl, and a running PipeWire/PulseAudio.
Run: .venv/bin/python scripts/dialog_smoke.py
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from listen_n_speak.config import load_config
from listen_n_speak.tts import Dispatcher as TtsDispatcher, TtsError

SENTENCE = "The listen dialog smoke test is working."
SINK = "lns_smoke"


def similarity(reference: str, hypothesis: str) -> float:
    normalize = lambda text: re.findall(r"[a-z0-9']+", text.lower())
    return difflib.SequenceMatcher(None, normalize(reference), normalize(hypothesis)).ratio()


def load_null_sink() -> int | None:
    proc = subprocess.run(
        [
            "pactl", "load-module", "module-null-sink",
            f"sink_name={SINK}", "rate=16000", "channels=1",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"pactl load-module failed: {proc.stderr.strip()}")
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def unload_module(module_id: int) -> None:
    subprocess.run(["pactl", "unload-module", str(module_id)], capture_output=True, text=True)


async def run() -> int:
    cfg = load_config()
    try:
        speech = TtsDispatcher(cfg).synthesize(SENTENCE, engine="piper")
    except TtsError as exc:
        print(f"FAIL synthesize: {exc}")
        return 1
    print("speech:", json.dumps(speech))

    module_id = load_null_sink()
    if module_id is None:
        return 1

    env = dict(
        os.environ,
        LISTEN_N_SPEAK_INPUT=f"{SINK}.monitor",
        LISTEN_N_SPEAK_DIALOG_AUTO_SEND="1",
        LISTEN_N_SPEAK_SILENCE_S="4",
    )
    server = Path(".venv/bin/listen-n-speak")
    params = StdioServerParameters(
        command=str(server) if server.is_file() else sys.executable,
        args=[] if server.is_file() else ["-m", "listen_n_speak"],
        env=env,
    )

    async def play_into_sink() -> None:
        await asyncio.sleep(3.0)  # let the dialog open and start recording
        subprocess.run(
            ["paplay", "--device", SINK, speech["file"]],
            capture_output=True,
            text=True,
        )

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                player = asyncio.create_task(play_into_sink())
                try:
                    response = await session.call_tool(
                        "listen", {"prompt": "Smoke test: say the sentence."}
                    )
                finally:
                    await player
                text = response.content[0].text if response.content else ""
                payload = json.loads(text)
    finally:
        unload_module(module_id)

    print("listen:", json.dumps(payload))
    if payload.get("error"):
        print("FAIL:", payload["error"])
        return 1
    transcript = payload.get("text") or ""
    score = similarity(SENTENCE, transcript)
    print(f"similarity: {score:.0%}  audio: {payload.get('audio')}")
    if score < 0.6:
        print("FAIL: dialog transcript too far from the spoken sentence")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
