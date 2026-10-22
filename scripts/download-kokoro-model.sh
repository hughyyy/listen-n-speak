#!/usr/bin/env bash
# download-kokoro-model.sh — fetch Kokoro-82M ONNX weights for OUT-OF-VM evaluation.
#
# STATUS (2026-10-22): Kokoro is a DEFERRED engine for listen-n-speak — no
# adapter is implemented in v1. Run this script and any evaluation OUTSIDE
# this virtual machine:
#   - kokoro-onnx supports Python 3.10-3.13; this VM has only Python 3.14.
#   - This VM's disks are tight (/mnt/shared 98% used, ~6.6 GB free in $HOME)
#     and the fp32 weights are ~300 MB (~80 MB int8).
# Why keep the script here: the adapter interface accepts any engine that
# maps text -> WAV, so Kokoro slots in later if the out-of-VM benchmark wins.
# See README.md ("Draft engines", "Benchmarks") for the benchmark protocol.
#
# Usage:
#   scripts/download-kokoro-model.sh [--int8] [DEST]
#
#   --int8    fetch the ~80 MB quantized model instead of the ~300 MB fp32
#             model (same release; curl --fail surfaces a clean error if the
#             file has been renamed upstream)
#   DEST      target directory (default: ~/.cache/listen-n-speak/kokoro)
#
# Requires: curl. Files come from the kokoro-onnx GitHub release:
#   https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1
# Voice/language catalog:
#   https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md

set -euo pipefail

INT8=0
if [[ "${1:-}" == "--int8" ]]; then
  INT8=1
  shift
fi
DEST="${1:-$HOME/.cache/listen-n-speak/kokoro}"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
MODEL="kokoro-v1.0.onnx"
if [[ $INT8 == 1 ]]; then
  MODEL="kokoro-v1.0.int8.onnx"
fi

mkdir -p "$DEST"

fetch() {
  local url="$1" out="$2"
  echo ">> $url"
  curl -L --fail --retry 3 --continue-at - -o "$out" "$url"
}

fetch "$BASE/$MODEL"          "$DEST/$MODEL"
fetch "$BASE/voices-v1.0.bin" "$DEST/voices-v1.0.bin"

echo
echo "Downloaded into $DEST:"
ls -lh "$DEST"
echo
echo "Next steps (outside this VM): pip install kokoro-onnx soundfile"
echo "  from kokoro_onnx import Kokoro"
echo "  k = Kokoro.from_pretrained('$DEST/$MODEL', '$DEST/voices-v1.0.bin')"
echo "  audio, sr = k.create('Hello from Kokoro.', voice='af_heart')"
