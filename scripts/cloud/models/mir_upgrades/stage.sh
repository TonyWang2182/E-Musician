#!/usr/bin/env bash
set -euo pipefail
ROOT=/root/autodl-tmp/emusician
if [[ -f /etc/network_turbo ]]; then
    set +u
    source /etc/network_turbo >/dev/null 2>&1
    set -u
fi
export NO_PROXY="${NO_PROXY:-},mirrors.aliyun.com,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
export CUDA_VISIBLE_DEVICES=""
mkdir -p "$ROOT/logs/model-library"
for id in scnet transkun chordmini; do
    echo "Starting $id cloud-only assets UTC $(date -u +%FT%TZ)"
    timeout 1800 /root/miniconda3/bin/python "$ROOT/tools/models/mir_upgrades/stage.py" "$id"
done
