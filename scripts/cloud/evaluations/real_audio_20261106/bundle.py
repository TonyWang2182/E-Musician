"""Bundle explicitly selected successful cloud results; never fetch audio to E:."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time
import uuid
import zipfile

ROOT=Path('/root/autodl-tmp/emusician/results/evaluations/real_audio_20261106')
ALLOWED={'.wav','.mid','.midi','.lab','.json','.abc'}
EXCLUDED_DIRS={'logs','cache','__pycache__','hidden_states','hidden-states','latents'}
CHUNK=1024*1024


def safe_path(value,root):
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(root):
        raise ValueError('Path must remain below the fixed cloud result root')
    current=root
    if current.is_symlink():raise ValueError('Result root cannot be a symlink')
    for part in path.relative_to(root).parts:
        current=current/part
        if current.is_symlink():raise ValueError('Symlinks are not allowed in a result bundle')
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Path escapes result root')
    return path


def read_json(path):
    if path.stat().st_size>16*1024*1024:raise ValueError('Unexpectedly large success receipt')
    return json.loads(path.read_text(encoding='utf-8'))


def successful_result(directory,root):
    if (directory/'attempt.json').is_file():
        paths=[directory/'attempt.json',directory/'data/result.json']
        parent,child=[read_json(safe_path(p,root)) for p in paths]
        expected=parent.get('expected_input_sha256')
    else:
        paths=[directory/'guard-receipt.json',directory/'result-receipt.json']
        parent,child=[read_json(safe_path(p,root)) for p in paths]
        expected=parent.get('input_sha256')
    if parent.get('status')!='passed' or child.get('status')!='passed':
        raise ValueError('Both supervisor and worker must have successful terminal receipts')
    actual=child.get('input',{}).get('sha256')
    if not expected or actual!=expected:raise ValueError('Parent and worker input SHA disagree')
    expected_outputs={}
    for entry in child.get('outputs',child.get('artifacts',[])):
        path=safe_path(entry['path'],root)
        if not path.is_relative_to(directory):raise ValueError('Receipt references another result directory')
        expected_outputs[path]=(int(entry['bytes']),entry['sha256'])
    if not expected_outputs:raise ValueError('Successful receipt lists no output artifacts')
    return paths,expected_outputs


def input_files(directories,root):
    files=[];expected={};omitted=[]
    for directory in directories:
        _,locked=successful_result(directory,root);expected.update(locked)
        for base,subdirs,names in os.walk(directory,followlinks=False):
            base=Path(base)
            for name in list(subdirs):
                candidate=safe_path(base/name,root)
                if name.startswith('.') or name in EXCLUDED_DIRS:
                    omitted.append(candidate.relative_to(root).as_posix()+'/');subdirs.remove(name)
            for name in sorted(names):
                path=safe_path(base/name,root)
                if not stat.S_ISREG(path.stat().st_mode):raise ValueError('Only regular result files may be bundled')
                if name.startswith('.') or path.suffix.lower() not in ALLOWED:
                    omitted.append(path.relative_to(root).as_posix());continue
                files.append(path)
    if not any(path.suffix.lower() in {'.wav','.mid','.midi','.lab','.abc'} for path in files):
        raise ValueError('No raw analysis outputs to bundle')
    selected=set(files)
    for path in expected:
        relative=path.relative_to(root)
        eligible=path.suffix.lower() in ALLOWED and not any(part.startswith('.') or part in EXCLUDED_DIRS for part in relative.parts)
        if eligible and path not in selected:raise ValueError('A declared output artifact is missing from the bundle input')
    return sorted(files),expected,sorted(omitted)


def build_archive(directories,output,*,root=ROOT,reserve_bytes=50_000_000_000):
    root=Path(root);output=safe_path(output,root)
    directories=[safe_path(value,root) for value in directories]
    if not directories or any(not p.is_dir() or p==root for p in directories):raise ValueError('Choose explicit result directories')
    for index,path in enumerate(directories):
        if any(path.is_relative_to(other) or other.is_relative_to(path) for other in directories[index+1:]):
            raise ValueError('Input directories overlap or repeat')
        if output.is_relative_to(path):raise ValueError('Archive must remain outside selected source directories')
    if output.suffix.lower()!='.zip':raise ValueError('Output must be a .zip archive')
    receipt_path=output.with_suffix('.manifest.json')
    safe_path(receipt_path,root)
    if output.exists() or receipt_path.exists():raise FileExistsError('Refusing to overwrite an archive or receipt')
    files,expected,omitted=input_files(directories,root)
    estimated=sum(path.stat().st_size for path in files)
    if shutil.disk_usage(root).free-estimated<reserve_bytes:raise RuntimeError('Insufficient cloud disk reserve for the raw archive')
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.name+'.partial-'+uuid.uuid4().hex)
    manifest={'schema_version':1,'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'kind':'raw_successful_analysis_results','source_root':str(root),
        'selected_directories':[p.relative_to(root).as_posix() for p in directories],
        'files':[],'omitted':omitted,'audio_downloaded_to_e':False}
    try:
        with temporary.open('xb') as stream,zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            for path in files:
                safe_path(path,root)
                flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)
                with os.fdopen(os.open(path,flags),'rb') as source:
                    before=os.fstat(source.fileno())
                    if not stat.S_ISREG(before.st_mode):raise ValueError('Bundle source is no longer a regular file')
                    member=path.relative_to(root).as_posix()
                    digest=hashlib.sha256();count=0
                    with archive.open(member,'w',force_zip64=True) as target:
                        for block in iter(lambda:source.read(CHUNK),b''):
                            target.write(block);digest.update(block);count+=len(block)
                    after=os.fstat(source.fileno())
                    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino) or count!=before.st_size:
                        raise ValueError('Source changed during bundle creation')
                    checksum=digest.hexdigest()
                    if path in expected and expected[path]!=(count,checksum):raise ValueError('Output SHA differs from successful inference receipt')
                    manifest['files'].append({'path':member,'original_relative_path':member,'bytes':count,'sha256':checksum})
            archive.writestr('MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        with temporary.open('rb') as source:archive_sha=hashlib.file_digest(source,'sha256').hexdigest()
        receipt={'status':'passed','archive':str(output),'bytes':temporary.stat().st_size,'sha256':archive_sha,
                 'file_count':len(manifest['files']),'raw_bytes':sum(x['bytes'] for x in manifest['files']),
                 'manifest_member':'MANIFEST.json','selected_directories':manifest['selected_directories'],
                 'audio_downloaded_to_e':False}
        # Hard-link publication is atomic and fails if the destination exists.
        os.link(temporary,output)
        with receipt_path.open('x',encoding='utf-8') as dest:json.dump(receipt,dest,ensure_ascii=False,indent=2);dest.write('\n')
        return receipt
    finally:
        # This is only the newly-created, random temporary file under the checked root.
        if temporary.is_file():temporary.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.name!='posix' or not ROOT.is_dir():raise RuntimeError('Run only on the authorized cloud instance')
    print(json.dumps(build_archive(args.input_dir,args.output),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
