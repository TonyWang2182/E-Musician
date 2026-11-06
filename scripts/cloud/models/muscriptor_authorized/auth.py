"""Check a user-supplied HF token via stdin; never print it or accept model terms."""
from pathlib import Path
import json
import os
import sys

ROOT = Path('/root/autodl-tmp/emusician')
HF_HOME = ROOT/'workspace/models/muscriptor/hf'
REPO = 'MuScriptor/muscriptor-medium'
REVISION = 'f32236969308476e01fd3aae67357de5feb05a2d'
BYTES = 1228144472

def main():
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only credential setup')
    token = sys.stdin.readline(512).strip()
    report = {'model':REPO,'revision':REVISION,'token_valid':False,'weight_access':False,'credential_saved':False,'terms_accepted_by_agent':False}
    if not token.startswith('hf_') or any(c.isspace() for c in token):
        report['reason'] = 'Invalid token input format'
        print(json.dumps(report),flush=True)
        return 2
    try:
        os.environ['HF_ENDPOINT'] = 'https://huggingface.co'
        from huggingface_hub import HfApi, get_hf_file_metadata, hf_hub_url
        HfApi().whoami(token=token)
        report['token_valid'] = True
        metadata = get_hf_file_metadata(hf_hub_url(REPO,'model.safetensors',revision=REVISION),token=token,timeout=30)
        if metadata.size != BYTES or metadata.commit_hash != REVISION:
            raise ValueError('Pinned metadata mismatch')
        report.update(weight_access=True,weight_bytes=metadata.size)
        if HF_HOME.is_symlink():
            raise ValueError('Credential directory cannot be a symlink')
        HF_HOME.mkdir(parents=True,exist_ok=True)
        os.chmod(HF_HOME,0o700)
        target = HF_HOME/'token'
        if target.is_symlink():
            raise ValueError('Credential target cannot be a symlink')
        if target.exists() and target.read_text().strip() != token:
            report['reason'] = 'Existing distinct model-scoped credential preserved'
            print(json.dumps(report),flush=True)
            return 3
        fd = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'w',encoding='utf8') as stream:
            stream.write(token)
        os.chmod(target,0o600)
        report.update(credential_saved=True,credential_scope='private MuScriptor HF_HOME only',credential_mode='0600')
    except Exception as error:
        response = getattr(error,'response',None)
        report.update(error_type=type(error).__name__,http_status=getattr(response,'status_code',None))
        report['reason'] = 'Authenticated access not established; no terms accepted or access controls bypassed'
    finally:
        token = None
    print(json.dumps(report),flush=True)
    return 0 if report['weight_access'] and report['credential_saved'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
