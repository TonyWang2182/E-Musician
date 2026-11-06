"""Transfer user-selected original input and inspect it without model execution."""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts'))
from dev import Recorder, configure_console_output

REMOTE = '/root/autodl-tmp/emusician/workspace/evaluations/real_audio_20261106'
DOC = ROOT / 'docs/review/2026-11-06-real-audio'

def main():
    configure_console_output()
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['upload', 'inspect'])
    parser.add_argument('--file')
    parser.add_argument('--id', default='newlight')
    args = parser.parse_args()
    if args.id not in {'newlight', 'piano'}:
        parser.error('Unknown evaluation input id')
    rec = Recorder('real-audio-' + args.action + '-' + args.id, 'cloud/Linux/RTX5090;local/Python3.14', 'Original user input; no DAW integration or model/audio download to E.')
    if args.action == 'upload':
        source = Path(args.file).resolve(strict=True)
        with source.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        remote_file = REMOTE + '/inputs/' + args.id + source.suffix.lower()
        manifest = {'id': args.id, 'source': str(source), 'original_filename': source.name, 'bytes': source.stat().st_size, 'sha256': sha, 'cloud_path': remote_file, 'trimmed': False}
        DOC.mkdir(parents=True, exist_ok=True)
        manifest_path = DOC / (args.id + '-input.json')
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding='utf8'))
            if previous['sha256'] != sha or previous['cloud_path'] != remote_file:
                raise ValueError('Input id already belongs to another file; use a new evaluation.')
        else:
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        rec.execute(['ssh', '-o', 'BatchMode=yes', 'emusician-autodl', 'mkdir -p ' + shlex.quote(REMOTE + '/inputs')])
        check = 'from pathlib import Path;import hashlib;p=Path(' + repr(remote_file) + ');assert not p.exists() or hashlib.file_digest(p.open("rb"),"sha256").hexdigest()==' + repr(sha) + ',"Existing input differs"'
        rec.execute(['ssh', '-o', 'BatchMode=yes', 'emusician-autodl', '/root/autodl-tmp/emusician/envs/scnet/bin/python -c ' + shlex.quote(check)])
        rec.execute(['scp', str(source), 'emusician-autodl:' + remote_file])
        rec.execute(['scp', str(manifest_path), 'emusician-autodl:' + REMOTE + '/inputs/' + manifest_path.name])
    else:
        m = json.loads((DOC / (args.id + '-input.json')).read_text(encoding='utf8'))
        code = 'import hashlib,json,soundfile as sf;from pathlib import Path;p=Path(' + repr(m['cloud_path']) + ');h=hashlib.file_digest(p.open("rb"),"sha256").hexdigest();assert h==' + repr(m['sha256']) + ';i=sf.info(str(p));print(json.dumps(dict(path=str(p),sha256=h,bytes=p.stat().st_size,frames=i.frames,sample_rate=i.samplerate,channels=i.channels,duration_seconds=i.duration,format=i.format,subtype=i.subtype)))'
        rec.execute(['ssh', '-o', 'BatchMode=yes', 'emusician-autodl', '/root/autodl-tmp/emusician/envs/scnet/bin/python -c ' + shlex.quote(code)])

if __name__ == '__main__':
    main()
