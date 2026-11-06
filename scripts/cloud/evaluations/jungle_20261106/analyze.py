"""CPU-only, cloud-local objective audio measurements, without listening claims."""
from __future__ import annotations
import argparse
import hashlib
import html
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from urllib.parse import quote
import numpy as np
import soundfile as sf

ROOT = Path('/root/autodl-tmp/emusician')
REPORT_ROOT = ROOT/'results/evaluations/jungle_20261106/analysis'
PROMPT_SHA = 'd52750d660e226231a13f846b1ac8ceecbcfb11dc446c13456b0d853333e9678'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.partial')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    temp.replace(path)


def db(value):
    return 20*math.log10(value) if value is not None and value > 0 else None


class Accumulator:
    def __init__(self, channels, sample_rate, rail):
        self.channels, self.rate, self.rail = channels, sample_rate, rail
        self.frames = self.nonfinite = self.zeros = self.near = self.full = self.over = 0
        self.count = np.zeros(channels, dtype=np.int64)
        self.sums = np.zeros(channels, dtype=np.float64)
        self.squares = np.zeros(channels, dtype=np.float64)
        self.peak = np.zeros(channels, dtype=np.float64)
        self.quiet_frames = self.invalid_window_frames = 0
        self.pair_n = 0
        self.pair_sums = np.zeros(2)
        self.pair_squares = np.zeros(2)
        self.cross = 0.0

    def add(self, block):
        values = np.asarray(block, dtype=np.float64)
        self.frames += len(values)
        finite = np.isfinite(values)
        self.nonfinite += int(np.count_nonzero(~finite))
        self.zeros += int(np.count_nonzero((values == 0) & finite))
        absolute = np.abs(np.where(finite, values, 0))
        self.near += int(np.count_nonzero((absolute >= .999) & finite))
        self.full += int(np.count_nonzero((absolute >= self.rail) & finite))
        self.over += int(np.count_nonzero((absolute > 1) & finite))
        clean = np.where(finite, values, 0)
        self.count += finite.sum(axis=0)
        self.sums += clean.sum(axis=0)
        self.squares += np.square(clean).sum(axis=0)
        if len(values):
            self.peak = np.maximum(self.peak, absolute.max(axis=0))
        if self.channels >= 2:
            pair = values[np.all(finite[:, :2], axis=1), :2]
            self.pair_n += len(pair)
            self.pair_sums += pair.sum(axis=0)
            self.pair_squares += np.square(pair).sum(axis=0)
            self.cross += float((pair[:, 0]*pair[:, 1]).sum())
        # 20ms windows; a short final window is weighted by its actual frames.
        width = max(1, round(self.rate*.02))
        for offset in range(0, len(values), width):
            part = values[offset:offset+width]
            if not np.isfinite(part).all():
                self.invalid_window_frames += len(part)
            elif float(np.sqrt(np.square(part).mean(axis=0)).max()) < .001:
                self.quiet_frames += len(part)

    def merge(self, other):
        for key in ('frames','nonfinite','zeros','near','full','over','quiet_frames','invalid_window_frames','pair_n','cross'):
            setattr(self, key, getattr(self, key)+getattr(other, key))
        for key in ('count','sums','squares','pair_sums','pair_squares'):
            setattr(self, key, getattr(self, key)+getattr(other, key))
        self.peak = np.maximum(self.peak, other.peak)

    def report(self):
        total = self.frames*self.channels
        valid = int(self.count.sum())
        rms = math.sqrt(float(self.squares.sum())/valid) if valid else None
        per_channel = [math.sqrt(float(s)/int(n)) if n else None for s,n in zip(self.squares,self.count)]
        correlation = None
        if self.pair_n >= 2:
            variances = self.pair_squares-np.square(self.pair_sums)/self.pair_n
            if np.all(variances > 1e-18):
                correlation = float(np.clip((self.cross-float(np.prod(self.pair_sums))/self.pair_n)/math.sqrt(float(np.prod(variances))), -1, 1))
        peak = float(self.peak.max()) if valid else None
        return {'frames': self.frames, 'sample_count_including_channels': total,
            'nonfinite_samples': self.nonfinite, 'all_samples_finite': self.nonfinite == 0,
            'sample_peak_linear': peak, 'sample_peak_dbfs': db(peak),
            'rms_linear': rms, 'rms_dbfs': db(rms), 'channel_rms_linear': per_channel,
            'channel_peak_linear': self.peak.tolist(), 'lr_pearson_correlation': correlation,
            'near_full_scale_sample_fraction': self.near/total if total else None,
            'digital_rail_sample_fraction': self.full/total if total else None,
            'over_full_scale_sample_fraction': self.over/total if total else None,
            'exact_zero_sample_fraction': self.zeros/total if total else None,
            'silence_duration_fraction': self.quiet_frames/self.frames if self.frames else None,
            'invalid_silence_window_duration_fraction': self.invalid_window_frames/self.frames if self.frames else None}


def measure(path):
    before_hash = digest(path)
    before_stat = path.stat()
    info = sf.info(path)
    if not 0 < info.duration <= 1800 or not 1 <= info.channels <= 8 or not 8000 <= info.samplerate <= 192000:
        raise ValueError('Audio outside bounded measurement envelope')
    bits = {'PCM_16':16, 'PCM_24':24, 'PCM_32':32}.get(info.subtype)
    rail = 1-2**(-(bits-1)) if bits else 1.0
    total = Accumulator(info.channels, info.samplerate, rail)
    windows = []
    with sf.SoundFile(path) as stream:
        while True:
            start = stream.tell()
            block = stream.read(round(20*info.samplerate), dtype='float64', always_2d=True)
            if not len(block):
                break
            part = Accumulator(info.channels, info.samplerate, rail)
            part.add(block)
            total.merge(part)
            windows.append({'start_seconds':start/info.samplerate, 'end_seconds':stream.tell()/info.samplerate, **part.report()})
    if total.frames != info.frames or digest(path) != before_hash or path.stat().st_mtime_ns != before_stat.st_mtime_ns:
        raise RuntimeError('Audio changed during measurement')
    return {'source': {'path':str(path), 'sha256':before_hash, 'bytes':before_stat.st_size,
            'frames':info.frames, 'duration_seconds':info.duration, 'sample_rate':info.samplerate,
            'channels':info.channels, 'container':info.format, 'subtype':info.subtype},
            'overall':total.report(), 'windows_20_seconds':windows,
            'method': {'decoding':'libsndfile to normalized float64; no gain or resampling for statistics',
                'silence':'20ms non-overlapping windows; every channel RMS below -60dBFS; duration-weighted',
                'near_full_scale_threshold':.999, 'digital_rail_abs_threshold':rail,
                'clipping_interpretation':'Digital-rail/near-full-scale counts are proxies, not proof of unwanted clipping. Deliberate gritty distortion may be requested.',
                'rms':'Unweighted sample RMS, not LUFS, true peak, or perceived loudness',
                'channel_correlation':'Pearson L/R across valid paired samples; undefined for constant channels; does not prove pad width or mix quality',
                'invalid_samples':'Counted and flagged; excluded from derived RMS/peak/correlation; invalid silence windows not classified as quiet',
                'dbfs_null':'Zero amplitude or undefined is represented as null, not NaN/Infinity',
                'window_labels':'Absolute elapsed-time blocks only; not inferred song sections'}}


def num(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def report_html(report, destination):
    source = report['source']
    overall = report['overall']
    relative_audio = quote(os.path.relpath(source['path'], destination.parent).replace(os.sep, '/'), safe='/.-_')
    rows = ''.join('<tr><td>'+f'{w["start_seconds"]:.0f}–{w["end_seconds"]:.1f}s'+'</td>'
        + ''.join('<td>'+html.escape(v)+'</td>' for v in [num(w['rms_dbfs']),num(w['sample_peak_dbfs']),num(100*w['silence_duration_fraction']),num(100*w['digital_rail_sample_fraction']),num(w['lr_pearson_correlation'],3)])
        +f'<td><a href="{relative_audio}#t={w["start_seconds"]},{w["end_seconds"]}" target="_blank" rel="noopener">试听此段</a></td></tr>' for w in report['windows_20_seconds'])
    beat = report.get('beat_estimate', {})
    bpm = beat.get('raw_bpm')
    alternatives = ', '.join(num(v) for v in beat.get('half_raw_double_bpm', [])) or '未取得'
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(report['label'])} — 客观音频检查</title><style>body{{font:16px/1.6 system-ui,sans-serif;max-width:1050px;margin:32px auto;padding:0 20px;color:#20242b;background:#f6f7f9}}h1{{font-size:28px}}section{{background:white;border:1px solid #dce1e7;padding:20px;margin:20px 0}}audio{{width:100%}}table{{border-collapse:collapse;width:100%}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #e5e8ed}}code{{overflow-wrap:anywhere}}.muted{{color:#596273}}a{{color:#145da0}}</style>
<h1>{html.escape(report['label'])}：客观检查与试听</h1><p>人工听感状态：<strong>未试听</strong>。本页不判断 Jungle 风格、Amen 来源、MC 内容或六段结构是否实现。</p>
<section><audio controls preload="none" src="{relative_audio}"></audio><p><a href="{relative_audio}" target="_blank" rel="noopener">直接打开原始云端音频</a> · 不复制音频，不嵌入 base64</p>
<p>{source['duration_seconds']:.3f} 秒 · {source['sample_rate']} Hz · {source['channels']} 声道 · {html.escape(source['subtype'])}</p><code>SHA256 {source['sha256']}</code></section>
<section><h2>整体指标</h2><p>有限值：{str(overall['all_samples_finite'])}；非有限样本 {overall['nonfinite_samples']}。RMS {num(overall['rms_dbfs'])} dBFS，样本峰值 {num(overall['sample_peak_dbfs'])} dBFS，静音时长比例 {num(100*overall['silence_duration_fraction'])}%。</p>
<p>接近满幅样本 {num(100*overall['near_full_scale_sample_fraction'],4)}%；数字满幅样本 {num(100*overall['digital_rail_sample_fraction'],4)}%；L/R相关 {num(overall['lr_pearson_correlation'],3)}。</p>
<p class="muted">RMS不是LUFS，样本峰值不是true peak。满幅比例不直接等同坏音质，提示词明确要求粗粝和轻微失真。整体相关系数不证明背景pad的宽度。</p></section>
<section><h2>节拍模型估计</h2><p>状态：{html.escape(str(beat.get('status','not_requested')))}；原始未折叠BPM：{num(bpm)}；半拍/原始/倍拍候选：{alternatives}。</p><p>提示词参考关系：85 / 170 / 340 BPM；不会为了符合提示词强制改成170。拍点稳定性：{html.escape(str(beat.get('stability','未测')))}。</p><p class="muted">自动节拍可能错拍、漏拍或产生半拍/倍拍歧义；与目标接近也不能证明风格或结构遵循。</p></section>
<section><h2>每20秒概览</h2><table><thead><tr><th>时间</th><th>RMS dBFS</th><th>峰值 dBFS</th><th>静音 %</th><th>满幅 %</th><th>L/R相关</th><th>试听</th></tr></thead><tbody>{rows}</tbody></table><p class="muted">时间块只是统计分段，不能据此命名Intro、Drop或Breakdown。完整方法和拍点见同目录report.json。</p></section></html>'''
    destination.write_text(body, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--label', choices=['ACE','YuE2'], required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--beats', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only audio measurement; no audio transfer to E:')
    source = args.input.resolve(strict=True)
    if not source.is_relative_to(ROOT) or not source.is_file():
        raise ValueError('Input must be an explicit file inside the cloud project')
    if digest(source) != args.expected_sha256:
        raise ValueError('Input SHA differs from the generation receipt')
    output = REPORT_ROOT/args.label.lower()
    output.mkdir(parents=True, exist_ok=True)
    if (output/'report.json').exists():
        raise FileExistsError('Preserve prior report; choose an explicit new evaluation instead of overwriting')
    started = time.monotonic()
    report = measure(source)
    report.update(label=args.label, created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        prompt_reference_sha256=PROMPT_SHA, prompt_provenance='Generation receipt owns full prompt verification',
        listened=False, style_accuracy_evaluated=False, structure_evaluated=False, daw_connected=False,
        analyzer={'path':str(Path(__file__).resolve()),'sha256':digest(Path(__file__))},
        environment={'python':platform.python_version(),'numpy':np.__version__,'soundfile':sf.__version__})
    write_json(output/'measurements.json', report)
    if args.beats and report['overall']['all_samples_finite']:
        env = os.environ.copy()
        env.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2', HF_HUB_OFFLINE='1')
        command = [str(ROOT/'envs/mir-torch/bin/python'), str(Path(__file__).with_name('analyze_beats.py')),
                   '--input', str(source), '--output', str(output/'beats.json')]
        try:
            with (output/'beats.log').open('wb') as log:
                result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=240)
            if result.returncode != 0:
                raise RuntimeError('BeatThis CPU worker failed; see cloud beats.log')
            report['beat_estimate'] = json.loads((output/'beats.json').read_text())
        except Exception as error:
            report['beat_estimate'] = {'status':'failed','error_type':type(error).__name__, 'raw_bpm':None,
                                       'detail':'No automatic retry or forced170BPM; inspect cloud beats.log'}
    else:
        report['beat_estimate'] = {'status':'not_requested' if not args.beats else 'skipped_nonfinite', 'raw_bpm':None}
    report['elapsed_seconds'] = time.monotonic()-started
    write_json(output/'report.json', report)
    report_html(report, output/'report.html')
    print(json.dumps({'label':args.label,'report':str(output/'report.json'),'source':report['source'],
                      'overall':report['overall'],'beat_status':report['beat_estimate']['status'],
                      'raw_bpm':report['beat_estimate'].get('raw_bpm'),'elapsed_seconds':report['elapsed_seconds']}), flush=True)


if __name__ == '__main__':
    main()
