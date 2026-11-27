# Models

Model environments are installed separately from the DAW. Results appear as
candidates for preview and explicit acceptance. Start with
[Configuration](CONFIGURATION.md) to install local workers or connect a server.

## Local workers

| Worker | Result | Notes |
| --- | --- | --- |
| [HTDemucs](https://huggingface.co/adefossez/HTDemucs) / [HTDemucs-6s](https://huggingface.co/adefossez/HTDemucs-6s) | Four or six audio stems | Piano/guitar separation is experimental. Code is MIT; this project has not cleared checkpoint redistribution. |
| [Basic Pitch 0.4.0](https://github.com/spotify/basic-pitch) | Pitched audio to MIDI notes | No drum classification or pitch-bend export. Apache-2.0 source and bundled model. |
| Chroma/HMM | Chord-label candidates | Original NumPy/SciPy template baseline; similarity scores are not calibrated confidence. |
| [Beat This! final0](https://github.com/CPJKU/beat_this) | Beats and downbeats for fixed-ratio Warp | No local Warp markers or variable tempo map. MIT source and checkpoint terms. |

`scripts/setup_analysis.py` installs Python 3.10.19 environments. Separation and
beats use Torch 2.5.1 (CPU or CUDA 12.4); transcription uses ONNX Runtime 1.20.1.
Exact packages are in `scripts/audio_analysis/requirements-*.txt`. Registration
records source revisions, hashes and probe results. HTDemucs resolves its
upstream revision on first setup and reuses it on subsequent runs.

## Cloud workers

| Model | Result | Notes |
| --- | --- | --- |
| [ACE-Step 1.5 XL Turbo + 1.7B LM](https://github.com/ACE-Step/ACE-Step-1.5) | Audio from text and lyrics | 10–120 seconds; BPM and meter guide generation. |
| [YuE2 3B](https://huggingface.co/m-a-p/YuE2-3B) + [VAE](https://huggingface.co/m-a-p/YuE2-Vae) | Audio from text and lyrics | A token limit can truncate the result; the candidate reports truncation. |
| [SCNet XL IHF](https://github.com/ZFTurbo/Music-Source-Separation-Training) | Vocals, drums, bass and other stems | Four-stem model. |
| [TransKun V2](https://github.com/Yujia-Yan/Transkun) | Piano MIDI and emitted pedal events | Piano-specific transcription. |
| [ChordMini BTC](https://github.com/ptnghia-j/ChordMini) | Chord timeline | Fixed 170-label vocabulary. |
| [MuScriptor medium](https://huggingface.co/MuScriptor/muscriptor-medium) | Multiple instrument note tracks | Exported velocity and MIDI tempo use defaults, rather than inferred dynamics or tempo. |
| [SheetSage2](https://huggingface.co/m-a-p/SheetSage2) + MERT2 | Notes, chords, beats, structure and symbolic scores | Optional score rendering tools are not included. |

Cloud tasks accept up to 600 seconds of analysis input or 120 seconds of
generation. One heavy task runs at a time. Admission requires the model's GPU
budget plus 1 GiB free VRAM, 8 GiB available host memory and 3 GiB free job
storage. Model budgets range from 8 to 22 GiB in
`scripts/cloud/compute/protocol.py`; they are admission thresholds, not measured
hardware recommendations.

YuE2, SheetSage2 and MuScriptor have noncommercial weight terms; MuScriptor also
requires accepting its access conditions. Obtain weights under the publisher's
terms for the selected revision. E-musician's source license does not relicense
them. See [Model assets](MODEL-ASSETS.md) for redistribution guidance.

## Deploy a server

Server setup is a manual Linux x86_64/NVIDIA workflow. The supplied tools use
`/root/autodl-tmp/emusician` for data, `/root/miniconda3/bin/python` for the base
interpreter, and separate environments under `envs/`. Prepare NVIDIA drivers,
`ffmpeg`, `uv`, Python 3.12 and space for the selected models. SheetSage2 uses a
separate Python 3.11.14 environment. A fresh all-model installation has not been
revalidated for this release.

1. Stage model setup scripts and adapters under `<data-root>/tools`, preserving
   `tools/models/`. The service deployment checks that `tools/ace_worker.py` and
   `tools/models/mir_upgrades/runtime.py` match this source revision. On a new
   server, leave `tools/compute` and `tools/compute_start.py` absent: the installer
   creates these as links to a versioned release. On an existing server, preserve
   its installer-managed links.

2. Prepare the selected models using their staging/install scripts:
   `models/yue2/stage.py`, `models/mir_upgrades/stage.py`, and
   `models/scores/artifacts.json` pin the respective sources and checkpoints.
   ACE tools pin source commit `ca1e85fe9430179831e6bc6be790c332190a3866` and use
   an operator-supplied model manifest. Some installers require staged wheels or
   source packages; inspect each model's prerequisites before running it.

3. Run each model's environment checks and a short GPU inference. Record results
   in `manifests/model-library/<model>/deployment.json`; ACE uses
   `manifests/ace-runtime.json` and `ace-runtime-model-files.json`. A server can
   expose a subset of models with valid readiness records.

4. From the desktop source checkout, activate the compute service:

   ```powershell
   python scripts/deploy_compute.py --ssh-alias emusician-cloud
   ```

   This uploads a versioned service release, verifies the staged adapters,
   creates or updates the managed links, and starts the service. It does not
   install models. Activation requires an idle queue and refuses to replace an
   unmanaged `tools/compute` directory or `tools/compute_start.py` file.

5. Check `/health` and `/capabilities` through SSH, then
   [register the desktop](CONFIGURATION.md#ssh-compute-server). Registration
   checks service readiness; run a short task for each enabled model to verify
   inference, preview, acceptance, Undo and save/reopen on your installation.

Model inference runs outside the audio callback. Keep the HTTP service bound to
loopback and access it through SSH. Linux environment archives are separate
from the portable Windows application; see [Model assets](MODEL-ASSETS.md) before
copying or distributing them.