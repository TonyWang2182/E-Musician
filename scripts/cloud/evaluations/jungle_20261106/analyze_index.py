"""Build a cloud-only listening index from completed objective reports."""
import html
import json
import os
from pathlib import Path
from urllib.parse import quote
from analyze import ROOT, REPORT_ROOT, digest, num, write_json


def main():
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Listening page stays on cloud')
    reports = [json.loads((REPORT_ROOT/name/'report.json').read_text()) for name in ('ace','yue2')]
    cards = []
    summary = {'listened':False,'style_accuracy_evaluated':False,'structure_evaluated':False,
               'method':'Objective metrics plus uncorrected BeatThis CPU estimates; single-output comparison only',
               'reports':[], 'html_builder_sha256':digest(Path(__file__))}
    for name, report in zip(('ace','yue2'), reports):
        source, metrics, beats = report['source'], report['overall'], report.get('beat_estimate', {})
        audio = Path(source['path']).resolve(strict=True)
        if not audio.is_relative_to(ROOT):
            raise ValueError('Audio link escaped cloud project')
        relative = quote(os.path.relpath(audio, REPORT_ROOT).replace(os.sep, '/'), safe='/.-_')
        unstable = beats.get('stability') != 'relatively_consistent_intervals'
        warning = '未得到稳健全曲BPM；不要把下面的统计量当作真实全曲速度。' if unstable else '拍间隔相对一致，仍需试听确认半拍/倍拍歧义。'
        local_estimates = ', '.join(f'{w["start_seconds"]:.0f}–{w["end_seconds"]:.0f}s: {num(w["raw_bpm"])}' for w in beats.get('windows_20_seconds', []))
        title = html.escape(report['label'])
        processing = ('既有ACE接口启用-1dB峰值归一化，随后保存PCM16。因此测到约-1dB峰值不代表模型天然留出了这份余量。'
                      if name == 'ace' else 'YuE2原管线将输出限制在[-1,1]，本次保存FLOAT。semantic达到3000 token预算而截断；ABC结束不等于音频自然完整结尾。')
        cards.append(f'''<section><h2>{title}</h2><audio controls preload="none" src="{relative}"></audio>
<p><a href="{relative}" target="_blank" rel="noopener">直接打开原始音频</a> · <a href="{name}/report.html">详细20秒概览</a> · <a href="{name}/report.json">完整测量与拍点JSON</a></p>
<dl><dt>真实格式</dt><dd>{source['duration_seconds']:.3f}秒 · {source['sample_rate']}Hz · {source['channels']}声道 · {html.escape(source['subtype'])}</dd>
<dt>峰值 / RMS</dt><dd>{num(metrics['sample_peak_dbfs'])} / {num(metrics['rms_dbfs'])} dBFS</dd>
<dt>静音时长 / 数字满幅样本</dt><dd>{num(100*metrics['silence_duration_fraction'],3)}% / {num(100*metrics['digital_rail_sample_fraction'],4)}%</dd>
<dt>非有限样本 / L-R相关</dt><dd>{metrics['nonfinite_samples']} / {num(metrics['lr_pearson_correlation'],3)}</dd></dl>
<p class="muted">{processing}</p>
<p><strong>{warning}</strong></p><p>未折叠的跨8拍统计：{num(beats.get('raw_bpm'))} BPM；单拍间隔中位数：{num(beats.get('median_single_interval_bpm'))} BPM。参考半/倍拍关系：85 / 170 / 340。</p>
<p class="muted">每20秒模型估计：{html.escape(local_estimates or '未取得')}。这些差异可能来自漏拍、额外拍点或半拍解释，不能直接证明音频真的变速。</p>
<details><summary>输入文件指纹</summary><code>{source['sha256']}</code></details></section>''')
        summary['reports'].append({'label':report['label'],'source':source,'overall':metrics,
            'generation_receipt_context':processing,
            'beat_estimate':{k:beats.get(k) for k in ('status','raw_bpm','median_single_interval_bpm','stability','interval_iqr_over_median','half_raw_double_bpm','windows_20_seconds')},
            'report_path':str(REPORT_ROOT/name/'report.json'),'report_sha256':digest(REPORT_ROOT/name/'report.json')})
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ACE / YuE2 · Jungle 对照试听</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#f6f7f9;color:#20242b}h1{font-size:30px}section{background:white;border:1px solid #dce1e7;padding:24px;margin:20px 0}audio{width:100%}dl{display:grid;grid-template-columns:minmax(170px,1fr) 2fr;gap:8px}dd{margin:0}code{overflow-wrap:anywhere}.muted{color:#596273}a{color:#145da0}</style>
<h1>ACE / YuE2：同一 Jungle 提示词</h1><p>人工听感状态：<strong>未试听</strong>。两份是各一次生成，不是择优结果，也不足以建立模型排名。</p>
<p>先把两份试听音量调到相近，再听整段，检查：170BPM/半拍感、Amen切分感、低频、MC碎片与完整歌唱、六段顺序。原始音频没有为本报告重写或响度归一化；不要因更响就判断更好。信号统计不能替代这些判断。</p>'''+''.join(cards)+'''
<section><h2>怎样读这些数字</h2><p>静音采用20ms窗、各声道RMS低于-60dBFS。RMS不是LUFS，样本峰值不是true peak。ACE和YuE2输出后处理不同；提示词要求粗粝和轻微失真，数字满幅比例不直接等同坏音质，也不能用于模型音质排名。整体相关系数不证明背景pad宽度。20秒块只表示时间，不代表Intro/Drop边界。</p>
<p>本页只引用现有云端音频，相对链接通过原有Jupyter会话访问，不复制音频、不内嵌base64、不开放新公网端口。若Jupyter HTML预览不显示播放器，点击“直接打开原始音频”，或在Jupyter文件浏览中右键HTML并使用新的浏览器标签页打开。</p></section></html>'''
    (REPORT_ROOT/'index.html').write_text(page, encoding='utf-8')
    write_json(REPORT_ROOT/'summary.json', summary)
    print(json.dumps({'html':str(REPORT_ROOT/'index.html'),'summary':str(REPORT_ROOT/'summary.json'),
                      'audio_copied':False,'listened':False}))


if __name__ == '__main__':
    main()
