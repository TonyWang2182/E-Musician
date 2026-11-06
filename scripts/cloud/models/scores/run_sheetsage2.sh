#!/usr/bin/env bash
# File input -> upstream ABC/MIDI/LAB output. Cloud-only; scheduling is external.
set -euo pipefail
ROOT=/root/autodl-tmp/emusician
test -d "$ROOT/models/sheetsage2"
export HF_HOME="$ROOT/workspace/models/sheetsage2/hf"
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_TELEMETRY=1
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
export PATH="$ROOT/workspace/models/sheetsage2/toolchain/bin:$PATH"
exec "$ROOT/envs/sheetsage2/bin/python" "$ROOT/models/sheetsage2/infer.py" --local-files-only "$@"
