"""Explicit live language-provider check using a synthetic read-only project.

No DAW editing or music-model inference. Existing private provider configuration
is read but not changed. Run with --live through the development Recorder.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from music_agent.audit import Audit
from music_agent.runtime import AgentRuntime
from music_agent.localization import public_response
from test_music_agent_runtime import FakeBridge

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    bridge = FakeBridge()
    runtime = AgentRuntime(bridge, audit=Audit(args.out / 'audit.jsonl'))
    report = {'checked_utc':datetime.now(timezone.utc).isoformat(), 'passed':False,
              'model':runtime.provider.model, 'real_language_provider':True,
              'project':'synthetic read-only fixture, 120 BPM and 4/4',
              'music_inference':False, 'daw_commands':0, 'cases':[]}
    try:
        for prompt in ('What are the current project tempo and time signature? Reply in one short sentence. Do not propose or apply edits.',
                       "\u8bf7\u544a\u8bc9\u6211\u5f53\u524d\u5de5\u7a0b\u7684\u901f\u5ea6\u548c\u62cd\u53f7\uff0c\u7528\u4e00\u53e5\u8bdd\u56de\u7b54\uff0c\u4e0d\u8981\u63d0\u51fa\u6216\u6267\u884c\u4efb\u4f55\u4fee\u6539\u3002"):
            runtime.plan_request(prompt, scope='project', language='en')
            runtime.worker.join(120)
            assert not runtime.worker.is_alive(), 'Language provider exceeded the test deadline'
            state = public_response(runtime.state(False), 'en')
            messages = [m['content'] for m in state['messages'] if m['role']=='assistant' and m.get('origin')!='runtime']
            answer = messages[-1] if messages else ''
            case = {'input_language':'Chinese' if any("\u4e00"<=c<="\u9fff" for c in prompt) else 'English',
                    'ui_language':'en','phase':state['phase'],'answer':answer,'error':state.get('error')}
            report['cases'].append(case)
            assert not state.get('error') and answer, case
            assert not any("\u4e00"<=c<="\u9fff" for c in answer), 'Model reply did not follow English interface language'
            assert '120' in answer and ('4/4' in answer or '4 / 4' in answer), 'Reply differs from supplied project facts'
            assert state.get('plan') is None and not bridge.calls, 'Read-only question proposed or applied an edit'
        report['usage'] = runtime.usage
        report['passed'] = True
    finally:
        (args.out / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
