#!/usr/bin/env bash
# Separate environments only. Never starts/restarts the gateway or invokes model inference.
set -euo pipefail
ROOT=/root/autodl-tmp/emusician
UV=/root/miniconda3/bin/uv
export UV_CACHE_DIR="$ROOT/cache/uv"
export UV_HTTP_TIMEOUT=120
export UV_CONCURRENT_DOWNLOADS=4
export TMPDIR="$ROOT/cache/tmp"
export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
if [[ -f /etc/network_turbo ]]; then
    set +u
    source /etc/network_turbo >/dev/null 2>&1
    set -u
fi
export NO_PROXY="${NO_PROXY:-},mirrors.aliyun.com,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
mkdir -p "$ROOT/workspace/mir-stage" "$TMPDIR"
echo "MIR stage started UTC $(date -u +%FT%TZ)"
/root/miniconda3/bin/python "$ROOT/tools/mir_stage.py" verify
for name in mir-torch mir-transcription; do
    if [[ ! -x "$ROOT/envs/$name/bin/python" ]]; then
        "$UV" venv --python /root/miniconda3/bin/python "$ROOT/envs/$name"
    fi
done
# The pinned ACE lock provides only immutable artifact coordinates; ACE is not modified.
/root/miniconda3/bin/python "$ROOT/tools/mir_requirements.py"
for name in torch transcription; do
    python="$ROOT/envs/mir-$name/bin/python"
    input="$ROOT/workspace/mir-stage/$name.in"
    lock="$ROOT/manifests/mir-$name.lock.txt"
    if [[ ! -f "$lock" ]]; then
        timeout 1200 "$UV" pip compile --quiet --python "$python" --generate-hashes \
            --index-url https://mirrors.aliyun.com/pypi/simple "$input" -o "$lock"
    fi
    timeout 1200 "$UV" pip sync --python "$python" --require-hashes \
        --index-url https://mirrors.aliyun.com/pypi/simple "$lock"
done
# Upstream BasicPitch auto-selects TensorFlow on Python>=3.11. This explicitly deploys
# its supported ONNX backend instead; all non-backend requirements are locked above.
timeout 300 "$UV" pip install --python "$ROOT/envs/mir-transcription/bin/python" \
    --no-deps --require-hashes -r "$ROOT/manifests/mir-basic-pitch-overlay.lock.txt"
"$UV" pip check --python "$ROOT/envs/mir-torch/bin/python"
for name in torch transcription; do
    "$UV" pip freeze --python "$ROOT/envs/mir-$name/bin/python" > "$ROOT/manifests/mir-$name-freeze.txt"
done
timeout 300 "$ROOT/envs/mir-torch/bin/python" "$ROOT/tools/mir_stage.py" cpu-check --backend torch
timeout 300 "$ROOT/envs/mir-transcription/bin/python" "$ROOT/tools/mir_stage.py" cpu-check --backend onnx
/root/miniconda3/bin/python "$ROOT/tools/mir_stage.py" finalize
echo "MIR stage finished UTC $(date -u +%FT%TZ)"
