"""Beat/Warp authorization and asynchronous Agent lifecycle, no inference."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from music_agent.tempo import safe_tempo,safe_warp,authorize_clips,compile_warp,compile_beats,verify_tempo_plan
from music_agent.analysis import safe_result,compile_import,authorize_result
from music_agent.selection import freeze_scope,ScopeError
from music_agent.bridge import DawBridge,NativeJobFailed,BridgeError
from music_agent.runtime import AgentRuntime
from music_agent.audit import Audit
from music_agent.config import DEFAULT_CONFIG
from music_agent.plans import compile_plan
from test_music_agent_analysis import context,result,AnalysisBridge
from test_music_agent_runtime import FakeProvider,tool

def warp():
    return {'clip_id':'c','enabled':False,'source_bpm':120.,'target_bpm':120.,'follow_tempo':False,'mode':'preserve_pitch','warp_speed_ratio':1.,
        'source_offset_seconds':0.,'playback_source_offset_seconds':0.,'timeline_start_seconds':8.,'duration_seconds':10.,'source_duration_seconds':10.,'playback_duration_seconds':10.}

def candidate():
    value=result('beats',20)
    value['parameters']={'meter':'auto'}
    value['items']=[{'time_seconds':i*.5,'is_downbeat':i%4==0} for i in range(20)]
    value['tempo']={'bpm':100.,'first_beat_seconds':.1,'first_downbeat_seconds':.5,'meter_numerator':4,'meter_denominator':4,'meter_supported':True,'variable_tempo':False,'tempo_candidates':[50.,100.,200.]}
    return value

class TempoPlanTests(unittest.TestCase):
    def setUp(self):self.ctx=context();self.scope=freeze_scope(self.ctx);self.states=[warp()]
    def test_beat_summary_strips_peaks_and_invalid_tempo_fails(self):
        c=safe_result({**candidate(),'waveform_peaks':[.5]*128})
        self.assertNotIn('waveform_peaks',c);self.assertEqual(c['items'][0]['is_downbeat'],True)
        for update in ({'bpm':float('nan')},{'meter_numerator':6},{'meter_supported':[]},{'tempo_candidates':{}},{'variable_tempo':1}):
            with self.subTest(update=update),self.assertRaises(ValueError):safe_tempo({**c['tempo'],**update})
        with self.assertRaises(ValueError):compile_import(c,self.ctx,self.scope,"\u666e\u901a\u5bfc\u5165")
    def test_manual_warp_preserves_pitch_and_projects_numeric_extent(self):
        plan=compile_warp({'clip_ids':['c'],'enabled':True,'source_bpm':100,'summary':"\u53d8\u901f"},self.ctx,self.scope,self.states)
        check=plan['warp_checks'][0]
        self.assertAlmostEqual(check['warp_speed_ratio'],1.2)
        self.assertAlmostEqual(check['duration_seconds'],10/1.2)
        self.assertEqual(check['timeline_start_seconds'],8)
        self.assertTrue(check['follow_tempo'])
        self.assertEqual(plan['commands'][0]['command'],'set_audio_warp')
        self.assertNotIn('project_bpm',plan['commands'][0]['args'])
    def test_disable_restores_duration_and_rejects_conflicting_parameters(self):
        self.ctx['tracks'][0]['clips'][0]['duration_seconds']=8
        self.states[0].update(enabled=True,warp_speed_ratio=1.25,duration_seconds=8)
        plan=compile_warp({'clip_ids':['c'],'enabled':False,'summary':"close"},self.ctx,self.scope,self.states)
        self.assertEqual(plan['warp_checks'][0]['duration_seconds'],10)
        self.assertFalse(plan['warp_checks'][0]['follow_tempo'])
        with self.assertRaises(ValueError):compile_warp({'clip_ids':['c'],'enabled':False,'source_bpm':100,'summary':"close"},self.ctx,self.scope,self.states)
    def test_beat_audio_to_project_first_downbeat_and_safe_next_bar(self):
        plan=compile_beats({'result_id':'r','mode':'audio_to_project','summary':"\u5bf9\u9f50"},candidate(),self.ctx,self.scope,self.states)
        args=plan['commands'][0]['args'];check=plan['warp_checks'][0]
        self.assertEqual(args['first_beat_seconds'],.5);self.assertEqual(args['target_start_seconds'],10)
        self.assertAlmostEqual(check['timeline_start_seconds'],10-.5*100/120)
        self.assertEqual(plan['tempo_check'],{'bpm':120})
        self.assertEqual(check['source_bpm'],100)
    def test_currently_warped_source_bpm_is_converted_once(self):
        self.states[0].update(enabled=True,warp_speed_ratio=2.,source_bpm=60.,target_bpm=120.)
        c=candidate();c['tempo']['bpm']=120
        plan=compile_beats({'result_id':'r','mode':'audio_to_project','summary':"\u5bf9\u9f50"},c,self.ctx,self.scope,self.states)
        self.assertEqual(plan['warp_checks'][0]['source_bpm'],60)
        self.assertEqual(plan['warp_checks'][0]['warp_speed_ratio'],2)
    def test_warped_trimmed_candidate_uses_playback_offset_and_bound_ratio(self):
        clip=self.ctx['tracks'][0]['clips'][0];clip.update(source_offset=4.,playback_source_offset=2.,warp_speed_ratio=2.)
        c=candidate();c['source'].update(clip_source_offset=2.,warp_speed_ratio=2.)
        c=safe_result(c);authorize_result(self.ctx,self.scope,c)
        self.assertEqual(c['source']['warp_speed_ratio'],2.)
        c['source']['warp_speed_ratio']=1.5
        with self.assertRaises(ScopeError):authorize_result(self.ctx,self.scope,c)
    def test_global_tempo_requires_project_scope_and_manual_meter(self):
        args={'result_id':'r','mode':'project_to_audio','bpm':200,'numerator':3,'summary':"\u91c7\u7528\u53cc\u500d\u901f\u5ea6"}
        with self.assertRaises(ScopeError):compile_beats(args,candidate(),self.ctx,self.scope,self.states)
        plan=compile_beats(args,candidate(),self.ctx,freeze_scope(self.ctx,'project'),self.states)
        self.assertEqual(plan['tempo_check'],{'bpm':200,'numerator':3,'denominator':4})
        self.assertEqual(plan['warp_checks'][0]['warp_speed_ratio'],1)
        self.assertFalse(plan['warp_checks'][0]['follow_tempo'])
    def test_unknown_meter_allowed_only_without_global_meter_change(self):
        c=candidate();c['tempo'].update(meter_numerator=0,meter_supported=False)
        plan=compile_beats({'result_id':'r','mode':'audio_to_project','summary':"\u5bf9\u9f50"},c,self.ctx,self.scope,self.states)
        self.assertNotIn('numerator',plan['commands'][0]['args'])
        with self.assertRaises(ValueError):compile_beats({'result_id':'r','mode':'project_to_audio','summary':"\u91c7\u7528"},c,self.ctx,freeze_scope(self.ctx,'project'),self.states)
    def test_first_beat_missing_negative_target_stale_and_type_errors(self):
        args={'result_id':'r','mode':'audio_to_project','summary':"\u5bf9\u9f50"};c=candidate();c['tempo']['first_downbeat_seconds']=None
        with self.assertRaises(ValueError):compile_beats(args,c,self.ctx,self.scope,self.states)
        compile_beats({**args,'first_beat_seconds':.1},c,self.ctx,self.scope,self.states)
        for extra in ({'target_start_seconds':0},{'first_beat_seconds':float('nan')},{'follow_tempo':[]},{'bpm':10}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):compile_beats({**args,**extra},candidate(),self.ctx,self.scope,self.states)
        with self.assertRaises(ValueError):compile_beats(args,{**candidate(),'stale':True},self.ctx,self.scope,self.states)
    def test_whole_clip_operation_does_not_escape_partial_selection(self):
        self.ctx['selection_context']['time_range']={'active':True,'start_seconds':9,'end_seconds':11}
        with self.assertRaises(ScopeError):authorize_clips(self.ctx,freeze_scope(self.ctx),['c'])
        authorize_clips(self.ctx,freeze_scope(self.ctx,'clip'),['c'])
        with self.assertRaises(ValueError):authorize_clips(self.ctx,freeze_scope(self.ctx,'project'),['c','c'])
    def test_state_paths_stripped_and_postcondition_mismatch_caught(self):
        value=safe_warp({'items':[{**warp(),'file':'C:/secret.wav'}]},['c'])
        self.assertNotIn('file',value[0])
        plan=compile_warp({'clip_ids':['c'],'enabled':True,'source_bpm':100,'summary':"\u53d8\u901f"},self.ctx,self.scope,value)
        self.assertTrue(verify_tempo_plan(plan,self.ctx,value))
        with self.assertRaises(ValueError):safe_warp({'items':[warp(),warp()]},['c'])
    def test_global_tempo_then_trim_uses_updated_source_time_mapping(self):
        clip=self.ctx['tracks'][0]['clips'][0]
        clip.update(asset_id='asset',source_offset=4.,fade_in_seconds=.1,fade_out_seconds=.2,
            warp_enabled=True,warp_follow_tempo=True,warp_source_bpm=60.,warp_target_bpm=120.,warp_speed_ratio=2.,playback_source_offset=2.)
        payload={'summary':"\u91c7\u7528\u901f\u5ea6\u5e76\u88c1\u526a",'actions':[{'type':'set_tempo','bpm':60},{'type':'trim_clip','clip_id':'c','start_seconds':17,'end_seconds':35}]}
        plan=compile_plan(payload,self.ctx)
        expected=next(c['value'] for c in plan['checks'] if c['kind']=='clip')
        self.assertEqual(expected['start_seconds'],17)
        self.assertEqual(expected['duration_seconds'],18)
        self.assertEqual(expected['source_offset'],5)
        self.assertEqual(expected['warp_speed_ratio'],1)
        self.assertEqual(expected['playback_source_offset'],5)
        self.assertAlmostEqual(expected['fade_in_seconds'],.2)

class TempoBridge(AnalysisBridge):
    def __init__(self):
        super().__init__();self.candidate=candidate();self.warps=[warp()];self.previous_warps=None;self.pending=None;self.fail=False
    def capabilities(self):return {'commands':['get_audio_warp','set_audio_warp','apply_beat_analysis']}
    def audio_warp(self,context,ids):return deepcopy(self.warps)
    def apply(self,plan):
        self.calls.append(('apply',deepcopy(plan)));self.pending=plan;self.last_before=deepcopy(self.data);self.last_notes=deepcopy(self.notes);self.previous_warps=deepcopy(self.warps)
        return {'status':'accepted','result':{'job_id':'warp-job'}}
    def wait_edit_job(self,jid):
        if self.fail:raise NativeJobFailed('Test renderer rejected before commit')
        self.warps[0].update(enabled=True,source_bpm=100.,target_bpm=120.,follow_tempo=True,warp_speed_ratio=1.2,duration_seconds=10/1.2,timeline_start_seconds=8.)
        self.data['tracks'][0]['clips'][0]['duration_seconds']=10/1.2
        if self.pending['execution_kind']=='beat_apply':
            self.warps[0]['timeline_start_seconds']=10-.5/1.2;self.data['tracks'][0]['clips'][0]['start_seconds']=10-.5/1.2;self.candidate['applied']=True
        self.data.update(revision=4,can_undo=True)
        return {'project_id':'p','revision':4,'clip_ids':['c'],'job_id':jid}
    def undo(self,*args):
        reply=super().undo(*args);self.warps=deepcopy(self.previous_warps);return reply

class TempoRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.runtimes=[]
        self.patches=[patch('music_agent.runtime.load_config',return_value=deepcopy(DEFAULT_CONFIG)),patch('music_agent.runtime.has_key',return_value=False),patch('music_agent.providers.has_key',return_value=False)]
        for p in self.patches:p.start()
    def tearDown(self):
        for runtime in self.runtimes:
            runtime.cancel_event.set()
            if runtime.worker:runtime.worker.join(3)
        for p in self.patches:p.stop()
        self.directory.cleanup()
    def make(self,name,args):
        r=AgentRuntime(TempoBridge(),provider=FakeProvider([tool(name,args)]),audit=Audit(Path(self.directory.name)/'audit.jsonl'));self.runtimes.append(r);return r
    def wait(self,r):r.worker.join(4);self.assertFalse(r.busy());return r.state(False)
    def test_manual_and_beat_proposals_confirm_readback_and_one_undo(self):
        for name,args in [('propose_audio_warp',{'clip_ids':['c'],'enabled':True,'source_bpm':100,'summary':'Warp'}),('propose_beat_application',{'result_id':'r','mode':'audio_to_project','summary':'Align'})]:
            with self.subTest(name=name):
                r=self.make(name,args);r.plan_request('Explicit fixture proposal','selection');state=self.wait(r)
                self.assertEqual(state['phase'],'ready',state);self.assertEqual(r.bridge.data['revision'],3);self.assertFalse(r.bridge.calls)
                r.apply(state['plan']['id']);state=self.wait(r);self.assertEqual(state['phase'],'done',state);self.assertTrue(state['can_undo'])
                self.assertEqual(len(r.bridge.data['tracks']),1)
                r.undo();self.wait(r);self.assertEqual(r.bridge.warps,[warp()]);self.assertEqual(r.bridge.data['tracks'][0]['clips'][0]['duration_seconds'],10)
    def test_failed_background_job_never_claims_undo_or_retries(self):
        r=self.make('propose_audio_warp',{'clip_ids':['c'],'enabled':True,'source_bpm':100,'summary':'Warp'});r.bridge.fail=True
        r.plan_request('Warp','selection');state=self.wait(r);r.apply(state['plan']['id']);state=self.wait(r)
        self.assertEqual(state['phase'],'error');self.assertFalse(state['can_undo']);self.assertEqual(len(r.bridge.calls),1);self.assertEqual(r.bridge.data['revision'],3)
    def test_selection_changed_after_preview_rejects_commit(self):
        r=self.make('propose_audio_warp',{'clip_ids':['c'],'enabled':True,'source_bpm':100,'summary':'Warp'})
        r.plan_request('Warp','selection');state=self.wait(r);r.bridge.data['selection_context']['selection_revision']+=1
        r.apply(state['plan']['id']);state=self.wait(r);self.assertEqual(state['phase'],'error');self.assertFalse(r.bridge.calls)

if __name__=='__main__':unittest.main()
