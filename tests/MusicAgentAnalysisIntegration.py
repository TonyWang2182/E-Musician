"""Real owned DAW + local chord/optional six-stem models + deterministic LLM.

This validates the shared analysis/import/edit pipeline, not musical accuracy or
live ASIO performance. Never accesses user projects or a paid model API.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
import struct
import sys
import time
from unittest.mock import patch
import uuid
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from agent_client import Client, ControlError
from music_agent.bridge import DawBridge, BridgeError
from music_agent.runtime import AgentRuntime
from music_agent.config import DEFAULT_CONFIG
from music_agent.analysis import authorize_start
from music_agent.selection import freeze_scope
from dev import configure_console_output
from MusicAgentIntegration import protected

def tool(name,args):
    return {"message":{"role":"assistant","content":None,"tool_calls":[{"id":"fixture-call","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]},"usage":{}}

class Provider:
    model='deterministic-integration-fixture';base_url='https://example.invalid';provider_id='kimi'
    def __init__(self,name,args):self.name=name;self.args=args;self.calls=0
    def complete(self,messages,tools):self.calls+=1;return tool(self.name,self.args)

class StartProvider(Provider):
    def __init__(self,clip,kind='chords',parameters=None):
        super().__init__('start_audio_analysis',{"clip_id":clip,"kind":kind})
        if parameters is not None:self.args['parameters']=parameters
    def complete(self,messages,tools):
        self.calls+=1
        if self.calls==1:return tool(self.name,self.args)
        reply=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
        assert reply['job']['status']=='ready'
        return tool('propose_analysis_import',{'result_id':reply['candidate']['result_id'],'summary':'Import actual local analysis candidates'})

class Audit:
    def write(self,*args,**kwargs):pass

def main():
    configure_console_output()
    ap=argparse.ArgumentParser();ap.add_argument('--exe',type=Path,required=True);ap.add_argument('--timeout',type=float,default=180)
    ap.add_argument('--six-stems',action='store_true',help='Also exercise real HTDemucs six-stem inference through Agent confirmation/readback/Undo/Redo')
    args=ap.parse_args()
    directory=ROOT/'build'/'agent-analysis-e2e'/uuid.uuid4().hex;directory.mkdir(parents=True)
    # Keep the test process independent of a concurrent MSBuild relink.
    frozen_exe=directory/'E-musician.exe';shutil.copy2(args.exe,frozen_exe)
    executable_hash=hashlib.sha256(frozen_exe.read_bytes()).hexdigest()
    path=directory/'synthetic-triad.wav';rate=22050
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate)
        out.writeframes(b''.join(struct.pack('<h',round(32767*.13*sum(math.sin(2*math.pi*f*i/rate) for f in (261.625565,329.627557,391.995436)))) for i in range(rate*4)))
    report={'passed':False,'mode':'owned-offline-DAW-real-local-chords-and-six-stems' if args.six_stems else 'owned-offline-DAW-real-local-chords','physical_audio':False,'external_llm':False,'music_accuracy_claim':False,'input_executable':str(args.exe),'exe_sha256':executable_hash,'checks':[]}
    checks=report['checks'];before=protected();client=None
    def wait(runtime):
        runtime.worker.join(args.timeout)
        assert not runtime.busy(),'Agent local analysis/import wait timed out'
        if runtime.phase=='error':raise AssertionError(runtime.error)
    def wait_analysis(bridge,jid):
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            state=bridge.analysis_job(jid)
            if state['status']=='ready':return state
            if state['status'] in ('failed','stale','cancelled'):raise AssertionError(state)
            time.sleep(.1)
        raise AssertionError('Actual local inference did not finish')
    try:
        client=Client(frozen_exe,timeout=args.timeout,show=False,offline_test=True)
        assert not client.state()['tracks']
        client.request({'command':'import_audio','args':{'paths':[str(path)]}})
        bridge=DawBridge(client=client);snapshot=bridge.snapshot();clip=snapshot['tracks'][0]['clips'][0]['id']
        caps=bridge.analysis_capabilities();assert any(p['kind']=='chords' and p['available'] for p in caps['providers'])
        checks.append('Actual host commands and local chord runtime advertise readiness; no API key used')
        acknowledgment=client.request({'command':'start_analysis','args':{'kind':'chords','clip_id':clip}},wait=False)
        job=wait_analysis(bridge,acknowledgment['result']['job_id']);rid=job['result_id'];candidate=bridge.analysis_result(rid)
        assert candidate['total']>0 and candidate['source']['clip_id']==clip and not candidate['applied']
        assert 'path' not in json.dumps(candidate) and bridge.chord_page(bridge.snapshot(),clip)['total']==0
        checks.append('Manual native start executes real Chroma/HMM; Agent reads same immutable result with no project changes')
        with patch('music_agent.runtime.has_key',return_value=False),patch('music_agent.providers.has_key',return_value=False),patch('music_agent.runtime.load_config',return_value=DEFAULT_CONFIG):
            runtime=AgentRuntime(bridge,provider=Provider('propose_analysis_import',{'result_id':rid,'summary':'Import reviewed chord candidate'}),audit=Audit())
            # A stdio process has no genuine GUI music selection. Explicit
            # project scope is required; never fabricate a selected clip.
            report['initial_selection']=snapshot.get('selection_context')
            rev=bridge.snapshot()['revision'];runtime.plan_request('Import reviewed chords',scope='project');wait(runtime)
            assert runtime.phase=='ready' and bridge.snapshot()['revision']==rev
            plan_id=runtime.plan['id'];runtime.apply(plan_id);wait(runtime)
            assert runtime.phase=='done' and runtime.undo_target and bridge.snapshot()['revision']==rev+1
            regions=bridge.chord_page(bridge.snapshot(),clip);assert regions['total']==candidate['total']
            checks.append('Agent confirmation submits one asynchronous native import; receipt/regions verified after completion')
            try:runtime.apply(plan_id)
            except ValueError:pass
            else:raise AssertionError('Same plan accepted twice')
            imported_revision=bridge.snapshot()['revision']
            replay=client.request({'command':'accept_analysis_result','args':{'result_id':rid}},wait=False)
            assert replay['status']=='completed' and replay['result']['result_id']==rid
            assert bridge.snapshot()['revision']==imported_revision and bridge.chord_page(bridge.snapshot(),clip)['total']==candidate['total']
            runtime.undo();wait(runtime);assert bridge.chord_page(bridge.snapshot(),clip)['total']==0
            client.request({'command':'redo'});assert bridge.chord_page(bridge.snapshot(),clip)['total']==candidate['total']
            checks.append('Plan and candidate deduplicate; one Undo removes all chord regions and Redo restores them')
            region=bridge.chord_page(bridge.snapshot(),clip)['items'][0];label='D:min' if region['label']!='D:min' else 'C:maj'
            runtime.provider=Provider('propose_chord_edit',{'clip_id':clip,'region_id':region['id'],'label':label,'summary':'Correct one chord label'})
            runtime.plan_request('Correct one chord',scope='project');wait(runtime);assert runtime.phase=='ready'
            assert bridge.find_chord(bridge.snapshot(),region['id'],clip)['label']==region['label']
            runtime.apply(runtime.plan['id']);wait(runtime);assert runtime.phase=='done'
            assert bridge.find_chord(bridge.snapshot(),region['id'],clip)['label']==label
            runtime.undo();wait(runtime);assert bridge.find_chord(bridge.snapshot(),region['id'],clip)['label']==region['label']
            checks.append('Persisted chord label can be proposed, confirmed, independently read back and undone through Agent')
            project=directory/'analysis.emproj';client.request({'command':'save_project','args':{'path':str(project)}})
            client.request({'command':'open_project','args':{'path':str(project)}})
            assert bridge.chord_page(bridge.snapshot(),clip)['total']==candidate['total']
            checks.append('Chord source provenance and labels survive real project save/reopen; original audio remains')
            runtime.provider=StartProvider(clip);runtime.plan_request('Analyze the specified source audio locally',scope='project');wait(runtime)
            assert runtime.phase=='ready' and runtime.provider.calls==2
            assert runtime.plan['analysis']['result_id']!=rid
            assert bridge.chord_page(bridge.snapshot(),clip)['total']==candidate['total']
            checks.append('Agent starts and locally polls real inference, then prepares review with exactly two mocked LLM requests; no automatic import')
            runtime.cancel()
            groups=runtime.state()['capability_groups'];assert len(groups)==10 and next(g for g in groups if g['id']=='chords')['status']=='not_applicable'
            checks.append('Fixed UI capability state comes from actual host, adapter and local model readiness')
            if args.six_stems:
                assert caps.get('separation_six_stems') is True
                assert any(p['kind']=='separate' and p['available'] for p in caps['providers'])
                before_separation=bridge.snapshot();before_tracks={t['id'] for t in before_separation['tracks']}
                source_before=next(c for t in before_separation['tracks'] for c in t['clips'] if c['id']==clip)
                runtime.provider=StartProvider(clip,'separate',{'stems':6,'quality':'fast'})
                runtime.plan_request('Separate the source into vocals, drums, bass, piano, guitar and other; prepare an import for confirmation',scope='project');wait(runtime)
                assert runtime.phase=='ready' and runtime.provider.calls==2
                candidate6=runtime.plan['analysis'];rid6=candidate6['result_id']
                names={'vocals','drums','bass','piano','guitar','other'}
                assert candidate6['kind']=='separate' and candidate6['total']==6 and candidate6['parameters']['stems']==6
                assert {item['name'] for item in candidate6['items']}==names
                assert bridge.snapshot()['revision']==before_separation['revision']
                assert {t['id'] for t in bridge.snapshot()['tracks']}==before_tracks
                assert not candidate6['applied'] and 'waveform_peaks' not in json.dumps(candidate6)
                report['six_stems']={'result_id':rid6,'model':candidate6['model'],'parameters':candidate6['parameters'],'source_sha256':candidate6['source']['source_sha256']}
                checks.append('Agent starts actual six-stem HTDemucs, polls locally and prepares a six-track review in two mocked LLM calls; no premature mutation')
                runtime.apply(runtime.plan['id']);wait(runtime)
                assert runtime.phase=='done' and runtime.undo_target
                added=bridge.snapshot();assert added['revision']==before_separation['revision']+1
                imported=[t for t in added['tracks'] if t['id'] not in before_tracks]
                assert len(imported)==6 and {t['name'] for t in imported}=={'Separated / '+name for name in names}
                assert all(len(t['clips'])==1 and t['clips'][0]['kind']=='audio' for t in imported)
                role_ids={t['clips'][0]['analysis_role']:(t['id'],t['clips'][0]['id']) for t in imported}
                assert set(role_ids)==names
                assert all(abs(t['clips'][0]['start_seconds']-candidate6['source']['timeline_start'])<1e-6 for t in imported)
                assert next(c for t in added['tracks'] for c in t['clips'] if c['id']==clip)==source_before
                assert bridge.analysis_result(rid6)['applied'] is True
                report['six_stems']['role_ids']=role_ids
                checks.append('Explicit Agent confirmation imports exactly six named audio tracks; runtime readback verifies IDs, audio kinds, positions and instrument roles')
                runtime.undo();wait(runtime)
                assert {t['id'] for t in bridge.snapshot()['tracks']}==before_tracks
                client.request({'command':'redo'})
                restored=bridge.snapshot()
                assert {t['id'] for t in restored['tracks']}==before_tracks|{pair[0] for pair in role_ids.values()}
                assert {c['analysis_role']:(t['id'],c['id']) for t in restored['tracks'] if t['id'] not in before_tracks for c in t['clips']}==role_ids
                checks.append('One Agent Undo removes all six imported tracks; one native Redo restores the same six track/clip IDs and roles')
                project6=directory/'six-stems.emproj'
                client.request({'command':'save_project','args':{'path':str(project6)}})
                client.request({'command':'open_project','args':{'path':str(project6)}})
                reopened=bridge.snapshot();scope=freeze_scope(reopened,'project')
                assert {c['analysis_role']:(t['id'],c['id']) for t in reopened['tracks'] if t['id'] not in before_tracks for c in t['clips']}==role_ids
                for role in ('piano','guitar'):
                    request=authorize_start(reopened,scope,{'clip_id':role_ids[role][1],'kind':'transcribe','parameters':{'instrument':'auto'}})
                    assert request['parameters']['instrument']=='auto'
                request=authorize_start(reopened,scope,{'clip_id':role_ids['other'][1],'kind':'transcribe','parameters':{'instrument':'piano'}})
                assert request['parameters']['instrument']=='piano'
                checks.append('Six-stem project saves/reopens with roles intact; piano/guitar Auto and explicit other profile pass Agent authorization without another model run')
        report['passed']=True
    finally:
        if client:client.close()
        report['protected_settings_unchanged']=before==protected()
        report['passed']=report['passed'] and report['protected_settings_unchanged']
        (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2));print(directory/'result.json')
    assert report['passed']

if __name__=='__main__':main()
