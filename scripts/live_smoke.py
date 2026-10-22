#!/usr/bin/env python3
"""Live smoke: synthesize a sentence, transcribe it back, play it aloud.

Verifies the real pipeline end to end on this host:
  piper speech -> WAV -> faster-whisper transcript -> aplay playback

Run: .venv/bin/python scripts/live_smoke.py [--engine piper] [--stt faster-whisper]
Exit code 0 means the transcript came back recognizably similar.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

from listen_n_speak.audio import prepare
from listen_n_speak.config import load_config
from listen_n_speak.stt import Dispatcher as SttDispatcher, SttError
from listen_n_speak.tts import Dispatcher as TtsDispatcher, TtsError, play_file

SENTENCE = "The quick brown fox jumps over the lazy dog."


def similarity(reference: str, hypothesis: str) -> float:
    normalize = lambda text: re.findall(r"[a-z0-9']+", text.lower())
    return difflib.SequenceMatcher(None, normalize(reference), normalize(hypothesis)).ratio()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts", default="piper")
    parser.add_argument("--stt", default="faster-whisper")
    parser.add_argument("--no-play", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    tts = TtsDispatcher(cfg)
    stt = SttDispatcher(cfg)

    try:
        synth = tts.synthesize(SENTENCE, engine=args.tts)
    except TtsError as exc:
        print(f"FAIL synthesize: {exc}")
        return 1
    print("synthesized:", json.dumps(synth))

    wav, duration = prepare(synth["file"])
    try:
        heard = stt.transcribe(wav, duration, engine=args.stt, language="en")
    except SttError as exc:
        print(f"FAIL transcribe: {exc}")
        return 1
    print("transcribed:", json.dumps(heard))

    score = similarity(SENTENCE, heard["text"])
    print(f"similarity: {score:.0%}")
    if score < 0.6:
        print("FAIL: transcript too far from the spoken sentence")
        return 1

    if not args.no_play:
        played, error = play_file(Path(synth["file"]))
        print("playback:", played, error or "")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
