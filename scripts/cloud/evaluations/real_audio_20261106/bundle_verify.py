"""Read-only streaming CRC/SHA verification of a raw-result ZIP; no extraction."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import stat
import zipfile


def verify(path,receipt_path):
    receipt=json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    path=Path(path)
    if path.stat().st_size!=receipt['bytes']:raise ValueError('Archive byte count changed')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=receipt['sha256']:
            raise ValueError('Archive SHA mismatch')
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist();names=[info.filename for info in infos]
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive members')
        for info in infos:
            name=PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ':' in info.filename or info.is_dir():
                raise ValueError('Unsafe archive member name')
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('Archive contains a symlink')
        if archive.getinfo('MANIFEST.json').file_size>16*1024*1024:raise ValueError('Oversize manifest')
        manifest=json.loads(archive.read('MANIFEST.json'))
        entries={entry['path']:entry for entry in manifest['files']}
        if len(entries)!=len(manifest['files']) or set(names)!=set(entries)|{'MANIFEST.json'}:
            raise ValueError('Manifest membership mismatch')
        total=0
        for name,entry in entries.items():
            if archive.getinfo(name).file_size!=entry['bytes']:raise ValueError('Member declared size mismatch')
            count=0;digest=hashlib.sha256()
            with archive.open(name) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):
                    count+=len(block)
                    if count>entry['bytes']:raise ValueError('Member exceeds declared size')
                    digest.update(block)
            # Reading the complete member also invokes zipfile's CRC validation.
            if count!=entry['bytes'] or digest.hexdigest()!=entry['sha256']:raise ValueError('Member SHA/size mismatch')
            total+=count
    if len(entries)!=receipt['file_count'] or total!=receipt['raw_bytes']:raise ValueError('Receipt count mismatch')
    return {'status':'passed','archive':str(path),'bytes':receipt['bytes'],'sha256':receipt['sha256'],
            'members_verified':len(entries),'raw_bytes':total,'whole_archive_sha_verified':True,
            'crc_and_member_sha_verified':True,'extraction_performed':False,'audio_downloaded_to_e':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();report=verify(args.archive,args.receipt)
    with args.report.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
