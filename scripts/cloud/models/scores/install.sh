#!/usr/bin/env bash
# Assigned cloud environments only; no GPU, DAW, gateway or system-package changes.
set -euo pipefail
MODEL="${1:?Choose sheetsage2 or muscriptor}"
case "$MODEL" in sheetsage2|muscriptor) ;; *) exit 2;; esac
ROOT=/root/autodl-tmp/emusician
WORK="$ROOT/workspace/models/$MODEL"
MANIFEST="$ROOT/manifests/model-library/$MODEL"
UV=/root/miniconda3/bin/uv
export UV_CACHE_DIR="$WORK/uv-cache"
export UV_PYTHON_INSTALL_DIR="$WORK/python"
export UV_HTTP_TIMEOUT=120
export UV_CONCURRENT_DOWNLOADS=3
export TMPDIR="$WORK/tmp"
export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
export HF_HOME="$WORK/hf"
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1
if [[ -f /etc/network_turbo ]]; then
    set +u
    source /etc/network_turbo >/dev/null 2>&1
    set -u
fi
export NO_PROXY="${NO_PROXY:-},mirrors.aliyun.com,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
mkdir -p "$WORK" "$TMPDIR" "$MANIFEST"
echo "Scores environment $MODEL start $(date -u +%FT%TZ)"
/root/miniconda3/bin/python -c 'import shutil; assert shutil.disk_usage("/root/autodl-tmp/emusician").free > 65_000_000_000, "Need 50GB reserve plus environment staging budget"'
if [[ "$MODEL" == sheetsage2 ]]; then
    if [[ ! -x "$ROOT/envs/$MODEL/bin/python" ]]; then
        timeout 600 "$UV" python install --no-bin 3.11.14
        "$UV" venv --python 3.11.14 --managed-python "$ROOT/envs/$MODEL"
    fi
else
    if [[ ! -x "$ROOT/envs/$MODEL/bin/python" ]]; then
        "$UV" venv --python /root/miniconda3/bin/python "$ROOT/envs/$MODEL"
    fi
fi
export SCORES_MODEL="$MODEL"
/root/miniconda3/bin/python - <<'PY'
import os
from pathlib import Path
import tomllib
root = Path('/root/autodl-tmp/emusician')
name = os.environ['SCORES_MODEL']
if name == 'sheetsage2':
    lines = [line for line in (root/'models/sheetsage2/requirements.txt').read_text().splitlines()
             if line and not line.startswith(('torch==', 'torchaudio=='))]
    # Official PyPI 2.8 Linux distribution uses CUDA12.8. The final generated
    # hash lock preserves its distinct distribution hashes; it is not the
    # separately packaged +cu128-index wheel from the interrupted attempt.
    lines += ['torch==2.8.0', 'torchaudio==2.8.0',
              'soundfile==0.13.1', 'psutil==7.1.0']
else:
    source = root/'workspace/models/muscriptor/source/pyproject.toml'
    project = tomllib.loads(source.read_text())['project']
    lines = [line for line in project['dependencies'] if not line.startswith('torch')]
    # Read-only reuse of exact already validated PyTorch coordinates. Other
    # dependencies resolve into this private environment and its private cache.
    lines += [line for line in (root/'workspace/mir-stage/torch.in').read_text().splitlines()
              if line.startswith(('torch @', 'torchaudio @'))]
    lines += ['hatchling==1.27.0']
(root/'workspace/models'/name/'requirements.in').write_text('\n'.join(lines)+'\n')
PY
PYTHON="$ROOT/envs/$MODEL/bin/python"
INPUT="$WORK/requirements.in"
LOCK="$MANIFEST/environment.lock.txt"
timeout 1500 "$UV" pip compile --quiet --python "$PYTHON" --generate-hashes \
    --index-url https://mirrors.aliyun.com/pypi/simple --find-links "$ROOT/cache/wheels" "$INPUT" -o "$LOCK"
timeout 1800 "$UV" pip sync --python "$PYTHON" --require-hashes \
    --index-url https://mirrors.aliyun.com/pypi/simple --find-links "$ROOT/cache/wheels" "$LOCK"
if [[ "$MODEL" == muscriptor ]]; then
    timeout 180 "$UV" pip install --python "$PYTHON" --no-deps --no-build-isolation "$WORK/source"
fi
"$UV" pip check --python "$PYTHON"
"$UV" pip freeze --python "$PYTHON" > "$MANIFEST/environment.freeze.txt"
# CPU load/CLI checks run as a separately recorded step after model-file staging
# completes; installation alone must not set any readiness flag.
echo "Scores environment $MODEL finish $(date -u +%FT%TZ)"
