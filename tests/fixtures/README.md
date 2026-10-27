# Audio fixtures

These short MP3 files are generated signals, with no user music or downloaded recordings. The application and normal test run read the committed fixtures directly; neither Python `lameenc` nor FFmpeg is needed by the application.

| File | Original signal | Encoding |
|---|---|---|
| `audio/stereo-cbr-48000.mp3` | 2 seconds, 48 kHz, L=220 Hz / R=330 Hz sine, amplitude 0.2 | Stereo, CBR 128 kbps, ID3v2.3 text frames |
| `audio/mono-vbr-44100.mp3` | 2 seconds, 44.1 kHz, 440/880 Hz with a 4 Hz amplitude envelope | Mono, LAME MTRH VBR quality 4, ID3v2.3 text frames |

[manifest.json](audio/manifest.json) records exact asset hashes, source PCM hashes, sample rate/channels, MPEG frame counts, and observed frame bitrates. The VBR file actually contains multiple bitrates; it is not merely labelled VBR. Tests should allow 0.12 seconds around the two-second source duration for encoder delay/padding and decoder handling. Do not compare MP3 output sample-for-sample against the input PCM: it is lossy.

Suggested integration coverage: decode both files; import each through the engine; verify non-silent output and channel/sample-rate metadata; seek and loop; copy a fixture to a Unicode/space-containing filename and import it; ensure a corrupt MP3 does not replace existing tracks. The manifest does not claim these application checks have run.

## Regenerate

The recorded encoder is the [lameenc 1.8.1 PyPI release](https://pypi.org/project/lameenc/1.8.1/), from [chrisstaite/lameenc](https://github.com/chrisstaite/lameenc). Generation was performed with Python 3.12.6 on Windows x64. The exact `cp312-win_amd64` wheel SHA-256 is pinned in [encoder-requirements.txt](encoder-requirements.txt); the loaded binary hash is recorded in the manifest. Other platforms may produce different encoded bytes and require explicit review of changed fixtures/hashes.

From the project root:

```powershell
py -3.12 -m pip install --target .cache/fixture-encoder --no-deps --require-hashes -r tests/fixtures/encoder-requirements.txt
py -3.12 scripts/generate_audio_fixtures.py
```

The encoder is installed only in ignored `.cache/fixture-encoder`, not globally. The generator uses standard-library PCM synthesis, adds ID3 frames, and validates every MPEG frame and bitrate mode. Regeneration to an alternate `--output` directory allows byte-for-byte comparison before replacing fixtures.

The generated audio material is dedicated under CC0-1.0; see [AUDIO-LICENSE.txt](AUDIO-LICENSE.txt). The encoder package has its own LGPLv3 license, copied from its pinned wheel to [tool-licenses/lameenc-LICENSE.txt](tool-licenses/lameenc-LICENSE.txt). That package license is not the license of the synthetic recordings, and the encoder binary is not committed or linked into the app. The generator does not expose an independent bundled LAME version; the package version, wheel hash, and binary hash are the reproducibility identifiers.
