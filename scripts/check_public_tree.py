#!/usr/bin/env python3
"""Check publishable source for language, private paths, and credential material."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
PRIVATE_PATH = re.compile(r"C:[\\/]+Users[\\/]+28712|E:[\\/]+MusicAgent&DAW|connect\.bjb[0-9]+\.", re.I)
API_KEY = re.compile(r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{24,})")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{32,}")


def main() -> int:
    result = subprocess.run(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
        cwd=ROOT, capture_output=True, check=True,
    )
    names = sorted(set(result.stdout.decode('utf-8').split('\0')) - {''})
    failures: list[str] = []
    checked = 0
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        if CJK.search(name):
            failures.append(f'{name}: non-English filename')
        data = path.read_bytes()
        if b'\0' in data[:8192]:
            continue
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            continue
        checked += 1
        if CJK.search(text):
            failures.append(f'{name}: CJK source text')
        if PRIVATE_PATH.search(text):
            failures.append(f'{name}: maintainer-specific path or host')
        if PRIVATE_KEY.search(text):
            failures.append(f'{name}: private key material')
        for match in API_KEY.finditer(text):
            value = match.group()
            if name.startswith('tests/') and (value.startswith('sk-test') or len(set(value[3:])) == 1):
                continue
            failures.append(f'{name}: possible API credential (value withheld)')
            break
    for failure in failures:
        print(failure)
    print(f'Checked {checked} text files; {len(failures)} issues.')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
