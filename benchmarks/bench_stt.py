#!/usr/bin/env python3
"""STT benchmark: latency and WER per engine against a reference manifest.

Consumes the `manifest.json` written by `bench_tts.py` (file -> reference
text), transcribes each clip with every available engine, and reports word
error rate plus latency. Audio is synthesized speech, which flatters every
engine equally — treat the numbers as a relative comparison, not an absolute
WER claim.

Run: python3 benchmarks/bench_stt.py [--manifest PATH] [--engines faster-whisper,groq]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

from listen_n_speak.audio import prepare
from listen_n_speak.config import load_config
from listen_n_speak.stt import Dispatcher, SttError

WORD_RE = re.compile(r"[a-z0-9']+")


def words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein edit distance over words, normalized by reference length."""
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp, start=1):
            cost = 0 if ref_word == hyp_word else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1] / len(ref)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", default="benchmarks/results", help="dir containing manifest.json (or a path to one)"
    )
    parser.add_argument("--engines", default="faster-whisper,groq")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if manifest_path.is_dir():
        candidates = sorted(manifest_path.glob("tts-*/manifest.json"))
        if not candidates:
            print("no manifest found — run benchmarks/bench_tts.py first")
            return 2
        manifest_path = candidates[-1]
    manifest: dict[str, str] = json.loads(manifest_path.read_text())

    cfg = load_config()
    dispatcher = Dispatcher(cfg)
    rows: list[dict] = []
    for engine in [e.strip() for e in args.engines.split(",") if e.strip()]:
        for audio_file, reference in manifest.items():
            path = Path(audio_file)
            if not path.is_file():
                continue
            workdir = Path("benchmarks/results/work") / path.stem
            wav, duration = prepare(str(path), workdir)
            started = time.perf_counter()
            try:
                result = dispatcher.transcribe(
                    wav, duration, engine=engine, language="en"
                )
            except SttError as exc:
                rows.append({"engine": engine, "file": path.name, "error": str(exc)})
                continue
            elapsed = time.perf_counter() - started
            wer = word_error_rate(reference, result["text"])
            rows.append(
                {
                    "engine": engine,
                    "file": path.name,
                    "latency_s": round(elapsed, 3),
                    "audio_s": round(duration, 2),
                    "rtf": round(elapsed / duration, 3) if duration else None,
                    "wer": round(wer, 3),
                    "text": result["text"],
                }
            )
            print(
                f"{engine:14s} {path.name:28s} "
                f"{elapsed:6.2f}s  WER {wer:5.1%}  rtf {elapsed / duration:4.2f}"
            )

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path("benchmarks/results") / f"stt-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "stt.json").write_text(json.dumps(rows, indent=2))
    print(f"\nResults: {outdir}/stt.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
