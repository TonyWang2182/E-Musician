"""Real DAW + real Beat This + deterministic language fixture (no API cost).

Run only against the new native build through scripts.dev.Recorder. This is a
pipeline test using an attributed local public excerpt, not a music-quality or
hardware test. The original source and user projects are never modified.
"""
from pathlib import Path
import argparse
from copy import deepcopy
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from agent_client import Client
from music_agent.bridge import DawBridge
from music_agent.runtime import AgentRuntime
from music_agent.config import DEFAULT_CONFIG
from music_agent.tempo import verify_tempo_plan
from MusicAgentIntegration import protected
from MusicAgentAnalysisIntegration import Provider,Audit,tool

def protected_snapshot():
    """Preserve the shared guard and inventory additions beyond its hash filter."""
    app=(Path(os.environ['APPDATA'])/'E-musician').resolve()
    projects=Path('E:/E-musician/test-projects').resolve()
    hashes=dict(protected())
    for name in ('ui-language.txt','follow-playhead.txt'):
        path=app/name
        # An absent preference becoming present must also fail protection.
        hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    files={str(p) for root in (app,projects) if root.is_dir() for p in root.rglob('*') if p.is_file()}
    return {'hashes':hashes,'files':files,'app_root':app,'projects_root':projects}

def protected_changes(before,after):
    """Allow only NEW content-addressed Warp artifacts, never changed old ones."""
    app=before['app_root'];projects=before['projects_root']
    # Do not resolve a cache-directory junction into an unrelated location.
    cache=app/'cache'/'warp-v1'
    def allowed_new(path):
        resolved=Path(path).resolve()
        return resolved.parent==cache and re.fullmatch(r'[0-9a-fA-F]{64}\.(?:wav|json)',resolved.name) is not None
    def display(path):
        resolved=Path(path).resolve()
        for prefix,root in (('%APPDATA%/E-musician',app),('test-projects',projects)):
            if resolved.is_relative_to(root):return prefix+'/'+resolved.relative_to(root).as_posix()
        # Unexpected links must not leak personal/external absolute locations.
        return '<outside-protected-root>/'+hashlib.sha256(str(path).encode()).hexdigest()[:12]
    old=before['hashes'];new=after['hashes']
    changed=sorted(display(p) for p,digest in old.items() if p not in new or new[p]!=digest)
    added=after['files']-before['files']
    allowed=sorted(display(p) for p in added if allowed_new(p))
    unexpected=sorted(display(p) for p in added if not allowed_new(p))
    return {'unchanged':not changed and not unexpected,'changed_or_removed':changed,
        'unexpected_additions':unexpected,'allowed_new_warp_cache':allowed}

class StartBeats(Provider):
    def __init__(self,clip,mode):
        super().__init__('start_audio_analysis',{'clip_id':clip,'kind':'beats','parameters':{'meter':'auto'}});self.mode=mode
    def complete(self,messages,tools):
        self.calls+=1
        if self.calls==1:return tool(self.name,self.args)
        reply=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
        assert reply['job']['status']=='ready';candidate=reply['candidate']
        args={'result_id':candidate['result_id'],'mode':self.mode,'summary':'Review actual beat analysis and explicit timing action'}
        if self.mode=='project_to_audio':
            # Deliberate manual correction fixture; does not claim the model
            # recognized a 90 BPM waltz in this piece.
            args.update(bpm=90,numerator=3,denominator=4,first_beat_seconds=.25)
        elif candidate['tempo']['first_downbeat_seconds'] is None:
            args['first_beat_seconds']=.0
        return tool('propose_beat_application',args)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--exe',type=Path,required=True);ap.add_argument('--timeout',type=float,default=300)
    ap.add_argument('--source',type=Path,default=Path('E:/MusicAgent&DAW/analysis/cache/public-fixtures/vibeace-excerpt.wav'));args=ap.parse_args()
    directory=ROOT/'build/agent-tempo-e2e'/uuid.uuid4().hex;directory.mkdir(parents=True)
    exe=directory/'E-musician.exe';shutil.copy2(args.exe,exe);source=directory/'public-excerpt.wav';shutil.copy2(args.source,source)
    original_hash=hashlib.sha256(args.source.read_bytes()).hexdigest()
    report={'passed':False,'mode':'real-offline-native-and-BeatThis-with-mocked-language-provider','physical_audio':False,'external_llm':False,
        'recognition_accuracy_claim':False,'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'source_sha256':original_hash,'checks':[]}
    before=protected_snapshot();client=None;checks=report['checks']
    def wait(runtime):
        runtime.worker.join(args.timeout)
        assert not runtime.busy(),'Agent operation timed out'
        if runtime.phase=='error':raise AssertionError(runtime.error)
    try:
        client=Client(exe,timeout=args.timeout,show=False,offline_test=True);assert not client.state()['tracks']
        client.request({'command':'import_audio','args':{'paths':[str(source)]}})
        bridge=DawBridge(client=client);initial=bridge.snapshot();cid=initial['tracks'][0]['clips'][0]['id'];baseline=bridge.audio_warp(initial,[cid])
        assert {'get_audio_warp','set_audio_warp','apply_beat_analysis'}<=set(bridge.capabilities()['commands'])
        assert any(p['kind']=='beats' and p['available'] for p in bridge.analysis_capabilities()['providers'])
        checks.append('Actual native commands and pinned local Beat This provider advertise readiness')
        with patch('music_agent.runtime.has_key',return_value=False),patch('music_agent.providers.has_key',return_value=False),patch('music_agent.runtime.load_config',return_value=deepcopy(DEFAULT_CONFIG)):
            runtime=AgentRuntime(bridge,provider=StartBeats(cid,'audio_to_project'),audit=Audit())
            runtime.plan_request('Analyze actual source beats, then propose audio-to-project alignment. Review before applying.',scope='project');wait(runtime)
            assert runtime.phase=='ready' and runtime.provider.calls==2
            assert bridge.snapshot()['revision']==initial['revision'] and bridge.audio_warp(bridge.snapshot(),[cid])==baseline
            plan=deepcopy(runtime.plan);assert plan['analysis']['kind']=='beats' and plan['analysis']['total']>3
            assert 'waveform_peaks' not in plan['analysis'] and not plan['analysis']['applied']
            report['beat_model']=plan['analysis']['model'];report['detected_tempo']=plan['analysis']['tempo'];report['audio_to_project_args']=plan['commands'][0]['args']
            checks.append('Real beat inference becomes an Agent review in two mocked language calls without changing the project')
            runtime.apply(plan['id']);wait(runtime);assert runtime.phase=='done' and runtime.undo_target
            aligned=bridge.snapshot();aligned_warp=bridge.audio_warp(aligned,[cid])
            assert not verify_tempo_plan(plan,aligned,aligned_warp) and len(aligned['tracks'])==1
            assert aligned['bpm']==initial['bpm'] and aligned['numerator']==initial['numerator']
            assert bridge.analysis_result(plan['analysis']['result_id'])['applied']
            checks.append('Confirmed audio-to-project Warp commits once, preserves project tempo/meter and passes actual state readback without a fake track')
            runtime.undo();wait(runtime);assert bridge.audio_warp(bridge.snapshot(),[cid])==baseline
            client.request({'command':'redo'});assert bridge.audio_warp(bridge.snapshot(),[cid])==aligned_warp
            checks.append('One Agent Undo and one native Redo restore the exact pre/post Warp mappings')
            project=directory/'warped.emproj';client.request({'command':'save_project','args':{'path':str(project)}});client.request({'command':'open_project','args':{'path':str(project)}})
            assert bridge.audio_warp(bridge.snapshot(),[cid])==aligned_warp
            checks.append('Warp source identity, timing and enabled/follow settings survive a real save/reopen')
            runtime.provider=Provider('propose_audio_warp',{'clip_ids':[cid],'enabled':False,'summary':'Disable Warp and restore source speed'})
            runtime.plan_request('Disable Warp for this audio clip.',scope='project');wait(runtime);assert runtime.phase=='ready'
            runtime.apply(runtime.plan['id']);wait(runtime);assert runtime.phase=='done'
            disabled=bridge.audio_warp(bridge.snapshot(),[cid])[0];assert not disabled['enabled'] and disabled['warp_speed_ratio']==1
            assert abs(disabled['duration_seconds']-baseline[0]['duration_seconds'])<.003
            runtime.undo();wait(runtime);assert bridge.audio_warp(bridge.snapshot(),[cid])==aligned_warp
            checks.append('Manual Agent Warp-off restores the original duration; one Undo restores the warped clip')
            runtime.provider=Provider('propose_plan',{'summary':'Change project tempo to 90 BPM','actions':[{'type':'set_tempo','bpm':90}]})
            runtime.plan_request('Set the entire project to 90 BPM, including audio that follows tempo.',scope='project');wait(runtime);assert runtime.phase=='ready'
            runtime.apply(runtime.plan['id']);wait(runtime);assert runtime.phase=='done'
            slowed=bridge.audio_warp(bridge.snapshot(),[cid])[0]
            assert bridge.snapshot()['bpm']==90 and abs(slowed['duration_seconds']-aligned_warp[0]['duration_seconds']*120/90)<.003
            runtime.undo();wait(runtime);assert bridge.snapshot()['bpm']==120 and bridge.audio_warp(bridge.snapshot(),[cid])==aligned_warp
            checks.append('Existing set_tempo DSL waits for asynchronous follow-audio processing, checks final geometry and supports one Undo')
            clip_before=next(c for t in bridge.snapshot()['tracks'] for c in t['clips'] if c['id']==cid)
            crop_start=clip_before['start_seconds']+.4;crop_end=clip_before['start_seconds']+clip_before['duration_seconds']-.3
            runtime.provider=Provider('propose_plan',{'summary':'Trim audible warped clip while preserving source mapping','actions':[{'type':'trim_clip','clip_id':cid,'start_seconds':crop_start,'end_seconds':crop_end}]})
            runtime.plan_request('Trim 0.4 seconds from the front and 0.3 seconds from the end of the warped clip.',scope='project');wait(runtime)
            assert runtime.phase=='ready';runtime.apply(runtime.plan['id']);wait(runtime);assert runtime.phase=='done'
            cropped=next(c for t in bridge.snapshot()['tracks'] for c in t['clips'] if c['id']==cid)
            assert abs(cropped['source_offset']-.4*aligned_warp[0]['warp_speed_ratio'])<.003
            assert abs(cropped['playback_source_offset']-.4)<.003
            checks.append('Agent trims a warped clip using original-source and playback offsets consistently; next analysis exercises nonzero cropped offsets')
            runtime.provider=StartBeats(cid,'project_to_audio')
            runtime.plan_request('Analyze the audible warped source, then adopt a manually corrected 90 BPM 3/4 meter with first beat at 0.25 seconds. Whole-project scope.',scope='project');wait(runtime)
            assert runtime.phase=='ready' and runtime.provider.calls==2
            global_plan=deepcopy(runtime.plan);assert global_plan['tempo_check']=={'bpm':90,'numerator':3,'denominator':4}
            assert abs(global_plan['analysis']['source']['clip_source_offset']-cropped['playback_source_offset'])<.003
            pre_global=bridge.audio_warp(bridge.snapshot(),[cid])[0]
            runtime.apply(runtime.plan['id']);wait(runtime);assert runtime.phase=='done'
            global_state=bridge.snapshot();global_warp=bridge.audio_warp(global_state,[cid])
            assert not verify_tempo_plan(global_plan,global_state,global_warp)
            assert len(global_state['tracks'])==1 and global_warp[0]['warp_speed_ratio']==pre_global['warp_speed_ratio'] and not global_warp[0]['follow_tempo']
            runtime.undo();wait(runtime);assert bridge.snapshot()['bpm']==120 and bridge.snapshot()['numerator']==4
            checks.append('A second real analysis of warped audio supports explicit manual tempo/meter correction; project adoption retains source playback speed and undoes atomically')
            assert len(runtime.state()['capability_groups'])==10
        report['passed']=True
    finally:
        if client:client.close()
        report['protected_file_changes']=protected_changes(before,protected_snapshot())
        report['protected_settings_unchanged']=report['protected_file_changes']['unchanged'];report['original_source_unchanged']=original_hash==hashlib.sha256(args.source.read_bytes()).hexdigest()
        report['passed']=report['passed'] and report['protected_settings_unchanged'] and report['original_source_unchanged']
        output=directory/'result.json';output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));print(output)
    assert report['passed']
if __name__=='__main__':main()
