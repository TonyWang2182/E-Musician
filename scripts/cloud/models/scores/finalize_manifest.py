"""Freeze small deployment evidence after recorded checks; never marks unrun checks."""
from pathlib import Path
import json
import os
from stage import ROOT, artifact, deployment, save_deployment


def main():
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only evidence finalizer')
    here = Path(__file__).parent
    plan = json.loads((here/'artifacts.json').read_text())
    for name in ('sheetsage2', 'muscriptor'):
        state = deployment(name, plan)
        manifest = ROOT/'manifests/model-library'/name
        for path in sorted(manifest.iterdir()):
            if path.is_file() and path.name != 'deployment.json':
                item = artifact(path)
                state['artifacts'] = [i for i in state['artifacts'] if i['path'] != item['path']] + [item]
        state['entrypoints'] = {'cpu_verifier': str(here/'stage-cpu-v2.py')}
        if name == 'sheetsage2':
            state['entrypoints'].update(cli=str(here/'run_sheetsage2-v1.sh'), guarded_gpu_probe=str(here/'gpu_probe-final-v3.py'),
                installer=str(here/'install-pypi-v2.sh'))
            state['guard_evidence'] = {'actual_gpu_executed_guard': artifact(here/'gpu_probe-v1.py'),
                'final_guard': artifact(here/'gpu_probe-final-v3.py'),
                'final_guard_cpu_fault_tests': {'passed': 7, 'record': '20261106T104412.119818Z-94b839b905',
                                              'no_gpu_rerun': True}}
            state['distribution_note'] = 'PyPI torch==2.8.0 and torchaudio==2.8.0 Linux wheels report runtime2.8.0+cu128. Original CUDA-index wheel attempts were stopped; distinct SHA hashes retained in the review log.'
            state['upstream_default_parent_resolution_verified'] = (manifest/'wrapper-help.txt').is_file()
            state['retained_limitations'] = [
                'Only one8-second cloud fixture structurally checked; no transcription accuracy or listening evaluation',
                'Actual upstream300-second encoder padding retained; short fixture does not establish long-song performance',
                'Optional score PDF/image and rendered-audio assets/tools not deployed',
                'Paper-preset torchaudio FFmpeg shared-library backend unverified',
                'No DAW or Agent integration in this phase',
            ]
        else:
            state['retained_limitations'] = ['Gated medium weights unavailable; source/environment only, no model CPU/GPU load',
                'Large model not attempted; MIDI velocity default100 is not measured performance velocity',
                'No DAW or Agent integration in this phase']
        for filename in ('artifacts.json', 'stage-cpu-v2.py', 'finalize-20261106.sh'):
            item = artifact(here/filename)
            state['artifacts'] = [i for i in state['artifacts'] if i['path'] != item['path']] + [item]
        if name == 'sheetsage2':
            for filename in ('toolchain-v2.py', 'gpu_probe-v1.py', 'gpu_probe-final-v3.py', 'test_guard-v2.py',
                             'run_sheetsage2-v1.sh', 'install-pypi-v2.sh'):
                item = artifact(here/filename)
                state['artifacts'] = [i for i in state['artifacts'] if i['path'] != item['path']] + [item]
        save_deployment(name, state)
        print(json.dumps({'model': name, 'checks': state['checks'], 'artifact_count': len(state['artifacts']),
                          'free_bytes': state['cloud_free_bytes']}))


if __name__ == '__main__':
    main()
