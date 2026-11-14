"""Collect public rehearsal evidence; no model calls or user project writes."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path('E:/MusicAgent&DAW/demo-video/2026-11-14/rehearsal')
cases = json.loads((HERE/'cases.json').read_text(encoding='utf-8'))
ids = {c['id'] for c in cases}
rows = []
for path in sorted(ROOT.glob('*/report.json')):
    r = json.loads(path.read_text(encoding='utf-8'))
    if r.get('case_id') not in ids:
        continue
    row = {k: r[k] for k in (
        'case_id', 'passed', 'model_id', 'execution', 'kind', 'real_llm',
        'physical_audio', 'listening_quality_verified', 'started_at', 'finished_at',
        'checks', 'error', 'usage', 'music_attempts', 'project', 'project_sha256',
        'accepted_audio_paths', 'input_files_unchanged', 'small_settings_unchanged',
        'accepted_note_count', 'accepted_controller_count', 'chord_mapping_regions_checked',
        'warp_after', 'request', 'exe_sha256') if k in r}
    row['exact_prompt_verified'] = r.get('exact_prompt_verified', r.get('passed', False) and r.get('real_llm', False))
    row['validation_mode'] = r.get('validation_mode', 'exact-prompt-live')
    row['report_path'] = str(path)
    row['report_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    row['elapsed_wall_seconds'] = round((datetime.fromisoformat(r['finished_at'])-datetime.fromisoformat(r['started_at'])).total_seconds(), 3) if r.get('finished_at') else None
    candidate = r.get('candidate', {})
    row['candidate'] = {k: candidate[k] for k in ('result_id', 'result_hash', 'model_id', 'execution', 'model', 'audio', 'summary', 'total', 'tempo', 'completion', 'limitations') if k in candidate}
    row['final_job_status'] = r.get('final_music_job', {}).get('status')
    rows.append(row)
diagnostic = json.loads((ROOT/'api-admission-diagnostic-01.json').read_text(encoding='utf-8'))
result = {'cases': rows, 'api_diagnostic': diagnostic,
          'physical_device_or_listening_verified': False,
          'note': 'A direct-pipeline pass does not verify the English prompt or GUI clicks. Failed attempts are retained.'}
(HERE/'RECEIPTS.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
by_id = {r['case_id']: r for r in rows if r['passed']}
index = ['# 演示素材与工程入口', '',
         '使用0.13.3打开。以下是本轮真实结果，保留每个.emproj旁的完整.assets文件夹；补拍时注明Previously generated/analyzed result。先Save as拍摄副本，避免覆盖唯一验证工程。', '',
         'ACE原样GPT指令已通过；其他五项是模型与DAW结构化管线验证，不能冒充Agent自然语言实测。当前OpenAI API返回insufficient_quota，恢复后才补验相应Agent指令。', '',
         '| 案例 | 已保存工程 |', '|---|---|']
for case in cases:
    r = by_id.get(case['id'])
    index.append(f"| {case['id']} | [打开工程](<{Path(r['project']).as_posix()}>) |" if r else f"| {case['id']} | 尚无通过的工程 |")
operations = HERE.parents[2]/'docs/demo/2026-11-14-demo-operations.md'
index += ['', f'[操作稿与英文提示词](<{operations.as_posix()}>)', '',
          f'[逐项验证结果](<{(HERE/"RESULTS.md").as_posix()}>)', '',
          '生成/分离：先分开试听两个版本；分离工程原始混音仍保留，试听分轨前先Mute来源，避免重叠出声。', '',
          '钢琴转录：MIDI音符已保存，但试听前需挂一个已验证钢琴音源；源钢琴与MIDI分开试听。D4人声/MIDI录音仍需实际录制。', '',
          '音质、歌词遵从、和弦准确性、转录漏音及声卡播放尚未人工验收。YuE2本次短段有token_budget截断；不要解说成完整歌曲。', '']
(ROOT.parent/'OPEN-FIRST.md').write_text('\n'.join(index), encoding='utf-8')
for row in rows:
    print(json.dumps({k: row[k] for k in ('case_id', 'validation_mode', 'passed', 'exact_prompt_verified', 'elapsed_wall_seconds')}, ensure_ascii=False))
