"""Official HF -> bounded local RAM -> SSH cloud file; never store weights locally."""
from pathlib import Path
import getpass
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'scripts'))
from dev import Recorder,configure_console_output
REPO='MuScriptor/muscriptor-medium'
REV='f32236969308476e01fd3aae67357de5feb05a2d'
SIZE=1228144472
SHA='ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec'
CONFIG={'dim':1024,'num_heads':16,'num_layers':24,'card':1395}

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,url):
        if urlsplit(url).scheme!='https':
            raise ValueError('No downgrade to HTTP')
        redirected=super().redirect_request(request,fp,code,msg,headers,url)
        if urlsplit(url).hostname != 'huggingface.co':
            redirected.remove_header('Authorization')
        return redirected

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def transfer(name,size,checksum,blocks):
    command=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=20','emusician-autodl',
        '/root/miniconda3/bin/python /root/autodl-tmp/emusician/workspace/models/muscriptor/deploy-relay-v1/relay_receive.py --filename '+name+' --bytes '+str(size)+' --sha256 '+checksum]
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    total=0;last=0;digest=hashlib.sha256()
    try:
        for block in blocks:
            total+=len(block)
            if total>size:
                raise ValueError('Download exceeds pinned size')
            process.stdin.write(block);digest.update(block)
            if total-last>=64*1024*1024:
                print(json.dumps({'filename':name,'relayed_bytes':total,'total_bytes':size}),flush=True);last=total
        process.stdin.close();process.stdin=None
        stdout,stderr=process.communicate(timeout=60)
        if process.returncode!=0:
            raise RuntimeError('Cloud receiver failed')
        result=json.loads(stdout)
        if total!=size or digest.hexdigest()!=checksum or result.get('sha256')!=checksum or result.get('bytes')!=size or result.get('status')!='passed':
            raise ValueError('Relay content verification failed')
        return result
    finally:
        if process.poll() is None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (BrokenPipeError,OSError):
                    pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)

def main():
    configure_console_output()
    token=getpass.getpass('MuScriptor read token (hidden, RAM relay): ')
    recorder=Recorder('muscriptor-official-ram-relay','Windows/Python3.14 -> SSH/cloud','Official HF download through local 1MiB memory blocks directly to cloud; no local model file, no credential in argv/log, no unauthorized endpoint.')
    started=time.monotonic()
    record,rpath,log=recorder.new_record(['official-HF-HTTPS','bounded-RAM-relay','SSH-stdin-cloud-receiver'])
    report={'model':REPO,'revision':REV,'status':'running','files':[],'local_model_files_written':False,'chunk_bytes':1048576,'phase':'config_metadata','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        opener=urllib.request.build_opener(SafeRedirect())
        url=f'https://huggingface.co/{REPO}/resolve/{REV}/config.json'
        with opener.open(urllib.request.Request(url,headers={'Authorization':'Bearer '+token}),timeout=45) as response:
            data=response.read(65537);etag=response.headers.get('ETag','').strip('"')
        assert len(data)<=65536
        values=json.loads(data);assert all(values.get(k)==v for k,v in CONFIG.items())
        blob=hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()
        assert blob==etag,'Official config Git blob mismatch'
        checksum=hashlib.sha256(data).hexdigest()
        report['phase']='config_transfer'
        report['files'].append(transfer('config.json',len(data),checksum,[data]))
        report['config']=values;report['config_git_blob']=blob
        report['phase']='weight_metadata'
        request=urllib.request.Request(f'https://huggingface.co/{REPO}/resolve/{REV}/model.safetensors',method='HEAD',headers={'Authorization':'Bearer '+token})
        try:
            response=urllib.request.build_opener(NoRedirect()).open(request,timeout=45)
        except urllib.error.HTTPError as error:
            if error.code not in (302,307):
                raise
            response=error
        headers=response.headers
        assert headers.get('X-Repo-Commit')==REV and int(headers.get('X-Linked-Size',0))==SIZE and headers.get('X-Linked-Etag','').strip('"')==SHA
        location=headers['Location'];assert urlsplit(location).scheme=='https'
        response.close()
        report['phase']='weight_transfer'
        # Signed URL from official HF; never forward the HF bearer token to it.
        with opener.open(urllib.request.Request(location),timeout=90) as response:
            report['files'].append(transfer('model.safetensors',SIZE,SHA,iter(lambda:response.read(1048576),b'')))
        report.update(status='passed',phase='complete')
        record.update(status='succeeded',exit_code=0)
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__,http_status=getattr(error,'code',None))
        record.update(status='failed',exit_code=1)
    finally:
        token=None
        report['elapsed_seconds']=time.monotonic()-started
        data=json.dumps(report,indent=2)+'\n'
        log.write_text(data,encoding='utf8')
        (ROOT/'docs/review/2026-11-06-muscriptor-authorized/relay.json').write_text(data,encoding='utf8')
        recorder.finish(record,rpath,log,started)
        print(data,flush=True)
    return record['exit_code']

if __name__=='__main__':
    raise SystemExit(main())
