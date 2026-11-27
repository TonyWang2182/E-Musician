"""One explicit live-language/music-model rehearsal in an owned offline DAW.

No GUI selection is invented: every case uses Whole project and a unique named
source. This spends API/GPU budget only when explicitly invoked. At most four
language calls and one music inference are allowed; there is no automatic retry.
--direct-pipeline explicitly skips the LLM and validates only structured model
requests and native editing. It never counts as exact-prompt/Agent verification.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from agent_client import Client
from music_agent import analysis, generation
from music_agent.audit import Audit
from music_agent.bridge import DawBridge
from music_agent.config import active_config
from music_agent.localization import public_response
from music_agent.providers import create_provider
from music_agent.runtime import AgentRuntime
from music_agent.tempo import verify_tempo_plan, compile_beats
from music_agent.selection import freeze_scope


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def stable(value):
    if isinstance(value, float): return round(value, 8)
    if isinstance(value, list): return [stable(v) for v in value]
    if isinstance(value, dict): return {k: stable(v) for k, v in value.items()}
    return value


def protected_small():
    paths = [Path(os.environ['LOCALAPPDATA'])/'E-musician/agent/settings.json']
    app = Path(os.environ['APPDATA'])/'E-musician'
    paths += [app/name for name in ('ui-language.txt', 'follow-playhead.txt', 'settings.xml', 'E-musician.settings')]
    # Do not enumerate projects, caches, session capabilities or encrypted keys.
    return {str(p): sha(p) if p.is_file() else None for p in paths}


class BoundedProvider:
    def __init__(self, provider):
        self.provider, self.calls = provider, []

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def complete(self, messages, tools):
        if len(self.calls) >= 4:
            raise ValueError('Rehearsal permits at most four language calls; no retry.')
        entry = {'started_at': utc(), 'status': 'started'}
        self.calls.append(entry)
        started = time.monotonic()
        try:
            result = self.provider.complete(messages, tools)
            usage = result.get('usage') or {}
            entry.update(status='returned', model=result.get('model', self.provider.model),
                         tool_names=[call.get('function', {}).get('name') for call in result['message'].get('tool_calls', [])],
                         usage={k: usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens') if k in usage})
            return result
        except Exception as exc:
            entry.update(status='failed', exception_type=type(exc).__name__)
            raise
        finally:
            entry['seconds'] = round(time.monotonic()-started, 3)


class BoundedBridge(DawBridge):
    def __init__(self, client, case):
        super().__init__(client=client)
        self.case, self.attempts, self.request_receipt, self.owned_job = case, 0, None, None
        self.source_clip_id, self.source_duration = None, None

    def budget(self, request, kind):
        if self.attempts:
            raise ValueError('Rehearsal permits only one external music task.')
        if (request.get('model_id'), request.get('execution')) != (self.case['model_id'], self.case['execution']):
            raise ValueError('The model did not choose the explicitly requested music route.')
        if kind != self.case['kind']:
            raise ValueError('The model chose the wrong music task.')
        duration = request.get('duration_seconds')
        if type(duration) not in (int, float) or not math.isfinite(duration):
            raise ValueError('An explicit bounded duration is required after authorization.')
        if kind == 'generate':
            if abs(duration-self.case['duration_seconds']) > .001 or not 10 <= duration <= 120:
                raise ValueError('Generation differs from the requested duration budget.')
            if not request.get('lyrics', '').strip():
                raise ValueError('This vocal rehearsal requires non-empty explicit lyrics.')
            for line in ('Stay until the morning light', 'Hold this feeling through the night'):
                if line.lower() not in request['lyrics'].lower():
                    raise ValueError('The generation lyrics field omitted a required chorus line.')
        else:
            if request.get('clip_id') != self.source_clip_id:
                raise ValueError('Analysis targeted a different clip.')
            if abs(request.get('start_seconds', 0)) > .001 or abs(duration-self.source_duration) > .003:
                raise ValueError('Analysis must use the complete bounded source excerpt.')
            if duration > self.case['duration_seconds']+.003:
                raise ValueError('Analysis exceeded the prepared excerpt budget.')
        self.attempts += 1
        self.request_receipt = deepcopy(request)

    def start_generation(self, context, scope, args):
        request = generation.authorize_start(context, scope, args)
        self.budget(request, 'generate')
        result = super().start_generation(context, scope, request)
        self.owned_job = result['job_id']
        return result

    def start_analysis(self, context, scope, args):
        request = analysis.authorize_start(context, scope, args)
        self.budget(request, request['kind'])
        result = super().start_analysis(context, scope, request)
        self.owned_job = result['job_id']
        return result


def pages(client, command, args=None, key='items', limit=100):
    items = []
    while True:
        page = client.request({'command': command, 'args': {**(args or {}), 'offset': len(items), 'limit': limit}})['result']
        total = page['total']
        assert type(total) is int and 0 <= total <= 100000
        batch = page[key]
        assert isinstance(batch, list) and (batch or len(items) == total)
        items.extend(batch)
        assert len(items) <= total
        if len(items) == total: return items


def music_state(client, bridge):
    snapshot = bridge.snapshot()
    tracks, audio = [], []
    for track in snapshot['tracks']:
        clips = []
        for clip in track['clips']:
            item = {k: clip.get(k) for k in ('id', 'kind', 'start_seconds', 'duration_seconds', 'source_offset', 'note_count', 'controller_count')}
            if clip['kind'] == 'midi':
                item['notes'] = pages(client, 'get_clip_notes', {'clip_id': clip['id']}, 'notes', 1000)
                item['controllers'] = pages(client, 'get_clip_controllers', {'clip_id': clip['id']}, 'events', 1000)
            elif clip['kind'] == 'audio': audio.append(clip['id'])
            clips.append(item)
        tracks.append({'id': track['id'], 'name': track['name'], 'clips': clips})
    return stable({'bpm': snapshot['bpm'], 'numerator': snapshot['numerator'], 'denominator': snapshot['denominator'],
                   'tracks': tracks, 'chords': pages(client, 'get_chord_regions'),
                   'warp': bridge.audio_warp(snapshot, audio) if audio else []})


def wait_runtime(runtime, timeout, report, checkpoint):
    deadline, last = time.monotonic()+timeout, None
    while runtime.busy() and time.monotonic() < deadline:
        runtime.worker.join(.25)
        value = runtime.state(False)
        marker = (value['phase'], value['progress'].get('stage'), value['progress'].get('label'))
        if marker != last:
            report.setdefault('progress', []).append({'at': utc(), 'phase': marker[0], 'stage': marker[1]})
            checkpoint()
            print(json.dumps({'phase': marker[0], 'stage': marker[1]}), flush=True)
            last = marker
    if runtime.busy(): raise AssertionError('Rehearsal deadline exceeded; cancellation receipt required.')
    if runtime.phase == 'error': raise AssertionError(analysis.safe_text(runtime.error, 1000))


def direct_plan(bridge, before, case, timeout, report, checkpoint):
    """Production authorization and proposal compilation, without any Provider."""
    frozen = freeze_scope(before, 'project')
    if case['kind'] == 'generate':
        request = deepcopy(case.get('generation_request'))
        if not isinstance(request, dict):
            raise ValueError('Direct generation requires an explicit generation_request in the case; no prompt interpretation is simulated.')
        bridge.start_generation(before, frozen, request)
    else:
        bridge.start_analysis(before, frozen, {
            'clip_id': bridge.source_clip_id, 'kind': case['kind'],
            'model_id': case['model_id'], 'execution': case['execution'],
            'start_seconds': 0, 'duration_seconds': bridge.source_duration,
            'parameters': {'meter': 'auto'} if case['kind'] == 'beats' else {},
        })
    report['request'] = bridge.request_receipt
    checkpoint()
    read_job = bridge.generation_job if case['kind'] == 'generate' else bridge.analysis_job
    deadline, last = time.monotonic()+timeout, None
    while True:
        job = read_job(bridge.owned_job)
        report['direct_music_job'] = job
        marker = (job.get('status'), job.get('phase'))
        if marker != last:
            report.setdefault('progress', []).append({'at': utc(), 'phase': marker[0], 'stage': marker[1]})
            checkpoint()
            print(json.dumps({'pipeline_phase': marker[0], 'stage': marker[1]}), flush=True)
            last = marker
        if job.get('status') == 'ready': break
        if job.get('status') in {'applied', 'failed', 'cancelled', 'conflict', 'stale', 'interrupted'}:
            raise AssertionError('Music candidate did not become ready: '+analysis.safe_text(job.get('error') or job.get('status'), 700))
        if time.monotonic() >= deadline:
            raise AssertionError('Direct pipeline music deadline exceeded; see cancellation receipt.')
        time.sleep(.25)
    result_id = job['result_id']
    summary = 'Direct pipeline validation: review the real candidate before explicit test acceptance.'
    if case['kind'] == 'generate':
        candidate = bridge.generation_result(result_id)
        plan = generation.compile_import(candidate, before, frozen, summary)
    else:
        candidate = bridge.analysis_result(result_id)
        if case['kind'] == 'beats':
            # Do not invent a first downbeat if the actual model returns none.
            plan = compile_beats({'result_id': result_id, 'mode': 'audio_to_project', 'summary': summary},
                                 candidate, before, frozen, bridge.audio_warp(before, [bridge.source_clip_id]))
        else:
            plan = analysis.compile_import(candidate, before, frozen, summary)
    plan['id'] = str(uuid.uuid4())
    report['public_review'] = {'phase': 'ready', 'messages': [], 'error': None,
                             'pipeline_only': True, 'summary': summary,
                             'model_id': case['model_id'], 'candidate_id': result_id}
    return plan


def direct_apply(bridge, plan, timeout, report):
    """Explicitly accept once, then wait for the native commit receipt."""
    reply = bridge.apply(plan)
    job_id = reply['result']['job_id']
    if plan['execution_kind'] == 'generation_import':
        receipt = bridge.wait_generation_import(job_id, timeout=timeout)
    elif plan['execution_kind'] == 'analysis_import':
        receipt = bridge.wait_analysis_import(job_id, timeout=timeout)
    else:
        receipt = bridge.wait_edit_job(job_id, timeout=timeout)
    report['apply_receipt'] = receipt
    assert receipt['revision'] == plan['revision']+1
    key = 'generation' if plan['execution_kind'] == 'generation_import' else 'analysis'
    approved = plan[key]
    current = bridge.generation_result(approved['result_id']) if key == 'generation' else bridge.analysis_result(approved['result_id'])
    assert current['result_hash'] == approved['result_hash'] and current['applied']
    if key == 'generation': assert current['audio'] == approved['audio']
    else: assert current['summary'] == approved['summary'] and current['total'] == approved['total']


def load_case(path, identifier):
    contents = json.loads(path.read_text(encoding='utf-8-sig'))
    cases = contents.get('cases', contents) if isinstance(contents, dict) else contents
    if isinstance(cases, dict): cases = list(cases.values())
    matches = [deepcopy(c) for c in cases if c.get('id') == identifier]
    assert len(matches) == 1, 'Case must exist exactly once.'
    case = matches[0]
    case['kind'] = {'generation': 'generate', 'tempo': 'beats'}.get(case['kind'], case['kind'])
    assert case['kind'] in {'generate', 'separate', 'chords', 'transcribe', 'beats'}
    assert isinstance(case['prompt'], str) and case['prompt'].strip()
    assert case['execution'] in {'local', 'cloud'}
    assert 0 < case['duration_seconds'] <= 120
    assert 30 <= case['bpm'] <= 300
    return case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--case', required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--direct-pipeline', action='store_true',
                        help='No LLM: validate structured music request/native pipeline only, not the English prompt.')
    args = parser.parse_args()
    case = load_case(args.cases, args.case)
    outroot = args.output_root.resolve()
    if os.name == 'nt' and outroot.drive.upper() != 'E:':
        raise ValueError('Rehearsal files must stay on E:.')
    directory = outroot/(case['id']+'-'+uuid.uuid4().hex[:12])
    directory.mkdir(parents=True, exist_ok=False)
    executable = directory/'E-musician.exe'
    shutil.copy2(args.exe.resolve(strict=True), executable)
    temporary, cache = directory/'temporary', directory/'audio-cache'
    temporary.mkdir(); cache.mkdir()
    inputs = {str(Path(case[name]).resolve(strict=True)): sha(case[name])
              for name in ('source_path', 'input_project') if case.get(name)}
    preferences = protected_small()
    report = {'passed': False, 'case_id': case['id'], 'started_at': utc(), 'prompt': case['prompt'],
              'scope': 'project', 'gui_selection_tested': False, 'real_llm': not args.direct_pipeline, 'real_music_model': True,
              'validation_mode': 'direct-pipeline' if args.direct_pipeline else 'exact-prompt-live',
              'exact_prompt_verified': False, 'agent_task_interpretation_verified': False,
              'physical_audio': False, 'listening_quality_verified': False, 'exe_sha256': sha(executable),
              'model_id': case['model_id'], 'execution': case['execution'], 'kind': case['kind'],
              'inputs': inputs, 'checks': [], 'one_inference_limit': 1, 'language_call_limit': 0 if args.direct_pipeline else 4}
    client = bridge = runtime = provider = None
    def checkpoint(): write_json(directory/'report.json', report)
    checkpoint()
    environment = {'TEMP': str(temporary), 'TMP': str(temporary), 'EMUSICIAN_AUDIO_CACHE_ROOT': str(cache)}
    try:
        with patch.dict(os.environ, environment), patch('music_agent.runtime.MAX_MODEL_ROUNDS', 4):
            client = Client(executable, timeout=120, show=False, offline_test=True)
            assert not client.state()['tracks']
            if case.get('input_project'):
                client.request({'command': 'open_project', 'args': {'path': str(Path(case['input_project']).resolve())}})
            else:
                client.request({'command': 'set_tempo', 'args': {'bpm': case['bpm']}})
                if case.get('source_path'):
                    client.request({'command': 'import_audio', 'args': {'paths': [str(Path(case['source_path']).resolve())]}})
                    track = client.state()['tracks'][0]
                    client.request({'command': 'rename_track', 'args': {'track_id': track['id'], 'name': case['source_track_name']}})
            bridge = BoundedBridge(client, case)
            before = bridge.snapshot()
            assert before['bpm'] == case['bpm'] and (before['numerator'], before['denominator']) == (4, 4)
            source_clip = None
            if case['kind'] != 'generate':
                sources = [c for t in before['tracks'] if t['name'] == case['source_track_name'] for c in t['clips'] if c['kind'] == 'audio']
                assert len(sources) == 1, 'A unique named audio source is required.'
                source_clip = sources[0]
                bridge.source_clip_id = source_clip['id']
                bridge.source_duration = source_clip['duration_seconds']
                assert bridge.source_duration <= case['duration_seconds']+.003
            baseline = music_state(client, bridge)
            if args.direct_pipeline:
                report['language_model'] = None
                plan = direct_plan(bridge, before, case, args.timeout, report, checkpoint)
            else:
                settings = active_config()
                kwargs = {'reasoning_effort': settings['reasoning_effort']} if settings['provider'] == 'openai' else {}
                provider = BoundedProvider(create_provider(settings['provider'], settings['model'], settings['base_url'], **kwargs))
                runtime = AgentRuntime(bridge, provider=provider, audit=Audit(directory/'audit.jsonl'))
                report['language_model'] = {'provider': settings['provider'], 'model': settings['model'], **kwargs}
                runtime.plan_request(case['prompt'], scope='project', language='en')
                wait_runtime(runtime, args.timeout, report, checkpoint)
                public = public_response(runtime.state(False), 'en')
                report['public_review'] = {k: public[k] for k in ('phase', 'messages', 'plan', 'error', 'error_code')}
                assert runtime.phase == 'ready' and runtime.plan, 'No reviewable plan was produced.'
                assert 1 <= len(provider.calls) <= 4
                plan = deepcopy(runtime.plan)
            assert bridge.attempts == 1
            assert bridge.snapshot()['revision'] == before['revision'] and music_state(client, bridge) == baseline
            candidate = plan['generation'] if case['kind'] == 'generate' else plan['analysis']
            report['request'] = bridge.request_receipt
            report['candidate'] = candidate
            report['plan_commands'] = plan['commands']
            assert (candidate['model_id'], candidate['execution']) == (case['model_id'], case['execution'])
            assert len(candidate['result_hash']) == 64 and not candidate['applied']
            assert len(plan['commands']) == 1
            expected_command = 'accept_generation_result' if case['kind'] == 'generate' else 'apply_beat_analysis' if case['kind'] == 'beats' else 'accept_analysis_result'
            assert plan['commands'][0]['command'] == expected_command
            if case['kind'] == 'generate': assert candidate['audio']['duration_seconds'] > 0
            else:
                assert candidate['source']['clip_id'] == source_clip['id'] and candidate['total'] > 0
                if case['kind'] == 'separate':
                    assert candidate['total'] == 4 and {item['name'] for item in candidate['items']} == {'vocals', 'drums', 'bass', 'other'}
                if case['kind'] == 'beats': assert plan['commands'][0]['args']['mode'] == 'audio_to_project'
            report['exact_prompt_verified'] = not args.direct_pipeline
            report['agent_task_interpretation_verified'] = not args.direct_pipeline
            report['checks'].append('Structured direct request produced the requested real candidate and review without project mutation; no LLM used' if args.direct_pipeline
                                    else 'Exact prompt produced requested model candidate and review without project mutation')
            checkpoint()
            if args.direct_pipeline:
                direct_apply(bridge, plan, args.timeout, report)
            else:
                runtime.apply(plan['id'])
                wait_runtime(runtime, args.timeout, report, checkpoint)
                assert runtime.phase == 'done' and runtime.undo_target
            after_snapshot, after = bridge.snapshot(), music_state(client, bridge)
            assert after_snapshot['revision'] == before['revision']+1
            assert after['bpm'] == baseline['bpm'] and (after['numerator'], after['denominator']) == (baseline['numerator'], baseline['denominator'])
            if case['kind'] == 'beats':
                assert len(after['tracks']) == len(baseline['tracks'])
                assert not verify_tempo_plan(plan, after_snapshot, bridge.audio_warp(after_snapshot, [source_clip['id']]))
                old_warp = next(w for w in baseline['warp'] if w['clip_id'] == source_clip['id'])
                new_warp = next(w for w in after['warp'] if w['clip_id'] == source_clip['id'])
                assert new_warp['enabled']
                old_chords = {c['id']: c for c in baseline['chords']}
                new_chords = {c['id']: c for c in after['chords']}
                assert old_chords.keys() == new_chords.keys()
                factor = old_warp['warp_speed_ratio']/new_warp['warp_speed_ratio']
                for cid, chord in old_chords.items():
                    updated = new_chords[cid]
                    assert chord['label'] == updated['label']
                    for key in ('start_seconds', 'end_seconds'):
                        expected = new_warp['timeline_start_seconds'] + (chord[key]-old_warp['timeline_start_seconds'])*factor
                        assert abs(updated[key]-expected) < .005, 'Chord mapping did not follow source Warp.'
                report['chord_mapping_regions_checked'] = len(old_chords)
                report['warp_after'] = new_warp
            else:
                added = [t for t in after['tracks'] if t['id'] not in {t['id'] for t in baseline['tracks']}]
                expected_tracks = 1 if case['kind'] == 'generate' else analysis.import_track_count(candidate)
                assert len(added) == expected_tracks
                if case['kind'] == 'chords': assert len(after['chords'])-len(baseline['chords']) == candidate['total']
                if case['kind'] == 'transcribe':
                    note_count = sum(len(c.get('notes', [])) for t in added for c in t['clips'])
                    assert note_count > 0 and note_count == candidate['summary']['note_count']
                    report['accepted_note_count'] = note_count
                    if args.direct_pipeline:
                        controls = [e for t in added for c in t['clips'] for e in c.get('controllers', [])]
                        assert sum(0 <= e['type'] <= 127 for e in controls) == candidate['summary']['controller_count']
                        assert sum(e['type'] == 4097 for e in controls) == candidate['summary']['program_change_count']
                        assert len(controls) == candidate['summary']['controller_count']+candidate['summary']['program_change_count']
                        report['accepted_controller_count'] = len(controls)
                if case['kind'] in {'generate', 'separate'}:
                    assert all(c['kind'] == 'audio' and c['duration_seconds'] > 0 for t in added for c in t['clips'])
            report['checks'].append('Explicit Apply completed with expected tracks/notes/chords or Warp and unchanged project tempo')
            if args.direct_pipeline:
                client.request({'command': 'undo'})
            else:
                runtime.undo(); wait_runtime(runtime, 120, report, checkpoint)
                assert runtime.phase == 'done'
            assert music_state(client, bridge) == baseline
            client.request({'command': 'redo'})
            assert music_state(client, bridge) == after
            report['checks'].append('One native Undo and Redo restored exact before/after musical state' if args.direct_pipeline
                                    else 'One Agent Undo and native Redo restored exact before/after musical state')
            filename = case.get('output_project_name', case['id']+'.emproj')
            assert Path(filename).name == filename
            if not filename.endswith('.emproj'): filename += '.emproj'
            project = directory/filename
            client.request({'command': 'save_project', 'args': {'path': str(project)}})
            client.request({'command': 'open_project', 'args': {'path': str(project)}})
            assert music_state(client, bridge) == after
            manifest = json.loads(project.read_text(encoding='utf-8'))
            audio_paths = []
            for asset in manifest.get('assets', []):
                path = (project.parent/asset['source']).resolve(strict=True)
                assert path.is_relative_to(directory.resolve())
                audio_paths.append({'asset_id': asset['id'], 'path': str(path), 'sha256': sha(path)})
            report.update(project=str(project), project_sha256=sha(project), accepted_audio_paths=audio_paths,
                          accepted_musical_state=after)
            report['checks'].append('Saved project reopened with identical musical state and verified local audio assets')
            report['passed'] = True
    except Exception as exc:
        report.update(error=analysis.safe_text(str(exc), 1500), exception_type=type(exc).__name__)
        raise
    finally:
        if runtime:
            report['usage'] = dict(runtime.usage)
            if runtime.busy():
                runtime.cancel(); runtime.worker.join(15)
            report['worker_still_running_at_cleanup'] = runtime.busy()
            report['final_phase'] = runtime.phase
            try:
                final_public = public_response(runtime.state(False), 'en')
                report['public_final'] = {k: final_public[k] for k in ('phase', 'messages', 'error', 'error_code')}
            except Exception as exc:
                report['public_final_read_error'] = type(exc).__name__
        if provider: report['language_calls'] = provider.calls
        elif args.direct_pipeline:
            report.update(language_calls=[], usage={'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0},
                          final_phase='done' if report['passed'] else 'error')
        if bridge:
            report['music_attempts'] = bridge.attempts
            report['owned_job_id'] = bridge.owned_job
            report.setdefault('request', bridge.request_receipt)
            if bridge.owned_job:
                try:
                    report['final_music_job'] = bridge.generation_job(bridge.owned_job) if case['kind'] == 'generate' else bridge.analysis_job(bridge.owned_job)
                    if args.direct_pipeline and report['final_music_job'].get('status') not in {'ready', 'applied', 'completed', 'failed', 'cancelled', 'conflict', 'stale', 'interrupted'}:
                        cancel = bridge.cancel_generation if case['kind'] == 'generate' else bridge.cancel_analysis
                        cancel(bridge.owned_job)
                        report['music_cancel_requested'] = True
                        report['final_music_job'] = bridge.generation_job(bridge.owned_job) if case['kind'] == 'generate' else bridge.analysis_job(bridge.owned_job)
                except Exception as exc: report['job_cleanup_read_error'] = type(exc).__name__
        if client: client.close()
        report['input_files_unchanged'] = all(Path(p).is_file() and sha(p) == digest for p, digest in inputs.items())
        report['small_settings_unchanged'] = protected_small() == preferences
        report['passed'] = report['passed'] and report['input_files_unchanged'] and report['small_settings_unchanged']
        report['finished_at'] = utc()
        checkpoint()
        print(json.dumps({'passed': report['passed'], 'phase': report.get('final_phase'), 'error': report.get('error'),
                          'report': str(directory/'report.json'), 'project': report.get('project')}), flush=True)
    assert report['passed']


if __name__ == '__main__':
    main()
