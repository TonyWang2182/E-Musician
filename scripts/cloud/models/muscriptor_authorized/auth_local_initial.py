"""Hidden console input, SSH stdin transport and sanitized Recorder evidence."""
from pathlib import Path
import getpass
import json
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'scripts'))
from dev import Recorder,configure_console_output

def main():
    configure_console_output()
    token=getpass.getpass('MuScriptor read token (hidden): ')
    command=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10','emusician-autodl',
        '/root/autodl-tmp/emusician/envs/muscriptor/bin/python /root/autodl-tmp/emusician/workspace/models/muscriptor/deploy-authorized-v1/auth.py']
    recorder=Recorder('muscriptor-authorized-access','cloud/Linux;local/hidden-console-input','Read token via hidden input and SSH stdin; no token in argv, logs, Git or local files. No terms acceptance.')
    started=time.perf_counter()
    record,record_path,log_path=recorder.new_record(command)
    try:
        result=subprocess.run(command,input=token+'\n',text=True,capture_output=True,timeout=90)
        # Only the explicit non-secret JSON status contract may enter logs.
        report=json.loads(result.stdout)
        allowed={'model','revision','token_valid','weight_access','credential_saved','terms_accepted_by_agent','weight_bytes','credential_scope','credential_mode','error_type','http_status','reason'}
        if not isinstance(report,dict) or not set(report)<=allowed:
            raise ValueError('Unexpected authentication output')
        data=json.dumps(report,indent=2)+'\n'
        log_path.write_text(data,encoding='utf8')
        dest=ROOT/'docs/review/2026-11-06-muscriptor-authorized/access.json'
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(data,encoding='utf8')
        record.update(status='succeeded' if result.returncode==0 else 'failed',exit_code=result.returncode)
        print(data,flush=True)
    except Exception as error:
        record.update(status='failed',exit_code=1,error=type(error).__name__)
        log_path.write_text('Authentication transport failed: '+type(error).__name__+'\n',encoding='utf8')
    finally:
        token=None
        recorder.finish(record,record_path,log_path,started)
    return record['exit_code']

if __name__ == '__main__':
    raise SystemExit(main())
