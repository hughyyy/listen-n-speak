"""Audio normalization tests: input triple, WAV conversion, transcoding."""

import base64
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from listen_n_speak.audio import (
    AudioInputError,
    load_audio,
    prepare,
    probe_duration,
    to_wav,
    transcode,
)


def write_sine(path: Path, seconds: float = 0.5, rate: int = 16000, freq: float = 440.0) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(int(rate * seconds))
        )
        handle.writeframes(frames)
    return path


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp(prefix="lns-test-"))

    def test_data_uri(self):
        raw = b"RIFFfakewavbytes"
        uri = "data:audio/wav;base64," + base64.b64encode(raw).decode()
        path = load_audio(uri, self.workdir)
        self.assertEqual(path.read_bytes(), raw)

    def test_missing_file(self):
        with self.assertRaises(AudioInputError):
            load_audio("/nonexistent/x.wav", self.workdir)

    def test_empty_source(self):
        with self.assertRaises(AudioInputError):
            load_audio("   ", self.workdir)

    def test_malformed_data_uri(self):
        with self.assertRaises(AudioInputError):
            load_audio("data:audio/wav,not-base64", self.workdir)

    def test_bad_base64(self):
        with self.assertRaises(AudioInputError):
            load_audio("data:audio/wav;base64,@@@@", self.workdir)

    def test_path_input(self):
        wav = write_sine(self.workdir / "src.wav")
        self.assertEqual(load_audio(str(wav), self.workdir), wav)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp(prefix="lns-test-"))

    def test_wav_normalized_to_16k_mono(self):
        src = write_sine(self.workdir / "src.wav", seconds=0.5, rate=44100)
        wav, duration = prepare(str(src), self.workdir)
        self.assertAlmostEqual(duration, 0.5, delta=0.1)
        with wave.open(str(wav), "rb") as handle:
            self.assertEqual(handle.getframerate(), 16000)
            self.assertEqual(handle.getnchannels(), 1)

    def test_non_audio_rejected(self):
        junk = self.workdir / "junk.wav"
        junk.write_text("this is not audio")
        with self.assertRaises(AudioInputError):
            prepare(str(junk), self.workdir)

    def test_probe_duration(self):
        src = write_sine(self.workdir / "src.wav", seconds=1.0)
        self.assertAlmostEqual(probe_duration(src), 1.0, delta=0.1)

    def test_transcode_to_mp3(self):
        src = write_sine(self.workdir / "src.wav")
        dest = transcode(src, self.workdir / "out.mp3", "mp3")
        self.assertTrue(dest.is_file())
        self.assertGreater(dest.stat().st_size, 0)
        self.assertAlmostEqual(probe_duration(dest), 0.5, delta=0.2)

    def test_transcode_unsupported_format(self):
        src = write_sine(self.workdir / "src.wav")
        with self.assertRaises(AudioInputError):
            transcode(src, self.workdir / "out.xyz", "xyz")


if __name__ == "__main__":
    unittest.main()
