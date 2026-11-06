"""Install a pinned, model-scoped FFmpeg binary; never touches the system PATH."""
from pathlib import Path
import json
import os
import subprocess
import zipfile
from stage import ROOT, artifact, deployment, download, free_space, save_deployment

WHEEL = {
    'path': 'imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl',
    'url': 'https://mirrors.aliyun.com/pypi/packages/a0/2d/43c8522a2038e9d0e7dbdf3a61195ecc31ca576fb1527a528c877e87d973/imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl',
    'bytes': 29498237,
    'sha256': 'c7e46fcec401dd990405049d2e2f475e2b397779df2519b544b8aab515195282',
}


def main():
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only scoped toolchain')
    directory = ROOT/'workspace/models/sheetsage2/toolchain'
    free_space(250_000_000)
    wheel = download(directory, WHEEL)
    with zipfile.ZipFile(wheel['path']) as archive:
        binaries = [i for i in archive.infolist() if i.filename.startswith('imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-')]
        if len(binaries) != 1 or binaries[0].file_size > 200_000_000:
            raise RuntimeError('Unexpected binary in pinned FFmpeg wheel')
        binary = directory/'bin/ffmpeg'
        binary.parent.mkdir(parents=True, exist_ok=True)
        content = archive.read(binaries[0])
        if not content.startswith(b'\x7fELF'):
            raise RuntimeError('FFmpeg wheel did not contain an ELF binary')
        if binary.exists() and binary.read_bytes() != content:
            raise RuntimeError('Refusing to replace different FFmpeg binary')
        binary.write_bytes(content)
        binary.chmod(0o755)
        for item in archive.infolist():
            if 'license' in item.filename.lower() or 'copying' in item.filename.lower():
                if item.file_size > 1_000_000:
                    raise RuntimeError('Unexpected license size')
                target = directory/'licenses'/item.filename.replace('/', '__')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
    command = subprocess.run([str(binary), '-version'], check=True, capture_output=True, text=True, timeout=15)
    version = command.stdout.splitlines()[0]
    plan = json.loads((Path(__file__).parent/'artifacts.json').read_text())
    state = deployment('sheetsage2', plan)
    state['toolchain'] = {'ffmpeg': str(binary), 'version': version,
                          'source': 'https://pypi.org/project/imageio-ffmpeg/0.6.0/',
                          'transport_mirror': WHEEL['url'],
                          'scope': 'Explicit PATH prefix for SheetSage2 only; system PATH unchanged',
                          'limitation': 'Default subprocess decoder only; paper preset torchaudio FFmpeg shared-library backend unverified'}
    for entry in (wheel, artifact(binary)):
        state['artifacts'] = [i for i in state['artifacts'] if i['path'] != entry['path']] + [entry]
    save_deployment('sheetsage2', state)
    print(json.dumps({'ffmpeg': version, 'binary_sha256': artifact(binary)['sha256']}))


if __name__ == '__main__':
    main()
