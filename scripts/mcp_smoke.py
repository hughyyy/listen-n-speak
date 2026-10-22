#!/usr/bin/env python3
"""Live MCP smoke: spawn the server over stdio and exercise every tool.

Proves the harness-facing path, not just the library path:
  list tools -> synthesize -> transcribe a data URI -> speak -> listen

`listen` is expected to fail with a clear tkinter error on hosts without the
`tk` package (this VM); that is the specified degradation, so it is reported
rather than treated as a harness failure.

Run: .venv/bin/python scripts/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result) -> dict:
    text = result.content[0].text if result.content else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


async def run() -> int:
    # OMP spawns the server with the session environment; mcp's stdio client
    # would otherwise whitelist vars and break audio playback.
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "listen_n_speak"], env=dict(os.environ)
    )
    failures: list[str] = []

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(tool.name for tool in (await session.list_tools()).tools)
            print("tools:", tools)
            if set(tools) != {"transcribe", "speak", "synthesize", "listen"}:
                failures.append(f"unexpected tool surface: {tools}")

            synth = payload(await session.call_tool("synthesize", {"text": "MCP smoke test sentence."}))
            print("synthesize:", synth)
            if "error" in synth:
                failures.append(f"synthesize failed: {synth['error']}")
                return 1

            audio_bytes = Path(synth["file"]).read_bytes()
            data_uri = "data:audio/wav;base64," + base64.b64encode(audio_bytes).decode()
            heard = payload(
                await session.call_tool("transcribe", {"audio": data_uri, "language": "en"})
            )
            print("transcribe:", heard)
            if "error" in heard:
                failures.append(f"transcribe failed: {heard['error']}")
            elif "smoke" not in heard.get("text", "").lower():
                failures.append(f"transcript missed the spoken words: {heard.get('text')!r}")

            spoken = payload(await session.call_tool("speak", {"text": "Playback check."}))
            print("speak:", spoken)
            if "error" in spoken:
                failures.append(f"speak failed: {spoken['error']}")

            heard_dialog = payload(
                await session.call_tool("listen", {"prompt": "Say something (smoke test)."})
            )
            print("listen:", heard_dialog)
            if "error" not in heard_dialog:
                failures.append("listen unexpectedly succeeded without a display/tk")

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(" -", failure)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
