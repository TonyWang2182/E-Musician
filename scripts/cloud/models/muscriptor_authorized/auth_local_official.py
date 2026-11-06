"""Check official gated metadata locally; transport an approved token only via SSH stdin."""
from pathlib import Path
import getpass
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'scripts'))
from dev import Recorder,configure_console_output
REPO='MuScriptor/muscriptor-medium'
REV='f32236969308476e01fd3aae67357de5feb05a2d'
SHA='ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def main():
    configure_console_output()
    token=getpass.getpass('MuScriptor read token (hidden, official HF check): ')
    r=Recorder('muscriptor-official-local-access','Windows/Python3.14 -> official HF HTTPS','Cloud auth API503; local official HEAD, no cross-host Authorization redirects, approved credential to cloud SSH stdin only.')
    started=time.perf_counter()
    record,record_path,log_path=r.new_record(['official-HF-gated-weight-HEAD','credential-via-hidden-input'])
    report={'model':REPO,'revision':REV,'weight_access':False,'credential_saved':False,'endpoint':'https://huggingface.co','terms_accepted_by_agent':False}
    try:
        opener=urllib.request.build_opener(NoRedirect())
        request=urllib.request.Request(f'https://huggingface.co/{REPO}/resolve/{REV}/model.safetensors',method='HEAD',headers={'Authorization':'Bearer '+token})
        try:
            response=opener.open(request,timeout=30)
        except urllib.error.HTTPError as error:
            if error.code not in (302,307):
                raise
            response=error
        headers=response.headers
        assert headers.get('X-Repo-Commit')==REV
        assert int(headers.get('X-Linked-Size',0))==1228144472
        assert headers.get('X-Linked-Etag','').strip('"')==SHA
        report.update(weight_access=True,http_status=response.code)
        response.close()
        command=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10','emusician-autodl',
            '/root/miniconda3/bin/python /root/autodl-tmp/emusician/workspace/models/muscriptor/deploy-authorized-v3/receive.py']
        result=subprocess.run(command,input=token+'\n',text=True,capture_output=True,timeout=30)
        receipt=json.loads(result.stdout)
        assert result.returncode==0 and receipt=={'credential_saved':True,'mode':'0600','scope':'MuScriptor HF_HOME'}
        report.update(credential_saved=True,credential_mode='0600')
        record.update(status='succeeded',exit_code=0)
    except Exception as error:
        report.update(error_type=type(error).__name__,http_status=getattr(error,'code',report.get('http_status')))
        record.update(status='failed',exit_code=1)
    finally:
        token=None
        data=json.dumps(report,indent=2)+'\n'
        log_path.write_text(data,encoding='utf8')
        (ROOT/'docs/review/2026-11-06-muscriptor-authorized/access-local.json').write_text(data,encoding='utf8')
        r.finish(record,record_path,log_path,started)
        print(data,flush=True)
    return record['exit_code']

if __name__=='__main__':
    raise SystemExit(main())
