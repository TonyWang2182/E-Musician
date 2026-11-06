"""Small deployment progress report, without environment variables/secrets."""
import json
import time
from pathlib import Path

root = Path('/root/autodl-tmp/emusician')
files = []
for p in (root / 'models').rglob('*.partial'):
    stat = p.stat()
    files.append({'path': p.relative_to(root).as_posix(), 'bytes': stat.st_size, 'seconds_since_write': round(time.time()-stat.st_mtime, 1)})
recent = []
for p in (root / 'cache/uv').rglob('*'):
    if p.is_file():
        stat = p.stat()
        if stat.st_size > 1024*1024 and time.time()-stat.st_mtime < 120:
            recent.append({'path': p.relative_to(root).as_posix(), 'bytes': stat.st_size, 'seconds_since_write': round(time.time()-stat.st_mtime, 1)})
recent.sort(key=lambda f: f['bytes'], reverse=True)
print(json.dumps({'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'partial_files': files, 'recent_env_files': recent[:12]}, indent=2))
