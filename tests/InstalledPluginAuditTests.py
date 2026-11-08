"""Audit isolation/discovery regression checks; no installed plugin loaded."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import InstalledPluginAudit as audit
import InstalledPluginQuarantine as quarantine


class AuditTests(unittest.TestCase):
    def test_bundle_dependencies_are_not_plugin_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'Instrument.vst3'
            dependency = bundle / 'Contents/x86_64-win/REX Shared Library.dll'
            dependency.parent.mkdir(parents=True); dependency.touch()
            standalone = root / 'Effect.dll'; standalone.touch()
            custom = root / 'Custom.vst3'; custom.touch()
            cache = root / 'catalog.json'
            cache.write_text(json.dumps({'plugins':[
                {'description':ET.tostring(ET.Element('PLUGIN',file=str(dependency)),encoding='unicode')},
                {'description':ET.tostring(ET.Element('PLUGIN',file=str(custom)),encoding='unicode')}]}),encoding='utf-8')
            before=cache.read_bytes()
            with patch.object(audit,'CATALOG',cache), patch.object(audit,'SEARCH_ROOTS',[root]):
                paths, excluded=audit.inventory()
            self.assertEqual(set(paths),{bundle,standalone,custom})
            self.assertEqual(excluded,[str(dependency)])
            self.assertEqual(cache.read_bytes(),before)

    def test_job_timeout_terminates_owned_grandchild(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); pid_file=root/'pid.txt'
            code=('import subprocess,sys,time,pathlib;'
                  'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
                  f'pathlib.Path({str(pid_file)!r}).write_text(str(p.pid));'
                  'time.sleep(60)')
            result=audit.bounded_run([sys.executable,'-c',code],root/'process.log',1.5)
            self.assertTrue(result['timed_out'])
            self.assertTrue(pid_file.exists())
            pid=int(pid_file.read_text())
            api=ctypes.WinDLL('kernel32',use_last_error=True)
            api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            api.OpenProcess.restype=wintypes.HANDLE
            api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            api.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=api.OpenProcess(0x1000,False,pid)
            if handle:
                try:
                    code=wintypes.DWORD()
                    self.assertTrue(api.GetExitCodeProcess(handle,ctypes.byref(code)))
                    self.assertNotEqual(code.value,259,'Owned grandchild remained alive')
                finally:api.CloseHandle(handle)

    def test_success_retains_exit_and_output(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'process.log'
            result=audit.bounded_run([sys.executable,'-c','print("isolated audit child")'],log,5)
            self.assertFalse(result['timed_out'])
            self.assertEqual(result['exit_code'],0)
            self.assertIn(b'isolated audit child',log.read_bytes())

    def test_quarantine_preserves_other_entries_and_exact_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);module=root/'Failed.vst3';cache=root/'catalog.json'
            xml=ET.Element('PLUGIN',file=str(module),format='VST3',name='Failed',uniqueId='42',uid='43')
            failed={'description':ET.tostring(xml,encoding='unicode'),'available':True,'error':''}
            other={'description':'<PLUGIN file="C:/Other.vst3" format="VST3" />','available':True,'error':'preserved'}
            cache.write_text(json.dumps({'schema':1,'plugins':[failed,other]}),encoding='utf-8')
            original=cache.read_bytes()
            record={'completed':1,'total':1,'items':[{'module':str(module),'status':'failed','host':{
                'stage':'offline_render','error':'ControlError: Control process closed stdout.',
                'checks':['instantiate exact catalog identity','save native state','reopen native state'],
                'descriptors':[{'available':True,'id':quarantine.catalog_id(xml)}]}}]}
            audit_path=root/'audit.json';audit_path.write_text(json.dumps(record),encoding='utf-8')
            arguments=['quarantine','--audit',str(audit_path),'--module',str(module),'--out',str(root/'out')]
            with patch.object(quarantine,'CATALOG',cache),patch.object(sys,'argv',arguments):
                self.assertEqual(quarantine.main(),0)
            updated=json.loads(cache.read_text(encoding='utf-8'))
            self.assertFalse(updated['plugins'][0]['available'])
            self.assertEqual(updated['plugins'][0]['description'],failed['description'])
            self.assertEqual(updated['plugins'][1],other)
            self.assertEqual((root/'out/catalog-before.json').read_bytes(),original)


if __name__=='__main__':unittest.main()
