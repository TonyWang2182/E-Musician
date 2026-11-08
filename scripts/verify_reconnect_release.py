from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, shutil

root = Path(__file__).resolve().parents[1]
review = root / 'docs/review/2026-11-08-cloud-reconnect-ui'
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
initial = read(review / 'NATIVE-INPUTS.json')
changes = [p for p,h in initial['inputs'].items() if sha(root/p) != h]
assert changes == ['tests/PopupStyleSmoke.h'], changes
fixture = root / changes[0]
assert hashlib.sha256(fixture.read_bytes().replace(b'Save as...', 'Save as\u2026'.encode())).hexdigest() == initial['inputs'][changes[0]]
assert all(sha(p) == h for p,h in initial['preserved_executables'].items())
native = {p:sha(root/p) for p in initial['inputs']}
exe = Path('E:/emusician-analysis-build/bin-0.13.1/Release/E-musician.exe')
latest = read(root / 'build/workspace-smoke/latest.json')
popup = Path(latest['directory']) / 'popup-style'
popup_report = read(popup / 'popup-style-report.json')
assert popup_report['status'] == 'passed'
for report in latest['reports'].values(): assert report['status'] == 'passed'
cloud_dir = Path('E:/MusicAgent&DAW/cloud-inference/experiments/hybrid-clone-v0131-20261108')
cloud = read(cloud_dir / 'report.json')
assert cloud['passed'] and cloud['protected_unchanged'] and cloud['frozen_exe_unchanged']
assert len(cloud['models']) == 7 and all(m['passed'] for m in cloud['models'])
for name in ('ui-popup-menu-150.png','ui-options-callout.png','ui-save-confirm-en.png','ui-save-confirm-zh-200.png','popup-style-report.json'):
    shutil.copy2(popup/name, review/name)
shutil.copy2(root/'build/english-live-v0131/report.json', review/'ENGLISH-LIVE.json')
shutil.copy2(root/'build/hybrid-agent-web/hybrid-generate-340-en.png', review/'agent-generate-en.png')
shutil.copy2(cloud_dir/'report.json', review/'CLOUD-END-TO-END.json')
audit = {'checked_utc':datetime.now(timezone.utc).isoformat(), 'passed':True,
         'final_exe':str(exe), 'final_exe_sha256':sha(exe), 'native_inputs':native,
         'earlier_cloud_test_exe_sha256':cloud['exe_sha256'],
         'difference_from_cloud_test':'Only PopupStyleSmoke Save as ellipsis fixture literal corrected to ASCII; all 126 other native inputs unchanged. Final binary recompiled and native workspace smoke rerun; cloud inference not repeated for a test-label-only change.',
         'preserved_executables':initial['preserved_executables'],
         'workspace_directory':latest['directory'], 'popup_checks':len(popup_report['checks']),
         'cloud_output':str(cloud_dir), 'models':[{'id':m['model_id'],'passed':m['passed'],
         'phases':[{k:p[k] for k in ('phase','passed','elapsed_seconds')} for p in m['phases']]} for m in cloud['models']],
         'physical_audio_verified':False, 'musical_quality_verified':False}
(review/'VERIFICATION.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':True,'exe_sha256':audit['final_exe_sha256'],'popup_checks':audit['popup_checks'],
                 'models':len(cloud['models']),'production_native_inputs_unchanged':126},ensure_ascii=False))
