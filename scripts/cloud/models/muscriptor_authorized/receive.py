"""Store credential whose official gated metadata was verified by the local client."""
from pathlib import Path
import json
import os
import sys

def main():
    base=Path('/root/autodl-tmp/emusician/workspace/models/muscriptor/hf')
    assert os.name=='posix' and base.parent.is_dir() and not base.is_symlink()
    token=sys.stdin.readline(512).strip()
    assert token.startswith('hf_') and not any(c.isspace() for c in token)
    base.mkdir(mode=0o700,exist_ok=True);os.chmod(base,0o700)
    target=base/'token'
    assert not target.is_symlink()
    assert not target.exists() or target.read_text(encoding='utf8').strip()==token
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w',encoding='utf8') as stream:
        stream.write(token)
    os.chmod(target,0o600);token=None
    print(json.dumps({'credential_saved':True,'mode':'0600','scope':'MuScriptor HF_HOME'}))

if __name__=='__main__':
    try:
        main()
    except BaseException:
        print(json.dumps({'credential_saved':False}))
        raise SystemExit(1)
