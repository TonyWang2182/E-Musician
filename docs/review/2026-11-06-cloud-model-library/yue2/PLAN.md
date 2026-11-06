# YuE2 cloud-only deployment

Status: cloud files, isolated environment and real CPU weight loading verified. One bounded official low-VRAM GPU probe produced validated audio; semantic generation reached its deliberate token cap. This does not validate complete songs, listening quality or the default 24GiB path. Evidence: [RESULTS.md](RESULTS.md). No DAW connection is part of this task. Model weights, generated audio and backups remain on the cloud instance; only small deployment scripts, locks and evidence return to this repository.

## Locked inputs

- Official source: `multimodal-art-projection/YuE` commit `1116bea76032bee5668e5f097294d082fa0b84f0`, package `yue2-infer==0.1.6`.
- Generator: `m-a-p/YuE2-3B` revision `8f24312f187763b9854adeec87e437e2b03bbff1`.
- Listening VAE: `m-a-p/YuE2-Vae` revision `152733a19ad43aa67e367f9b5503ef8075bb5126`.
- Independent Python3.12 environment, official PyTorch eager path, `torch==2.10.0+cu128`, Transformers4.57.6. Optional vLLM is not installed. Existing ACE wheel coordinates are reused read-only and their SHA hashes rechecked.
- Source uses Apache-2.0; checkpoints use CC-BY-NC-4.0 with additional individual-creator and academic grants in the pinned `MODEL_LICENSE`. This deployment does not certify unrestricted commercial hosting.

## Boundaries and stages

1. Cloud download only. Pin HF revisions and verify LFS SHA256 or Git blob hash; record independent SHA256, size and path for every runtime/config/license file. Keep at least50GB cloud free-space reserve. No example songs, older decoder or duplicate inference wheels are needed.
2. Hash-locked isolated environment. Record exact upstream source files, resolved dependency lock and installed freeze. No changes to ACE, its service or its registry.
3. CPU import and real generator/decoder weight loading, with CUDA hidden; no generation. Record memory, elapsed time, actual dependencies and official CLI doctor output.
4. After the parent assigns the single GPU slot, perform one bounded generation probe using explicit local paths and no model downloads during execution. Until then `gpu_inference_verified=false`.
5. Publish per-model `deployment.json`. Root owns aggregation; individual deployment must not mutate the shared registry or DAW.

## Locations and entrypoints

Remote base `/root/autodl-tmp/emusician`:

| Contents | Path |
|---|---|
| Generator + decoder | `models/yue2/<model>/<revision>` |
| Environment | `envs/yue2` |
| Source and scripts | `workspace/models/yue2` |
| Locks, manifests, checks | `manifests/model-library/yue2` |
| Operation logs | `logs/model-library/yue2` |
| Future probe results | `results/model-library/yue2/probe-<UTC timestamp>` |

The already-verified 20261106T102323Z probe retains its original `workspace/models/yue2/probes/20261106T102323Z` evidence path. It was not moved or deleted during the output-directory cleanup.

The tracked transport entry is `scripts/cloud/models/yue2/record.py`: `upload`, `source`, `weights`, `install`, `tests`, `cpu`, `guard-tests`, authorized `gpu`, `finalize`, then `collect` (metadata only). Each operation uses the project's Recorder. Cloud `run.sh doctor` checks pinned local files on CPU; `run.sh generate` requires an explicitly assigned GPU slot and has a15-minute process ceiling. The runtime is not a shared GPU scheduler. `gpu_smoke.py` uses the shared exclusive GPU lock, checks the read-only ACE job queue, requires 12GiB free at admission, and stops only its owned child if ACE becomes active, free memory falls below 1GiB, or 180seconds elapse. The one authorized probe has finished and released this lock; rerunning requires a new slot assignment.

Primary sources: [official source at pinned commit](https://github.com/multimodal-art-projection/YuE/tree/1116bea76032bee5668e5f097294d082fa0b84f0), [hardware guidance](https://github.com/multimodal-art-projection/YuE/blob/1116bea76032bee5668e5f097294d082fa0b84f0/docs/hardware.md), [generator](https://huggingface.co/m-a-p/YuE2-3B/tree/8f24312f187763b9854adeec87e437e2b03bbff1), [VAE](https://huggingface.co/m-a-p/YuE2-Vae/tree/152733a19ad43aa67e367f9b5503ef8075bb5126).
