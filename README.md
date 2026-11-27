<p align="center"><img src="assets/brand/yi-yue-shi-logo.png" width="112" alt="E-Musician tree musician logo"></p>

# E-Musician

A Windows music workspace for recording, editing, and AI-assisted production.

Work on audio and MIDI in one arrangement. Ask the assistant to prepare a change, listen to the result, and decide what enters your project.

## What you can do

- **Record and arrange.** Record audio and MIDI, watch the waveform grow, edit clips and piano-roll notes, and export your work. The ruler and snap grid support detailed editing down to 1/16384.
- **Build a sound.** Use the 16-pad Drum Rack, Sampler, eight-band EQ, Compressor, Delay, Reverb, and Auto Filter. Load your own VST3 instruments and effects.
- **Work with an assistant.** Describe an edit in the sidebar. Review its proposal, apply it, or undo it. The assistant uses the same project commands as the interface.
- **Compare generated ideas.** Generate with ACE-Step or YuE2, preview each result, and add the take you want to keep.
- **Turn audio into editable material.** Separate stems, create a chord track, detect beats, apply tempo-aligned stretching, and transcribe piano to MIDI.

Music generation and model-based analysis use separately configured local or cloud workers. The DAW itself runs without an API account or cloud server.

## Get started

Download the Windows package from [Releases](https://github.com/TonyWang2182/E-Musician/releases/latest), extract it, and open `E-musician.exe`.

1. Open **Settings** and select your audio driver, device, and input channels.
2. Add an audio or MIDI track. Choose its input, enable **R**, and press the global record button. **Monitor** controls live input listening separately.
3. Open **Agent** to configure your model provider, or use the DAW directly.

The published version is **0.13.7**. See [Build from source](docs/BUILD.md) for the compiler and Python requirements.

## Set up AI tools

Bring your own API key for the assistant. Music generation and analysis use their own model workers; an assistant API key does not provide a GPU server.

- [API and SSH configuration](docs/CONFIGURATION.md)
- [Models and supported tasks](docs/MODELS.md)
- [Distributing model assets](docs/MODEL-ASSETS.md)

## Development

C++20, JUCE, and Tracktion Engine provide the desktop and audio engine. Python services handle assistant requests and model jobs outside the audio callback. [Architecture](docs/ARCHITECTURE.md) describes the command and worker boundaries.

[Contributing](CONTRIBUTING.md) · [Validation](docs/VALIDATION.md) · [License](LICENSE) · [Dependencies](THIRD_PARTY_NOTICES.md)

E-Musician is licensed under **AGPL-3.0-only**. Model weights, third-party plugins, and external SDKs retain their own licenses.
