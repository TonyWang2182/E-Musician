#!/usr/bin/env bash
set -euo pipefail
ROOT=/root/autodl-tmp/emusician
UV=/root/miniconda3/bin/uv
export UV_CACHE_DIR="$ROOT/cache/uv"
export UV_HTTP_TIMEOUT=120
export UV_CONCURRENT_DOWNLOADS=3
export TMPDIR="$ROOT/cache/tmp"
export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export MPLBACKEND=Agg
if [[ -f /etc/network_turbo ]]; then
    set +u
    source /etc/network_turbo >/dev/null 2>&1
    set -u
fi
export NO_PROXY="${NO_PROXY:-},mirrors.aliyun.com,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
for id in "$@"; do
    case "$id" in scnet|transkun|chordmini) ;; *) exit 2 ;; esac
    echo "Starting $id isolated environment UTC $(date -u +%FT%TZ)"
    "$UV" venv --allow-existing --python /root/miniconda3/bin/python "$ROOT/envs/$id"
    /root/miniconda3/bin/python "$ROOT/tools/models/mir_upgrades/requirements.py" "$id"
    folder="$ROOT/manifests/model-library/$id"
    if [[ ! -f "$folder/requirements.lock.txt" ]]; then
        timeout 900 "$UV" pip compile --quiet --python "$ROOT/envs/$id/bin/python" \
            --generate-hashes --index-url https://mirrors.aliyun.com/pypi/simple \
            "$folder/requirements.in" -o "$folder/requirements.lock.txt"
    fi
    timeout 1200 "$UV" pip sync --python "$ROOT/envs/$id/bin/python" \
        --require-hashes --index-url https://mirrors.aliyun.com/pypi/simple "$folder/requirements.lock.txt"
    "$UV" pip check --python "$ROOT/envs/$id/bin/python"
    "$UV" pip freeze --python "$ROOT/envs/$id/bin/python" > "$folder/environment-freeze.txt"
    timeout 300 "$ROOT/envs/$id/bin/python" "$ROOT/tools/models/mir_upgrades/runtime.py" "$id" --check
    echo "Finished $id CPU stage UTC $(date -u +%FT%TZ)"
done
