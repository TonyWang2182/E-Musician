#!/usr/bin/env bash
set -euo pipefail
ROOT=/root/autodl-tmp/emusician
BASE="$ROOT/workspace/models/yue2"
META="$ROOT/manifests/model-library/yue2"
SOURCE="$BASE/YuE-1116bea76032bee5668e5f097294d082fa0b84f0"
UV=/root/miniconda3/bin/uv
export UV_CACHE_DIR="$ROOT/cache/uv"
export UV_HTTP_TIMEOUT=120
export UV_CONCURRENT_DOWNLOADS=2
export TMPDIR="$BASE/tmp"
export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
mkdir -p "$TMPDIR" "$META"
if [[ -f /etc/network_turbo ]]; then
    set +u; source /etc/network_turbo >/dev/null 2>&1; set -u
fi
export NO_PROXY="${NO_PROXY:-},mirrors.aliyun.com,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
if [[ ! -x "$ROOT/envs/yue2/bin/python" ]]; then
    "$UV" venv --python /root/miniconda3/bin/python "$ROOT/envs/yue2"
fi
/root/miniconda3/bin/python "$BASE/stage.py" requirements
timeout 1200 "$UV" pip compile --quiet --python "$ROOT/envs/yue2/bin/python" --generate-hashes \
    --index-url https://mirrors.aliyun.com/pypi/simple "$BASE/requirements.in" -o "$META/environment.lock.txt"
timeout 1800 "$UV" pip sync --python "$ROOT/envs/yue2/bin/python" --require-hashes \
    --index-url https://mirrors.aliyun.com/pypi/simple "$META/environment.lock.txt"
timeout 180 "$UV" pip install --python "$ROOT/envs/yue2/bin/python" --no-deps --no-build-isolation "$SOURCE"
"$UV" pip check --python "$ROOT/envs/yue2/bin/python"
"$UV" pip freeze --python "$ROOT/envs/yue2/bin/python" > "$META/environment-freeze.txt"
"$ROOT/envs/yue2/bin/yue2" --help > "$META/cli-help.txt"
echo "YuE2 environment installed; no GPU model was loaded."
