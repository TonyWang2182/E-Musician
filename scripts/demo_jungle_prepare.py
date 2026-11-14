"""Bounded download and indexing of public demo sources; no DAW/model calls."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile
import time

ROOT=Path('E:/MusicAgent&DAW/demo-video/2026-11-14/jungle-materials')
UA='E-musician-demo-source-preparation/1.0'

def open_retry(request, timeout=60):
    for attempt in range(3):
        try:return urllib.request.urlopen(request,timeout=timeout)
        except Exception:
            if attempt == 2:raise
            time.sleep(1+attempt)

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()

def download(url, destination, limit):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        print('Reusing '+str(destination),flush=True)
        return {'url':url,'path':str(destination),'bytes':destination.stat().st_size,'sha256':digest(destination),'reused':True}
    part=destination.with_suffix(destination.suffix+'.partial')
    if part.exists():raise RuntimeError('Existing partial preserved: '+str(part))
    count=0
    with open_retry(urllib.request.Request(url,headers={'User-Agent':UA})) as response,part.open('xb') as output:
        length=response.headers.get('Content-Length')
        if length and int(length)>limit:raise ValueError('Source exceeds bounded download size')
        while True:
            block=response.read(1024*1024)
            if not block:break
            count+=len(block)
            if count>limit:raise ValueError('Source exceeded bounded size')
            output.write(block)
    part.replace(destination)
    print('Downloaded '+destination.name+' '+str(count)+' bytes',flush=True)
    return {'url':url,'path':str(destination),'bytes':count,'sha256':digest(destination),'reused':False}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['indices','reference','reference-pages'])
    args=parser.parse_args();ROOT.mkdir(parents=True,exist_ok=True)
    records=[]
    if args.stage=='indices':
        for url,name in [
            ('https://api.github.com/repos/LMMS/assets/git/trees/bc09e0745c69c73bd6c3112122031e4963ce3876?recursive=1','lmms-tree.json'),
            ('https://api.github.com/repos/freepats/synth-bass-lead/git/trees/426f32da700c42a4071b5061ee3bb2fc92de0680?recursive=1','freepats-bass-tree.json'),
            ('https://api.github.com/repos/freepats/synth-pad-choir/git/trees/b801f7fc3eee44f575cd480750aea4f6a16a07a9?recursive=1','freepats-pad-tree.json'),
            ('https://archive.org/metadata/producer-space-cc0-sample-library','producer-space-metadata.json'),
            ('https://producerspace.com/license','producer-space-license.html')]:
            records.append(download(url,ROOT/'evidence'/name,16*1024*1024))
    elif args.stage=='reference-pages':
        for url,name in [
            ('https://www.antidoteaudio.com/jungle-inside-of-ableton','antidote-project-page.html'),
            ('https://www.antidoteaudio.com/licensing-and-terms','antidote-terms.html')]:
            records.append(download(url,ROOT/'evidence'/name,16*1024*1024))
    else:
        url='https://dl.dropboxusercontent.com/s/jwlwi4fc0mqxlzj/Antidote%20Audio%20-%20Jungle%20in%20Ableton%20Project.zip?dl=0'
        path=ROOT/'personal-reference'/'Antidote Audio - Jungle in Ableton Project.zip'
        records.append(download(url,path,200*1024*1024))
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            entries=[{'name':i.filename,'bytes':i.file_size,'compressed':i.compress_size} for i in z.infolist()]
        (ROOT/'evidence'/'antidote-zip-index.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result={'time_utc':datetime.now(timezone.utc).isoformat(),'stage':args.stage,'downloads':records}
    (ROOT/'evidence').mkdir(exist_ok=True)
    (ROOT/'evidence'/('download-'+args.stage+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
