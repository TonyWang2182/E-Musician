"""Real CUDA smoke, separately records cold/warm generation (no quality claim)."""
import json
import hashlib
import time
from pathlib import Path
from ace_worker import AceGenerator

ROOT = Path("/root/autodl-tmp/emusician")


def main():
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = ROOT / "experiments" / f"ace-smoke-{stamp}"
    target.mkdir(parents=True)
    generator = AceGenerator(ROOT)
    reports = []
    requests = [
        {"request_id": f"smoke-{stamp}-instrumental", "kind": "generate", "model_id": "ace-step-1.5-xl-turbo",
         "prompt": "Warm acoustic piano jazz trio, relaxed upright bass and brushed drums, clean studio recording, mellow intimate groove.",
         "lyrics": "", "instrumental": True, "duration_seconds": 12, "bpm": 120, "time_signature": "4/4", "seed": 120},
        {"request_id": f"smoke-{stamp}-vocal", "kind": "generate", "model_id": "ace-step-1.5-xl-turbo",
         "prompt": "Gentle acoustic folk song with a clear warm female vocal, acoustic guitar and soft piano, clean recording.",
         "lyrics": "[Verse]\nA little light across the sea\nA melody comes home to me", "instrumental": False,
         "duration_seconds": 12, "bpm": 100, "time_signature": "4/4", "seed": 121},
    ]
    for request in requests:
        directory = target / request["request_id"]
        directory.mkdir()
        directory.joinpath("request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
        result = generator(request, directory, lambda phase: print(f"{request['request_id']} {phase}", flush=True), lambda: False)
        reports.append(result)
        print(json.dumps({"job": request["request_id"], "artifacts": result["artifacts"], "metrics": result["metrics"]}), flush=True)
    target.joinpath("smoke-results.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    manifest_path = ROOT / "manifests/ace-runtime.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ready"] = True
    manifest["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest["real_smoke_results"] = str(target / "smoke-results.json")
    runtime_files = []
    lock = json.loads(ROOT.joinpath('manifests/ace-model-lock.json').read_text(encoding='utf-8'))
    for entry in lock['files']:
        path = ROOT / 'models/ace/checkpoints' / entry['local_path']
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                sha.update(block)
        actual = sha.hexdigest()
        if not path.name.endswith('.py') and actual != entry['sha256']:
            raise RuntimeError('Model weights/config changed during smoke: '+entry['local_path'])
        runtime_files.append({'path': entry['local_path'], 'sha256': actual, 'upstream_sha256': entry['sha256'],
                              'synced_from_pinned_source': actual != entry['sha256']})
    ROOT.joinpath('manifests/ace-runtime-model-files.json').write_text(json.dumps(runtime_files,indent=2),encoding='utf-8')
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"status": "real_smoke_passed", "results": str(target)}), flush=True)


if __name__ == "__main__":
    main()
