#!/usr/bin/env bash
# Explicit standalone CLI; no DAW integration and no server is started here.
set -euo pipefail
ROOT=/root/autodl-tmp/emusician
BASE="$ROOT/workspace/models/yue2"
MODEL="$ROOT/models/yue2/YuE2-3B/8f24312f187763b9854adeec87e437e2b03bbff1"
VAE="$ROOT/models/yue2/YuE2-Vae/152733a19ad43aa67e367f9b5503ef8075bb5126"
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export YUE2_COMPILE=0
command="${1:-doctor}"
if [[ $# -gt 0 ]]; then shift; fi
if [[ "$command" == doctor ]]; then
    export CUDA_VISIBLE_DEVICES=""
    exec timeout 180 "$ROOT/envs/yue2/bin/yue2" doctor --model "$MODEL" --vae "$VAE" --device cpu --backend torch-eager --offline --verify-hashes "$@"
fi
if [[ "$command" != generate ]]; then
    echo 'Use doctor or generate. For all upstream options: envs/yue2/bin/yue2 --help' >&2; exit 2
fi
if [[ "${EMUSICIAN_YUE2_GPU_ALLOWED:-0}" != 1 ]]; then
    echo 'Generation requires an explicitly assigned serialized GPU slot. No model was loaded.' >&2; exit 3
fi
exec timeout --signal=TERM --kill-after=15 900 "$ROOT/envs/yue2/bin/yue2" generate \
    --model "$MODEL" --vae "$VAE" --device cuda --budget 24 --backend torch-eager --offline "$@"
