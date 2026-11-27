#!/usr/bin/env bash
# Resume from an existing hash lock; stage each script under a unique filename.
set -euo pipefail
MODEL="${1:?Choose sheetsage2 or muscriptor}"
case "$MODEL" in sheetsage2|muscriptor) ;; *) exit 2;; esac
ROOT=/root/autodl-tmp/emusician
WORK="$ROOT/workspace/models/$MODEL"
MANIFEST="$ROOT/manifests/model-library/$MODEL"
UV=/root/miniconda3/bin/uv
PYTHON="$ROOT/envs/$MODEL/bin/python"
export UV_CACHE_DIR="$WORK/uv-cache" TMPDIR="$WORK/tmp" CUDA_VISIBLE_DEVICES=""
export UV_HTTP_TIMEOUT=120 UV_CONCURRENT_DOWNLOADS=3
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
export HF_HOME="$WORK/hf" HF_HUB_OFFLINE=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_TELEMETRY=1
if [[ -f /etc/network_turbo ]]; then
  set +u
  source /etc/network_turbo >/dev/null 2>&1
  set -u
fi
export NO_PROXY="${NO_PROXY:-},mirrors.aliyun.com,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
echo "Scores resume $MODEL start $(date -u +%FT%TZ)"
test -s "$MANIFEST/environment.lock.txt"
timeout 1800 "$UV" pip sync --python "$PYTHON" --require-hashes --index-url https://mirrors.aliyun.com/pypi/simple --find-links "$ROOT/cache/wheels" "$MANIFEST/environment.lock.txt"
if [[ "$MODEL" == muscriptor ]]; then
  timeout 180 "$UV" pip install --python "$PYTHON" --no-deps --no-build-isolation "$WORK/source"
fi
"$UV" pip check --python "$PYTHON"
"$UV" pip freeze --python "$PYTHON" > "$MANIFEST/environment.freeze.txt"
echo "Scores resume $MODEL finish $(date -u +%FT%TZ)"
