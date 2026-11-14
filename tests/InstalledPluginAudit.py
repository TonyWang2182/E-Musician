"""Sequential, bounded installed-plugin audit. Native editors are opt-in.

Each module has an independent offline DAW process. Windows Job Objects bound
the entire owned child tree, including the renderer, to the module's deadline.
Passing means this machine/default program passed these checks, not all presets,
licence states, editor gestures, hardware or third-party native code are safe.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(os.environ['APPDATA']) / 'E-musician/plugins-v1/catalog.json'
SEARCH_ROOTS = [Path(p) for p in (
    'C:/Program Files/Common Files/VST3', 'C:/Program Files/VstPlugins',
    'C:/Program Files/Steinberg/VstPlugins', 'C:/Program Files/Common Files/VST2',
    str(Path.home() / 'AppData/Local/Programs/Common/VST3'))]


def bundle_interior(path: Path) -> bool:
    return any(parent.suffix.lower() == '.vst3' for parent in path.parents)


def inventory():
    paths: dict[str, Path] = {}
    excluded = []
    def add(path):
        path = Path(path)
        if bundle_interior(path):
            excluded.append(str(path)); return
        if path.exists() and path.suffix.lower() in {'.vst3', '.dll'}:
            paths[str(path).lower()] = path
    if CATALOG.exists():
        for item in json.loads(CATALOG.read_text(encoding='utf-8-sig'))['plugins']:
            add(ET.fromstring(item['description']).get('file', ''))
    for root in SEARCH_ROOTS:
        if not root.exists(): continue
        for directory, children, files in os.walk(root):
            for name in children[:]:
                if name.lower().endswith('.vst3'):
                    add(Path(directory) / name); children.remove(name)
            for name in files:
                if name.lower().endswith(('.vst3', '.dll')):
                    add(Path(directory) / name)
    return sorted(paths.values(), key=lambda p: str(p).lower()), sorted(set(excluded))


class OwnedJob:
    """Close/timeout terminates only descendants assigned to this audit item."""
    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t),
                        ('max_ws', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended(); limits.basic.flags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close(); raise ctypes.WinError(ctypes.get_last_error())
    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            process.kill(); process.wait()
            raise ctypes.WinError(ctypes.get_last_error())
    def kill(self): self.api.TerminateJobObject(self.handle, 124)
    def close(self):
        if self.handle: self.api.CloseHandle(self.handle); self.handle = None


def bounded_run(command, log, deadline):
    started = time.monotonic()
    job = OwnedJob()
    try:
        with log.open('wb') as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            job.assign(process)
            try: code = process.wait(timeout=deadline)
            except subprocess.TimeoutExpired:
                job.kill(); code = process.wait(timeout=10)
                return {'exit_code':code, 'timed_out':True, 'seconds':time.monotonic()-started}
            return {'exit_code':code, 'timed_out':False, 'seconds':time.monotonic()-started}
    finally: job.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--module', type=Path, action='append', default=[])
    parser.add_argument('--deadline', type=int, default=180)
    parser.add_argument('--editor-deadline', type=int, default=45)
    parser.add_argument('--probe-editors', action='store_true')
    parser.add_argument('--open-editors', action='store_true', help='Exercise production open_plugin in each owned offline host')
    parser.add_argument('--ui-handlers', action='store_true', help='Also exercise actual Library/Add/Open/Remove GUI callbacks without control-stdio')
    parser.add_argument('--skip-scan', action='store_true', help='Read existing exact descriptors without changing the catalog')
    args = parser.parse_args()
    if not args.exe.is_file(): parser.error('EXE does not exist')
    if not 30 <= args.deadline <= 600: parser.error('Deadline must be 30..600 seconds')
    args.out.mkdir(parents=True, exist_ok=False)
    if CATALOG.exists(): shutil.copy2(CATALOG, args.out / 'catalog-before.json')
    paths, excluded = inventory() if not args.module else (args.module, [])
    result = {'started_utc':datetime.now(timezone.utc).isoformat(), 'exe':str(args.exe),
              'exe_sha256':hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              'scope':'installed/default paths plus existing custom catalog paths; one default program per module',
              'physical_sound_verified':False, 'visible_gui_verified':False,
              'sample_rate':48000, 'render_duration_seconds':2, 'editor_block_size':512,
              'excluded_vst3_internals':excluded, 'total':len(paths), 'completed':0, 'items':[]}
    def save():
        result['counts'] = dict(Counter(item['status'] for item in result['items']))
        (args.out / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    save()
    for index, module in enumerate(paths):
        name = f'{index+1:03d}-'+hashlib.sha256(str(module).encode()).hexdigest()[:10]
        folder = args.out / name; folder.mkdir()
        item = {'module':str(module), 'status':'running', 'folder':name}
        result['items'].append(item); save()
        command = [sys.executable, '-X', 'utf8', str(ROOT / 'tests/InstalledPluginProbe.py'),
                   '--exe', str(args.exe), '--module', str(module), '--out', str(folder / 'host')]
        if args.open_editors: command.append('--open-editor')
        if args.skip_scan: command.append('--skip-scan')
        item['host_process'] = bounded_run(command, folder / 'host.log', args.deadline)
        report = folder / 'host/report.json'
        if report.exists(): item['host'] = json.loads(report.read_text(encoding='utf-8'))
        item['status'] = ('passed' if item['host_process']['exit_code']==0
                          and item.get('host', {}).get('status')=='passed' else 'failed')
        if args.probe_editors and item['status']=='passed':
            output = folder / 'editor.json'
            command = [str(args.exe), '--plugin-scan-worker', 'VST' if module.suffix.lower()=='.dll' else 'VST3',
                       str(module), str(output), '--probe-editor']
            item['editor_process'] = bounded_run(command, folder / 'editor.log', args.editor_deadline)
            if output.exists(): item['editor'] = json.loads(output.read_text(encoding='utf-8-sig'))
            if item['editor_process']['exit_code']!=0 or item.get('editor', {}).get('status')!='completed':
                item['status']='editor_failed'
        if args.ui_handlers and item['status']=='passed':
            descriptor=next(p for p in item['host']['descriptors'] if p['available'])
            if descriptor['is_instrument']:
                output=folder/'gui'
                command=[str(args.exe),'--plugin-ui-test',descriptor['id'],str(output.resolve()),'--offline']
                item['gui_process']=bounded_run(command,folder/'gui.log',args.deadline)
                if (output/'plugin-ui-report.json').exists():
                    item['gui']=json.loads((output/'plugin-ui-report.json').read_text(encoding='utf-8-sig'))
                if item['gui_process']['exit_code']!=0 or item.get('gui',{}).get('status')!='passed':
                    item['status']='gui_failed'
            else:
                item['gui']={'status':'not_tested','reason':'instrument-only UI handler harness'}
        result['completed']=index+1; save()
        print(json.dumps({'completed':index+1,'total':len(paths),'module':module.name,
                          'status':item['status'],'stage':item.get('host',{}).get('stage')},ensure_ascii=False),flush=True)
    result['finished_utc']=datetime.now(timezone.utc).isoformat(); save()
    print('Audit report: '+str(args.out / 'audit.json'),flush=True)
    # Report failures individually; a complete diagnostic audit itself succeeds.
    return 0


if __name__=='__main__': raise SystemExit(main())
