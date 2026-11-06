#!/usr/bin/env bash
set -euo pipefail
ROOT=/root/autodl-tmp/emusician
COMMIT=ca1e85fe9430179831e6bc6be790c332190a3866
SOURCE="$ROOT/workspace/third_party/ACE-Step-1.5-$COMMIT"
export UV_PROJECT_ENVIRONMENT="$ROOT/envs/ace"
export UV_CACHE_DIR="$ROOT/cache/uv"
export UV_HTTP_TIMEOUT=120
export UV_CONCURRENT_DOWNLOADS=6
export TMPDIR="$ROOT/cache/tmp"
mkdir -p "$TMPDIR"
# AutoDL-provided development network accelerator; do not print its variables.
if [[ -f /etc/network_turbo ]]; then
    set +u
    source /etc/network_turbo >/dev/null 2>&1
    set -u
fi
export NO_PROXY="${NO_PROXY:-},mirrors.aliyun.com,modelscope.cn,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
echo "Started UTC $(date -u +%FT%TZ), source $COMMIT"
"/root/miniconda3/bin/python" - "$SOURCE/uv.lock" <<'PY'
import pathlib,sys,tomllib,urllib.parse,subprocess
lock=pathlib.Path(sys.argv[1])
data=tomllib.loads(lock.read_text())
missing=[]
for package in data['package']:
    for wheel in package.get('wheels',[]):
        url=wheel.get('url','')
        if url.startswith('file:') and not pathlib.Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).exists():
            missing.append(url)
if missing:
    print('Local relay cache absent; restoring pinned mirror transport for rebuild.')
    subprocess.run([sys.executable,'/root/autodl-tmp/emusician/tools/ace_mirror_lock.py'],check=True)
PY
timeout 3600 /root/miniconda3/bin/uv sync --frozen --project "$SOURCE"
"$UV_PROJECT_ENVIRONMENT/bin/python" "$ROOT/tools/ace_env_verify.py"
/root/miniconda3/bin/uv pip freeze --python "$UV_PROJECT_ENVIRONMENT/bin/python" > "$ROOT/manifests/ace-environment-freeze.txt"
echo "Finished UTC $(date -u +%FT%TZ)"
