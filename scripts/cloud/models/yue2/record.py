"""Local recorded transport for small YuE2 code and metadata only."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'scripts'))
from dev import Recorder,configure_console_output

def main():
    configure_console_output()
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['upload','source','weights','install','cpu','tests','guard-tests','gpu','finalize','collect']);args=parser.parse_args()
    configuration=f'local/{sys.platform}/Python{sys.version_info.major}.{sys.version_info.minor}' if args.action=='guard-tests' else 'cloud/Linux/Python3.12'
    recorder=Recorder('cloud-yue2-'+args.action,configuration,'Cloud-only pinned YuE2 deployment; no DAW integration, no E model/audio/backup download; '+('explicitly authorized single low-VRAM180s GPU probe' if args.action=='gpu' else 'no GPU inference in this command'))
    base='/root/autodl-tmp/emusician/workspace/models/yue2'
    meta='/root/autodl-tmp/emusician/manifests/model-library/yue2'
    logs='/root/autodl-tmp/emusician/logs/model-library/yue2'
    if args.action=='guard-tests':
        recorder.execute([sys.executable,'-m','unittest','discover','-s',str(Path(__file__).parent),'-p','test_gpu_smoke.py','-v'])
    elif args.action=='upload':
        recorder.execute(['ssh','-o','BatchMode=yes','emusician-autodl',f'mkdir -p {base} {meta} {logs}'])
        files=[str(path) for path in Path(__file__).parent.iterdir() if path.suffix in {'.py','.sh'} and path.name!='record.py']
        recorder.execute(['scp',*files,f'emusician-autodl:{base}/'])
        recorder.execute(['ssh','-o','BatchMode=yes','emusician-autodl',f'chmod u+x {base}/run.sh {base}/install.sh'])
    elif args.action=='collect':
        destination=ROOT/'docs/review/2026-11-06-cloud-model-library/yue2'
        destination.mkdir(parents=True,exist_ok=True)
        recorder.execute(['scp',f'emusician-autodl:{meta}/*.json',f'emusician-autodl:{meta}/*.txt',str(destination)])
    elif args.action=='gpu':
        recorder.execute(['ssh','-o','BatchMode=yes','-o','ServerAliveInterval=20','emusician-autodl',f'/root/miniconda3/bin/python {base}/gpu_smoke.py --approved-slot'])
    elif args.action=='finalize':
        recorder.execute(['ssh','-o','BatchMode=yes','emusician-autodl',f'/root/miniconda3/bin/python {base}/finalize.py'])
    elif args.action=='tests':
        source=base+'/YuE-1116bea76032bee5668e5f097294d082fa0b84f0'
        cases=' '.join(source+'/tests/'+name+'.py' for name in ['test_protocol','test_preflight','test_storage','test_cli_public'])
        command=f'bash -lc \'set -eo pipefail; export CUDA_VISIBLE_DEVICES="" HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2; timeout 300 /root/autodl-tmp/emusician/envs/yue2/bin/python -m pytest -q {cases} 2>&1 | tee {logs}/cpu-tests-$(date -u +%Y%m%dT%H%M%SZ).log\''
        recorder.execute(['ssh','-o','BatchMode=yes','emusician-autodl',command])
    else:
        target='install.sh' if args.action=='install' else 'cpu_check.py' if args.action=='cpu' else 'stage.py '+args.action
        interpreter='bash' if args.action=='install' else '/root/autodl-tmp/emusician/envs/yue2/bin/python' if args.action=='cpu' else '/root/miniconda3/bin/python'
        limit=600 if args.action=='cpu' else 3600
        command=f'bash -lc \'set -eo pipefail; source /etc/network_turbo >/dev/null 2>&1; timeout {limit} {interpreter} {base}/{target} 2>&1 | tee {logs}/{args.action}-$(date -u +%Y%m%dT%H%M%SZ).log\''
        recorder.execute(['ssh','-o','BatchMode=yes','-o','ServerAliveInterval=20','emusician-autodl',command])

if __name__=='__main__':main()
