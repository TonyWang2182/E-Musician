"""Recorded YuE2 evaluation commands; transfer code/prompt/metadata only."""
from pathlib import Path
import argparse
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'scripts'))
from dev import Recorder,configure_console_output

REMOTE='/root/autodl-tmp/emusician/workspace/evaluations/jungle_20261106'
SOURCE='/root/autodl-tmp/emusician/workspace/models/yue2/YuE-1116bea76032bee5668e5f097294d082fa0b84f0'


def main():
    configure_console_output()
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','inspect-runtime','inspect-codec','upload','check','fault-tests','run','collect'])
    args=parser.parse_args()
    configuration=f'local/{sys.platform}/Python{sys.version_info.major}.{sys.version_info.minor}' if args.action=='fault-tests' else 'cloud/Linux/Python3.12'
    recorder=Recorder('jungle-yue2-'+args.action,configuration,'Original prompt evaluation; no DAW changes or model/audio downloads to E; GPU only for separately authorized run action.')
    if args.action=='fault-tests':
        recorder.execute([sys.executable,'-m','unittest','discover','-s',str(Path(__file__).parent),'-p','yue2_test.py','-v'])
    elif args.action in {'inspect','inspect-runtime','inspect-codec'}:
        files={'inspect':['docs/generation.md','examples/instrumental_clip.py','src/yue2/protocol.py'],
               'inspect-runtime':['src/yue2/pipeline.py','docs/hardware.md','skills/yue2-music/instrumental/README.md'],
               'inspect-codec':['src/yue2/nar.py','src/yue2/modeling_vae.py']}[args.action]
        for relative in files:
            recorder.execute(['ssh','-o','BatchMode=yes','emusician-autodl',f'cat {SOURCE}/{relative}'])
    elif args.action=='upload':
        recorder.execute(['ssh','-o','BatchMode=yes','emusician-autodl',f'mkdir -p {REMOTE}'])
        paths=[str(path) for path in Path(__file__).parent.glob('yue2*.py') if path.name!='yue2_record.py']
        paths.append(str(ROOT/'docs/review/2026-11-06-jungle-generation/prompt.txt'))
        recorder.execute(['scp',*paths,f'emusician-autodl:{REMOTE}/'])
    elif args.action in {'check','run'}:
        mode='--static-check' if args.action=='check' else '--approved-gpu-slot'
        recorder.execute(['ssh','-o','BatchMode=yes','-o','ServerAliveInterval=20','emusician-autodl',f'/root/autodl-tmp/emusician/envs/yue2/bin/python {REMOTE}/yue2_eval.py {mode}'])
    else:
        destination=ROOT/'docs/review/2026-11-06-jungle-generation/yue2'
        destination.mkdir(parents=True,exist_ok=True)
        recorder.execute(['scp',f'emusician-autodl:{REMOTE}/yue2-*.json',str(destination)])


if __name__=='__main__':main()
