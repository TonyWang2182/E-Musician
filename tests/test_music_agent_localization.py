"""Synthetic language contracts; no paid model or music inference is performed."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from music_agent.localization import L, public_response, response_instruction
from music_agent.plans import compile_plan
from music_agent.selection import freeze_scope
from music_agent import generation, analysis
import test_music_agent_runtime as runtime_fixture
from test_music_agent_runtime import tool, TEMPO, context
from test_music_agent_generation import context as generation_context, candidate
from test_music_agent_analysis import context as analysis_context, result as analysis_result


def has_chinese(text):
    return any('\u4e00' <= char <= '\u9fff' for char in text)


class RuntimeLanguageTests(unittest.TestCase):
    setUp = runtime_fixture.RuntimeTests.setUp
    tearDown = runtime_fixture.RuntimeTests.tearDown
    make = runtime_fixture.RuntimeTests.make
    finish = runtime_fixture.RuntimeTests.finish

    def test_english_submit_proposal_apply_and_runtime_message(self):
        runtime = self.make(tool('propose_plan', {'summary': 'Set the project tempo to 100 BPM.', 'actions': [TEMPO]}))
        runtime.plan_request('Set the tempo to 100 BPM.', scope='project', language='en')
        state = public_response(self.finish(runtime), 'en')
        self.assertEqual(state['phase'], 'ready', state)
        self.assertEqual(state['progress']['label'], 'Plan ready; project unchanged')
        instruction = runtime.provider.requests[0][0]['content']
        self.assertIn('interface language for this request is English', instruction)
        self.assertNotIn('用简明中文回答', instruction)
        self.assertTrue(all(not has_chinese(row) for row in state['plan']['changes']))
        self.assertTrue(all(not has_chinese(row['label']) for row in state['plan']['steps']))
        runtime.apply(state['plan']['id'])
        applied = public_response(self.finish(runtime), 'en')
        self.assertEqual(applied['phase'], 'done')
        self.assertFalse(has_chinese(applied['last_result']))
        self.assertFalse(has_chinese(applied['messages'][-1]['content']))
        self.assertEqual(runtime.bridge.data['bpm'], 100)
        self.assertEqual(len(runtime.bridge.calls), 1)

    def test_language_change_does_not_rewrite_user_model_or_music_data(self):
        reply = {'message': {'role':'assistant', 'content':'你明确要求的中文解释'}, 'usage':{}}
        runtime = self.make(reply)
        runtime.bridge.data['name'] = '中文工程'
        runtime.plan_request('Reply in Chinese: 解释节拍', scope='project', language='en')
        state = self.finish(runtime)
        projected = public_response(state, 'en')
        self.assertEqual(projected['snapshot']['name'], '中文工程')
        self.assertEqual(projected['messages'][-1]['content'], '你明确要求的中文解释')
        self.assertEqual(projected['messages'][0]['content'], 'Reply in Chinese: 解释节拍')
        self.assertEqual(state, public_response(state, 'zh-CN'))
        self.assertIn('explicitly requests a different response language', runtime.provider.requests[0][0]['content'])

    def test_runtime_failure_is_english_while_original_remains_available(self):
        runtime = self.make()
        runtime.bridge.data['recording'] = True
        runtime.plan_request('Change tempo.', scope='project', language='en')
        raw = self.finish(runtime)
        visible = public_response(raw, 'en')
        self.assertEqual(visible['phase'], 'error')
        self.assertIn('Stop recording', visible['error'])
        self.assertEqual(visible['error'], visible['messages'][-1]['content'])
        self.assertTrue(has_chinese(raw['error']))
        self.assertFalse(runtime.bridge.calls)

    def test_runtime_history_does_not_send_display_metadata_to_provider(self):
        runtime = self.make({'message': {'role':'assistant','content':'Ready.'}, 'usage':{}})
        runtime._message('assistant', L('已完成', 'Done'), runtime=True)
        runtime.plan_request('Explain the project.', scope='project', language='en')
        self.finish(runtime)
        for message in runtime.provider.requests[0]:
            self.assertNotIn('origin', message)

    def test_chinese_mode_keeps_chinese_runtime_copy(self):
        runtime = self.make()
        runtime.bridge.data['recording'] = True
        runtime.plan_request('更改速度', scope='project', language='zh-CN')
        state = self.finish(runtime)
        self.assertEqual(public_response(state, 'zh-CN')['error'], state['error'])
        self.assertIn('Simplified Chinese', response_instruction('zh-CN'))


class AuthoredCopyTests(unittest.TestCase):
    def test_plan_name_is_preserved_even_when_it_matches_an_authored_phrase(self):
        ctx = context()
        ctx['tracks'][0]['name'] = '正在规划「钢琴」'
        plan = compile_plan({'summary':'Reduce this track by 3 dB.', 'actions':[
            {'type':'set_track_gain', 'track_id':'track-1', 'gain_db':-3}]}, ctx)
        snapshot = deepcopy(ctx)
        projected = public_response({'plan':plan, 'snapshot':ctx}, 'en')
        self.assertIn('正在规划「钢琴」', projected['plan']['changes'][0])
        self.assertIn('Track', projected['plan']['changes'][0])
        self.assertEqual(projected['snapshot'], snapshot)
        self.assertEqual(ctx, snapshot)
        self.assertEqual(projected['plan']['commands'], plan['commands'])

    def test_generation_and_analysis_import_descriptions_are_english(self):
        ctx = generation_context()
        generated = generation.compile_import(candidate(), ctx, freeze_scope(ctx, 'project'), 'Add the generated audio.')
        ctx2 = analysis_context()
        analyzed = analysis.compile_import(analysis_result(), ctx2, freeze_scope(ctx2, 'project'), 'Add the MIDI candidate.')
        for plan in (generated, analyzed):
            view = public_response({'plan':plan}, 'en')['plan']
            self.assertTrue(all(not has_chinese(text) for text in view['changes']))
            self.assertTrue(all(not has_chinese(step['label']) for step in view['steps']))
            self.assertEqual(view['commands'], plan['commands'])

    def test_progress_and_postcommit_error_preserve_state_semantics(self):
        data = {'progress':{'stage':'generating','label':L('音乐生成 · running；尚未加入工程','Music generation · running; not added to the project')},
                'error':L('修改已提交，但回读未完成。','Changes were submitted, but verification did not finish.'),
                'messages':[{'role':'assistant','origin':'runtime','content':'已撤销上次 Agent 批次。'}]}
        out = public_response(data, 'en')
        self.assertEqual(out['progress']['stage'], 'generating')
        self.assertIn('submitted', out['error'])
        self.assertIn('Undid', out['messages'][0]['content'])
        self.assertFalse(has_chinese(json.dumps(out, ensure_ascii=False)))
        self.assertTrue(has_chinese(str(data['error'])))

    def test_authored_translation_survives_deepcopy_without_translating_plain_text(self):
        raw = {'changes':[L('轨道「中文」', 'Track “中文”')], 'summary':'原始模型文字', 'lyrics':'原始歌词'}
        view = public_response({'plan':deepcopy(raw)}, 'en')['plan']
        self.assertEqual(view['changes'], ['Track “中文”'])
        self.assertEqual(view['summary'], raw['summary'])
        self.assertEqual(view['lyrics'], raw['lyrics'])


if __name__ == '__main__':
    unittest.main()
