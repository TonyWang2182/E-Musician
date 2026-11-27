"""Fingerprint cloud deployment scripts after verification; never load model data."""
import json
import time
from pathlib import Path
from stage import BASE,META,atomic_json,digest


def main():
    artifacts=[{'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path)}
               for path in sorted(BASE.iterdir()) if path.is_file() and path.suffix in {'.py','.sh'}]
    lock=META/'deployment-script-lock.json'
    atomic_json(lock,{'schema_version':1,'files':artifacts,'generated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    deployment_path=META/'deployment.json'
    deployment=json.loads(deployment_path.read_text())
    deployment['deployment_script_lock']={'path':str(lock),'sha256':digest(lock)}
    probe=json.loads(Path(deployment['gpu_probe']).read_text())
    if probe['started_utc']=='20261106T102323Z':
        deployment['probe_guard_audit']={
            'executed_guard_sha256':'4e5e901d3bb1650e2bd4fd5a8f5ffc96617261a762e4caf3efc670af0abf5add',
            'current_guard_sha256':digest(BASE/'gpu_smoke.py'),
            'change':'After this one real probe, post-run telemetry failure handling was hardened and CPU-tested; future probe output moved to results/model-library/yue2/probe-<stamp>. Existing evidence was not moved. No repeat GPU run.',
            'evidence':'Recorder 20261106T102322.038961Z-19a5b59536 (probe), 20261106T102525.748015Z-944a3aa48a (CPU guard tests)'}
    deployment['gpu_limitations']=[
        'Only one token-capped 8GiB low_vram torch-eager instrumental request was tested.',
        'Semantic generation hit 192-token cap; this is bounded audio rendering, not a completed song.',
        'Default24GiB, full symbolic planning, long songs, vocals, batch/concurrent use and listening quality are unverified.',
        'PCM16 peak reached1.0; the test establishes finite/nonzero audio only, not clipping-free or perceptual quality.',
        'No DAW integration; generation requires an explicitly serialized GPU slot.']
    deployment['future_probe_output_root']='/root/autodl-tmp/emusician/results/model-library/yue2'
    atomic_json(deployment_path,deployment)
    print(json.dumps({'files':len(artifacts),'script_lock':str(lock),'script_lock_sha256':digest(lock),
                      'deployment_sha256':digest(deployment_path),'daw_connected':deployment['daw_connected']}))


if __name__=='__main__':main()
