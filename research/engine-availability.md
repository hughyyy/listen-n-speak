# Engine availability on this workstation — checked 2026-10-22

Evidence for the spec's engine table (README "Draft engines"). Sources: PyPI
JSON API (`/pypi/<pkg>/json`, latest release per package, x86_64 focus) and
the pacman repo DBs (CachyOS). Facts, not judgment — benchmarking decides
defaults (see README "Benchmarks").

## Python 3.14 wheels (system interpreter is 3.14.7, x86_64)

| Package | Latest | cp314 manylinux x86_64 wheel | requires_python | Verdict |
| --- | --- | --- | --- | --- |
| ctranslate2 | 4.8.3 | yes (+ cp314t) | >=3.9 | faster-whisper STT installs on system Python |
| faster-whisper | 1.2.1 | n/a (pure `py3-none-any`) | >=3.9 | works |
| onnxruntime | 1.31.0 | yes (+ cp314t) | >=3.11 | Piper/kokoro runtime installs |
| piper-tts | 1.8.0 | n/a (cp39-abi3 manylinux x86_64) | >=3.9 | abi3 → works on 3.14 |
| kokoro-onnx | 0.6.1 | — | >=3.10,**<3.14** | hard-capped below this VM's Python — out-of-VM testing confirmed |
| edge-tts | 7.3.1 | n/a (pure `py3-none-any`) | >=3.7 | works |

## pacman packages (CachyOS repos)

| Package | Repo / version | Relevance |
| --- | --- | --- |
| espeak-ng | cachyos-extra-v3 1.52.0 | zero-dep emergency TTS engine — one install |
| whisper.cpp | cachyos-extra-v3 1.9.5 / extra 1.9.5 | local STT alternative if chunked faster-whisper underperforms on CPU; binary + ggml models |
| piper | extra 0.8-5 | system-binary alternative to the piper-tts pip package |
| tk | cachyos-extra-v3 5.68 MiB | fixes the VM's broken tkinter (`libtk8.6.so` missing) for the listen dialog |

## Consequences for the spec

- The "Python 3.14 wheel support to verify" risk on faster-whisper and Piper
  is retired — both install cleanly on this workstation.
- Kokoro stays deferred exactly as specified; its Python cap is a hard PyPI
  constraint (`requires_python <3.14`), not a guess.
- whisper.cpp (pacman 1.9.5) is the designated local-STT plan B for the
  benchmark slate.
- The listen dialog's GUI toolkit needs a one-time `pacman -S tk` (~5.7 MiB).
