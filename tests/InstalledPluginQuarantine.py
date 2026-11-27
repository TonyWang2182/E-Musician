"""Mark explicitly selected, failed audited descriptors unavailable; preserve IDs.

Only mutates the host catalog, never plug-in binaries, presets or projects.
A deliberate subsequent scan of the module replaces this availability record.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from InstalledPluginAudit import CATALOG
from PluginHostSmoke import normal_path, signed_hex


def catalog_id(xml):
    text='\n'.join([xml.get('format',''),xml.get('file','').lower(),
                    str(signed_hex(xml.get('uniqueId','0'))),str(signed_hex(xml.get('uid','0')))])
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--module',type=Path,action='append',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    audit=json.loads(args.audit.read_text(encoding='utf-8'))
    if audit.get('completed')!=audit.get('total'):raise RuntimeError('Audit must finish before quarantine.')
    selected={normal_path(p) for p in args.module}
    items=[item for item in audit['items'] if normal_path(item['module']) in selected]
    if len(items)!=len(selected):raise RuntimeError('Each explicit module must be present exactly once in this audit.')
    required={'instantiate exact catalog identity','save native state','reopen native state'}
    identities={}
    for item in items:
        host=item.get('host',{})
        if item['status']!='failed' or host.get('stage')!='offline_render' or not required.issubset(host.get('checks',[])):
            raise RuntimeError('Quarantine requires the confirmed export-transaction failure, not a scan timeout.')
        if 'Control process closed stdout' not in host.get('error',''):
            raise RuntimeError('Control-process exit evidence is required.')
        good=[descriptor for descriptor in host.get('descriptors',[]) if descriptor.get('available')]
        if len(good)!=1:raise RuntimeError('Exactly one audited descriptor is required; do not quarantine untested classes.')
        identities[normal_path(item['module'])]=good[0]['id']
    before=CATALOG.read_bytes(); catalog=json.loads(before.decode('utf-8-sig'))
    changed=[]
    for entry in catalog['plugins']:
        xml=ET.fromstring(entry['description']); path=normal_path(xml.get('file',''))
        if path not in identities:continue
        if catalog_id(xml)!=identities[path]:raise RuntimeError('Catalog identity changed after the audit; refusing quarantine.')
        entry['available']=False
        entry['error']=('Local compatibility quarantine: scan/load/state passed, but the control host exited after '
                        'a 2-second export produced its output on 0.13.2. Not validated for use. '
                        'Plug-in files and project state are preserved. Explicit rescan clears this quarantine.')
        changed.append({'module':xml.get('file'),'catalog_id':identities[path],'name':xml.get('name'),'error':entry['error']})
    if len(changed)!=len(selected):raise RuntimeError('Missing or repeated catalog identities; no catalog written.')
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'catalog-before.json').write_bytes(before)
    temporary=CATALOG.with_suffix('.plugin-quarantine.tmp')
    temporary.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,CATALOG)
    after=CATALOG.read_bytes()
    report={'audit':str(args.audit),'before_sha256':hashlib.sha256(before).hexdigest(),
            'after_sha256':hashlib.sha256(after).hexdigest(),'quarantined':changed,
            'other_entries_preserved':True,'plugin_files_or_projects_modified':False}
    (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
