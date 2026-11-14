from pathlib import Path
from datetime import datetime, timezone
import json, re, shutil, subprocess

directory = Path('E:/MusicAgent&DAW/cloud-inference/connection')
backup = directory / ('previous-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir()
config = directory / 'ssh_config'
metadata = directory / 'connection.json'
for path in (config, metadata):
    shutil.copy2(path, backup / path.name)
old = config.read_text(encoding='utf-8-sig')
assert old.count('Host emusician-autodl') == 1
# This generated include currently has exactly one Host stanza.
assert len(re.findall(r'^Host\s', old, flags=re.M)) == 1
new, n = re.subn(r'(?m)^(\s*HostName\s+)\S+\s*$', r'\g<1>connect.bjb1.seetacloud.com', old)
assert n == 1
new, n = re.subn(r'(?m)^(\s*Port\s+)\d+\s*$', r'\g<1>22095', new)
assert n == 1 and 'StrictHostKeyChecking yes' in new
config.write_text(new, encoding='utf-8')
value = json.loads(metadata.read_text(encoding='utf-8-sig'))
value.update(hostname='connect.bjb1.seetacloud.com', port=22095,
             authentication='SSH key', password_stored=False)
metadata.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
resolved = subprocess.check_output(['ssh','-G','emusician-autodl'], text=True)
assert 'hostname connect.bjb1.seetacloud.com' in resolved and 'port 22095' in resolved
report = {'alias':'emusician-autodl','hostname':value['hostname'],'port':22095,
          'password_used_or_stored':False,'authentication':'existing SSH key',
          'backup_directory':str(backup),'strict_host_key_checking':True}
Path('docs/review/2026-11-14-reconnect-icons/CONNECTION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
