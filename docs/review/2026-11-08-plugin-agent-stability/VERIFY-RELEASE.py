from pathlib import Path
import datetime, hashlib, json, subprocess

root=Path.cwd()
folder=root/'docs/review/2026-11-08-plugin-agent-stability'
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def record(suffix): return json.loads(next((root/'docs/builds').glob('*'+suffix+'.json')).read_text(encoding='utf-8'))
native=json.loads((folder/'NATIVE-INPUTS-FINAL.json').read_text())
changed=[name for name,value in native.items() if digest(root/name)!=value]
assert not changed, changed
py=record('b9c850ad3d')['source_fingerprint']['files']
web=record('2e034e6a40')['source_fingerprint']['files']
agent={str(p.relative_to(root)).replace('\\','/'):p for p in (root/'scripts/music_agent').rglob('*') if p.suffix in {'.py','.js','.html','.css'}}
for name,p in agent.items():
    expected=web if '/web/' in name else py
    assert name in expected and digest(p)==expected[name], name
old=json.loads((folder/'PRESERVED.json').read_text())
assert digest(old['exe'])==old['sha256']
ps=r'''
$p=Get-Process -Id 24792 -ErrorAction Stop
$child=Get-CimInstance Win32_Process -Filter 'ParentProcessId=24792' | Where-Object Name -eq 'python.exe' | Select-Object -First 1
$match=[regex]::Match($child.CommandLine,'--embedded-session\s+"?(.+?\.json)"?(?:\s|$)')
$cfg=Get-Content -LiteralPath $match.Groups[1].Value -Raw | ConvertFrom-Json
$connections=@(Get-NetTCPConnection -OwningProcess 24792 -State Established -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $cfg.port -and $_.RemoteAddress -eq '127.0.0.1' })
[pscustomobject]@{pid=$p.Id;path=$p.Path;title=$p.MainWindowTitle;responding=$p.Responding;helper_pid=$child.ProcessId;helper_alive=($null -ne $child);control_socket_connected=($connections.Count -gt 0);ready_file_consumed=(!(Test-Path -LiteralPath $cfg.ready_path));age_seconds=((Get-Date)-$p.StartTime).TotalSeconds} | ConvertTo-Json -Compress
'''
live=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',ps],encoding='utf-8-sig'))
assert live['responding'] and '0.13.2' in live['title'] and live['helper_alive']
assert live['control_socket_connected'] and live['ready_file_consumed'] and live['age_seconds']>45
exe=Path('E:/emusician-analysis-build/bin-0.13.2-final/Release/E-musician.exe')
assert Path(live['path'])==exe
data={'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'passed',
      'native_inputs':len(native),'native_inputs_changed':changed,'agent_and_web_inputs_verified':len(agent),
      'python_test_record':'b9c850ad3d','web_test_record':'2e034e6a40','build_record':'bf75fc0851','ctest_record':'1ccfefae75',
      'exe':str(exe),'exe_sha256':digest(exe),'old_native_exe_preserved':True,'application':live,
      'helper_connection_evidence':'owned Python child, matching established control socket, consumed ready file after 45-second startup limit',
      'hardware_audio_or_listening_verified':False,'cloud_models_changed':False}
(folder/'VERIFICATION.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(data,ensure_ascii=False))
