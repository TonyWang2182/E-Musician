# Cloud score-model deployment

These scripts run only under `/root/autodl-tmp/emusician` on the rented Linux host. They do not connect models to the DAW. Never run model downloads on the Windows development computer or copy weights/audio back to E: for this phase.

`artifacts.json` pins reviewed upstream source/model identities. `stage.py stage --model sheetsage2` obtains and verifies the adapter and MERT2 parent; the MuScriptor mode obtains public source and records one anonymous access check without bypassing gated weights. `install.sh` prepares separate environments with exact, generated hash locks. Stage scripts under a unique immutable name per attempt; do not overwrite files that a running shell may still read. `finalize.sh` resumes an existing completed lock without silently resolving new versions.

SheetSage2 uses Python 3.11.14, upstream Torch/Torchaudio 2.8.0 and its pinned dependencies. The successful path uses official PyPI Linux distributions (CUDA 12.8) through a transport mirror. These hashes differ from the separate `2.8.0+cu128` index wheels from the preserved slow-transfer attempts. MuScriptor uses its own Python 3.12 environment and pinned 2.10 CUDA 12.8 distribution; it remains weight-blocked until the user has established model access and accepted applicable terms.

`toolchain.py` verifies a public FFmpeg wheel before extracting its binary into the SheetSage2 workspace. Only `run_sheetsage2.sh` adds that directory to its own PATH. It does not install system packages. The wrapper runs the actual upstream CLI offline, for example:

```sh
bash /root/autodl-tmp/emusician/workspace/models/sheetsage2/deploy/run_sheetsage2-v1.sh --help
# Only when the GPU scheduler has granted exclusive model work:
bash /root/autodl-tmp/emusician/workspace/models/sheetsage2/deploy/run_sheetsage2-v1.sh \
  /cloud/input.wav --output /cloud/output --device cuda --dtype bf16
```

`stage.py cpu-check` requires `CUDA_VISIBLE_DEVICES=''`. SheetSage2 loads both actual weight sets, verifies CPU placement and default WAV decoding, and invokes upstream CLI help. MuScriptor only imports public model code and checks CLI help; this cannot establish weight loading or inference.

`gpu_probe.py --approved-slot` is a bounded smoke check after explicit coordinator authorization. It requires ACE idle and at least 12 GiB free VRAM, caps its PyTorch allocator to 10 GiB, and stops only its own child if ACE work arrives, VRAM falls below 1 GiB, or 180 seconds elapse. The existing cloud audio is cropped to8 seconds, but the original model still pads its encoder window to300 seconds. Default prompts, BF16 and SDPA are retained. Output validation is structural and finite/bounds based, not accuracy or listening evaluation. The wrapper itself is not a scheduler.

The completed real GPU check ran immutable `gpu_probe-v1.py` (SHA256 `e9c1d4a7924b9418f3e0cb37fc141847ee4c4675826cc337d86bca84a00bfecf`). Final `gpu_probe-final-v3.py` (SHA256 `aeb829ca161770d7c478126ad9a01d95535b619645de6281aea3408aaeb9ec25`) subsequently hardened admission/error/cleanup receipts and passed seven CPU-only fault tests; it was not rerun on GPU. Both hashes are retained in `deployment.json.guard_evidence`. Future output is under `results/model-library/sheetsage2/`; the first probe's original `workspace/models/sheetsage2/probes/20261106T103753Z` evidence remains in place.

SheetSage2 exports ABC, MIDI and annotations; optional PDF/image/audio rendering assets and tools are not deployed. `paper` preset's torchaudio FFmpeg shared-library backend remains unverified. Both model families' noncommercial weight licenses and MuScriptor access conditions remain applicable. All per-model readiness flags and file hashes live in cloud `manifests/model-library/<id>/deployment.json`; small copies may be archived in the review folder.
