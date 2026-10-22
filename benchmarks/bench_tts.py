#!/usr/bin/env python3
"""TTS benchmark: synthesis latency and output size per engine.

Runs each available engine over a fixed sample set, saves the audio under
`benchmarks/results/`, and writes a manifest the STT benchmark consumes.
Quality is not measured here — rank the saved files blind by ear, then record
the ranking in README's benchmark table.

Run: python3 benchmarks/bench_tts.py [--engines piper,edge,espeak,openai]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

from listen_n_speak.config import load_config
from listen_n_speak.tts import Dispatcher, TtsError

SAMPLES = {
    "announcement": "Heads up: the build finished and all tests passed.",
    "technical": "Call transcribe with engine set to faster-whisper for offline speech to text.",
    "paragraph": (
        "The quick brown fox jumps over the lazy dog. Pack my box with five "
        "dozen liquor jugs. The five boxing wizards jump quickly."
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", default="piper,edge,espeak,openai")
    parser.add_argument("--out", default="benchmarks/results")
    args = parser.parse_args()

    cfg = load_config()
    dispatcher = Dispatcher(cfg)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = outdir / f"tts-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    manifest: dict[str, str] = {}
    for engine in [e.strip() for e in args.engines.split(",") if e.strip()]:
        for sample_name, text in SAMPLES.items():
            started = time.perf_counter()
            try:
                result = dispatcher.synthesize(text, engine=engine)
            except TtsError as exc:
                rows.append(
                    {"engine": engine, "sample": sample_name, "error": str(exc)}
                )
                continue
            elapsed = time.perf_counter() - started
            source = Path(result["file"])
            dest = run_dir / f"{engine}-{sample_name}{source.suffix}"
            dest.write_bytes(source.read_bytes())
            manifest[str(dest)] = text
            rows.append(
                {
                    "engine": engine,
                    "sample": sample_name,
                    "latency_s": round(elapsed, 3),
                    "audio_s": result["duration_s"],
                    "bytes": dest.stat().st_size,
                    "file": str(dest),
                }
            )
            print(
                f"{engine:8s} {sample_name:13s} "
                f"{elapsed:6.2f}s synth for {result['duration_s']:5.1f}s audio "
                f"({dest.stat().st_size // 1024} KiB)"
            )

    (run_dir / "tts.json").write_text(json.dumps(rows, indent=2))
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nResults: {run_dir}/tts.json")
    print(f"Listening ranking input: {run_dir} (blind-rank the files, record in README)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
