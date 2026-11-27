"""Read the real desktop capability projection; no model calls or audio device.

Cloud health is checked separately through register_compute.py's real SSH
tunnel. A registered provider is not an inference or listening acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_client import Client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'inference_performed': False, 'audio_device_tested': False,
              'executable': str(args.exe.resolve()),
              'exe_sha256': hashlib.sha256(args.exe.read_bytes()).hexdigest()}
    client = Client(args.exe, offline_test=True, timeout=40)
    try:
        for kind, command in [('analysis', 'get_analysis_capabilities'),
                              ('generation', 'get_generation_capabilities')]:
            response = client.request({'command': command})
            report[kind] = response['result']
        providers = report['analysis']['providers'] + report['generation']['providers']
        ready = {(p['execution'], p['model_id']) for p in providers if p.get('available') is True}
        expected_cloud = {'ace-step-1.5-xl-turbo', 'yue2', 'scnet', 'transkun',
                          'chordmini', 'muscriptor', 'sheetsage2'}
        expected_local = {'htdemucs', 'basic-pitch', 'chroma-hmm', 'beat-this-final0'}
        assert all(('cloud', name) in ready for name in expected_cloud), 'Missing registered cloud route'
        assert all(('local', name) in ready for name in expected_local), 'Missing registered local route'
        # The six-stem checkpoint is exposed as a Demucs option, not a fifth
        # provider object in the desktop protocol projection.
        assert report['analysis']['separation_six_stems'] is True, 'Six-stem option unavailable'
        report['checked_routes'] = {'cloud': sorted(expected_cloud),
                                    'local': sorted(expected_local), 'six_stem_option': True}
        report['passed'] = True
    finally:
        client.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'output': str(args.output),
                      'inference_performed': False}))


if __name__ == '__main__':
    main()
