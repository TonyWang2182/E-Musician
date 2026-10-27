"""Real plugin listener regression. Exact pre-scanned module required; run via Recorder."""
import argparse, hashlib, json, subprocess, sys, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from agent_client import Client
from PluginHostSmoke import exact_cache_entries, page

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--module',type=Path,required=True)
    args=parser.parse_args()
    exe=args.exe.resolve(strict=True);module=args.module.resolve(strict=True)
    ids={entry['id'] for entry in exact_cache_entries(module) if entry['available']}
    with Client(exe,60) as client:
        matches=[entry for entry in page(client,'get_plugin_catalog','plugins') if entry['id'] in ids]
        if len(matches)!=1: raise RuntimeError('Expected exactly one available catalog class for the explicit module')
        catalog=matches[0]['id']
    parent=ROOT/'build/plugin-notification';parent.mkdir(exist_ok=True)
    directory=parent/str(uuid.uuid4())
    completed=subprocess.run([str(exe),'--plugin-notification-test',str(directory),catalog],timeout=90)
    report=json.loads((directory/'report.json').read_text(encoding='utf-8-sig'))
    metadata={'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'module':str(module),'catalog_id':catalog,'exit_code':completed.returncode}
    (directory/'execution.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'report':str(directory/'report.json'),'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=True),flush=True)
    return 0 if completed.returncode==0 and report['status']=='passed' else 1

if __name__=='__main__': raise SystemExit(main())
