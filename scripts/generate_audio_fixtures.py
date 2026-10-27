#!/usr/bin/env python3
"""Regenerate owned MP3 fixtures; lameenc is test tooling, never an app dependency.

On the recorded Windows toolchain:
  py -3.12 -m pip install --target .cache/fixture-encoder --no-deps lameenc==1.8.1
  py -3.12 scripts/generate_audio_fixtures.py
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
PINNED_ENCODER = "1.8.1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def syncsafe(number: int) -> bytes:
    return bytes((number >> 21 & 127, number >> 14 & 127, number >> 7 & 127, number & 127))


def id3(title: str) -> bytes:
    # ID3v2.3 text frames with UTF-16; no dependency on a tagging package.
    frames = bytearray()
    for key, value in ((b"TIT2", title), (b"TPE1", "E-musician synthetic fixtures"),
                       (b"TALB", "Generated signals; no user recording")):
        payload = b"\x01" + value.encode("utf-16-le")
        payload = payload[:1] + b"\xff\xfe" + payload[1:]
        frames += key + struct.pack(">I", len(payload)) + b"\0\0" + payload
    return b"ID3\x03\x00\x00" + syncsafe(len(frames)) + frames


def pcm(rate: int, channels: int, mode: str) -> bytes:
    result = bytearray()
    for index in range(rate * 2):
        seconds = index / rate
        for channel in range(channels):
            if mode == "cbr":
                sample = 0.2 * math.sin(math.tau * (220 + 110 * channel) * seconds)
            else:
                envelope = 0.75 + 0.25 * math.sin(math.tau * 4 * seconds)
                sample = envelope * (0.18 * math.sin(math.tau * 440 * seconds)
                                     + 0.04 * math.sin(math.tau * 880 * seconds))
            result += struct.pack("<h", round(sample * 32767))
    return bytes(result)


def inspect_frames(data: bytes) -> dict:
    """Validate the generated MPEG-1 Layer III frame structure and bitrate mode."""
    if data[:3] == b"ID3":
        offset = 10 + sum((value & 127) << shift for value, shift in zip(data[6:10], (21, 14, 7, 0)))
    else:
        offset = 0
    bitrates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
    rates = (44100, 48000, 32000)
    observed: set[int] = set()
    frame_count = 0
    while offset + 4 <= len(data):
        header = int.from_bytes(data[offset:offset + 4], "big")
        if header >> 21 != 0x7ff or header >> 19 & 3 != 3 or header >> 17 & 3 != 1:
            raise ValueError(f"Unexpected MPEG-1 Layer III header at byte {offset}")
        bitrate = bitrates[header >> 12 & 15]
        rate_index = header >> 10 & 3
        if bitrate == 0 or rate_index == 3:
            raise ValueError("Invalid MPEG audio parameters")
        rate = rates[rate_index]
        frame_size = 144000 * bitrate // rate + (header >> 9 & 1)
        if offset + frame_size > len(data):
            raise ValueError("Truncated encoded audio frame")
        observed.add(bitrate)
        frame_count += 1
        offset += frame_size
    if offset != len(data) or frame_count == 0:
        raise ValueError("Unexpected tail or empty MP3")
    return {"mpeg_frame_count": frame_count, "observed_bitrates_kbps": sorted(observed),
            "encoded_frame_duration_seconds": frame_count * 1152 / rate}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder-dir", type=Path, default=ROOT / ".cache/fixture-encoder")
    parser.add_argument("--output", type=Path, default=ROOT / "tests/fixtures/audio")
    args = parser.parse_args()
    sys.path.insert(0, str(args.encoder_dir.resolve()))
    import lameenc
    version = importlib.metadata.version("lameenc")
    if version != PINNED_ENCODER:
        raise RuntimeError(f"Expected lameenc {PINNED_ENCODER}, found {version}")
    args.output.mkdir(parents=True, exist_ok=True)
    cases = (("stereo-cbr-48000.mp3", 48000, 2, "cbr"), ("mono-vbr-44100.mp3", 44100, 1, "vbr"))
    assets = []
    for filename, rate, channels, mode in cases:
        source = pcm(rate, channels, mode)
        encoder = lameenc.Encoder()
        encoder.silence()
        encoder.set_in_sample_rate(rate)
        encoder.set_out_sample_rate(rate)
        encoder.set_channels(channels)
        encoder.set_quality(2)
        if mode == "cbr":
            encoder.set_bit_rate(128)
            encoder.set_vbr(lameenc.VBR_OFF)
        else:
            encoder.set_vbr(lameenc.VBR_MTRH)
            encoder.set_vbr_quality(4.0)
        encoded = id3(f"Synthetic {mode.upper()} {channels}-channel test") + encoder.encode(source) + encoder.flush()
        frames = inspect_frames(encoded)
        if mode == "vbr" and len(frames["observed_bitrates_kbps"]) < 2:
            raise RuntimeError("VBR fixture did not actually contain varying frame bitrates")
        if mode == "cbr" and frames["observed_bitrates_kbps"] != [128]:
            raise RuntimeError("CBR fixture did not remain at 128 kbps")
        (args.output / filename).write_bytes(encoded)
        assets.append({"file": filename, "sha256": digest(encoded), "bytes": len(encoded),
                       "sample_rate": rate, "channels": channels, "source_duration_seconds": 2.0,
                       "decoded_duration_tolerance_seconds": 0.12, "bitrate_mode": mode.upper(),
                       "source_pcm_s16le_sha256": digest(source), "id3_version": "2.3",
                       "frequencies_hz": [[220], [330]] if mode == "cbr" else [[440, 880]],
                       **frames})
        print(f"Generated {filename}: {len(encoded)} bytes; frame rates {frames['observed_bitrates_kbps']} kbps")
    encoder_path = Path(lameenc.__file__)
    manifest = {"schema": 1, "source": "Deterministic synthesized formula in scripts/generate_audio_fixtures.py",
                "audio_license": "CC0-1.0", "contains_user_audio": False,
                "encoder": {"package": "lameenc", "version": version,
                            "package_source": "https://pypi.org/project/lameenc/1.8.1/",
                            "source_repository": "https://github.com/chrisstaite/lameenc",
                            "binary_sha256": digest(encoder_path.read_bytes()),
                            "python": platform.python_version(), "platform": platform.system(),
                            "machine": platform.machine(), "runtime_dependency": False},
                "fixtures": assets}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
