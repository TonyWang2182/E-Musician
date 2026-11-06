# SheetSage2 and MuScriptor cloud preparation

Status: SheetSage2/MERT2 files, environment, CPU load and one guarded real GPU smoke verified; MuScriptor public source/environment verified but gated weights blocked. Evidence and retained limitations are in [RESULTS](RESULTS.md). Parent phase `feature/cloud-model-library`, baseline `01936fa`. Scope is cloud deployment only: no DAW integration, existing service changes, or new weights/audio/backups on E:. Only source scripts, small manifests and logs return to the development repository.

## Fixed sources and paths

| Component | Fixed source | Cloud path |
| --- | --- | --- |
| SheetSage2 adapter and custom code | `m-a-p/SheetSage2@b83c3d79a6d98bcffaf8f9ed112c90aa887887bc` | `models/sheetsage2`, `envs/sheetsage2`, `workspace/models/sheetsage2` |
| MERT2 FullSong parent | `m-a-p/MERT-v2-FullSong@d8ba1c745e733b3908ce6ad16ebeb17ac7600a42` | `models/mert2` |
| MuScriptor implementation | `muscriptor/muscriptor@8a1ef88672cc23c26619adaff37ec48d82c0b906` | `workspace/models/muscriptor`, `envs/muscriptor` |
| MuScriptor medium | `MuScriptor/muscriptor-medium@f32236969308476e01fd3aae67357de5feb05a2d` | `models/muscriptor` if access permits |

All cloud paths are under `/root/autodl-tmp/emusician`. Each model gets a separate `manifests/model-library/<id>/deployment.json`. Large MuScriptor is not downloaded speculatively; medium access and compatibility come first.

## Execution sequence

1. Inspect official model cards, requirements, custom loaders, subprocess/download boundaries and exact hashes. Save a fixed artifact plan; all model downloads run cloud-side and verify byte size plus SHA-256 (or Git blob identity for ordinary source files).
2. Confirm MuScriptor's anonymous weight access. If gated, record the access block without accepting terms, finding arbitrary credentials or using a mirror to bypass it. Public implementation and environment can still be prepared.
3. Build isolated, hash-locked environments. SheetSage2's upstream NumPy 1.24.3 needs Python 3.11; use matching Torch/Torchaudio 2.8 CUDA 12.8 wheels for RTX5090 compatibility. MuScriptor can use Python 3.12 and the already pinned Torch 2.10 coordinates in a separate environment. Preserve upstream defaults and record all compatibility deviations.
4. Check imports, upstream CLI `--help`, dependency consistency and CPU-only model loading. `CUDA_VISIBLE_DEVICES` stays empty until the parent explicitly serializes a GPU test. Do not start servers or modify ACE/gateway.
5. Record actual states, source/artifact hashes, environment lock/freeze, failed attempts and start/end timestamps. Maintain at least 50 GB free cloud disk. Installation, CPU loading, GPU inference, output quality and DAW integration remain separate evidence levels.

## Review findings and retained limits

SheetSage2 is a lead-sheet/structured annotation model, not complete multi-instrument score recovery. Its loader checks the pinned MERT2 parent hashes and accepts an explicit local parent path. Audio decoding uses bounded FFmpeg subprocess calls; optional score/audio rendering has separate assets and tools and is not implied by successful transcription setup. Both model families' weights are CC-BY-NC-4.0; MuScriptor also has gated access conditions. MuScriptor does not infer true note velocity (MIDI exporter default is 100), and drums encode onsets. No commercial clearance or arbitrary-song accuracy claim follows from installation.

Official references: [SheetSage2](https://huggingface.co/m-a-p/SheetSage2), [MERT2](https://huggingface.co/m-a-p/MERT-v2-FullSong), [MuScriptor model card](https://huggingface.co/MuScriptor/muscriptor-medium), [MuScriptor code](https://github.com/muscriptor/muscriptor).
