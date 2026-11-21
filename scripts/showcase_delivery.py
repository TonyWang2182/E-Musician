"""Finish the local film handoff after explicit visual review of final frames."""
from __future__ import annotations
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from showcase_firstcut import KIT
from showcase_assemble import digest, write


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--visual-reviewed',action='store_true',required=True)
    args=parser.parse_args()
    qa=json.loads((KIT/'exports/FINAL-TECHNICAL-QA.json').read_text())
    assert qa['status']=='technical-checks-passed'
    films=qa['films']
    for item in films.values():assert digest(item['path'])==item['sha256']
    reviewed=['final-film-contact-sheet.png','G03-34s.png','C01-96.5s.png','T01-145s.png','T04-164.5s.png','D403-185.5s.png','W03-138.5s.png','C03-110.5s.png','E01-234s.png']
    visual={'status':'reviewed','reviewed_at':datetime.now(timezone.utc).isoformat(),
        'method':'Direct visual inspection of the final encoded-film contact sheet and selected full-size frames.',
        'frames':[{'path':str(KIT/'exports/qa'/p),'sha256':digest(KIT/'exports/qa'/p)} for p in reviewed],
        'findings':['No error dialogs or blank replacement product screens in sampled frames.',
          'C01 and T01 use editorial crops of actual captured pixels, excluding an unrelated prior Agent conversation.',
          'T04 and the opening piano preview omit the internal capture-project header; actual note pixels remain.',
          'C01/W03 retain real pixels and restore recorded frame wall timing; source audio stays at normal speed. G03 begins with actual Previewing state, no running transport is invented.',
          'D403 intentionally combines an existing sax-track crop with an abstract graphic; genuine incoming recording/performer footage is still pending.',
          'Opening and closing retain the original tree logo and the repository URL.'],
        'limits':'Sampled visual review and automated audio measures, not physical-device or human-listening acceptance.',
        'film_sha256':{role:f['sha256'] for role,f in films.items()}}
    visual['encoded_midpoint_readouts']=[
        {'shot':'C01','film_seconds':96.5,'visible_position':'2:2:845','visible_project_seconds':2.9401041666666665,'mapped_audio_seconds':2.9,'difference_seconds':0.04010416666666661},
        {'shot':'W03','film_seconds':138.5,'visible_position':'2:4:384','visible_project_seconds':3.7,'mapped_audio_seconds':3.759895833333333,'difference_seconds':-0.05989583333333286}]
    write(KIT/'exports/VISUAL-REVIEW.json',visual)
    lines=['# E-musician · 4 分钟影片交付','',
      '- [英文旁白版](E-musician-Showcase-240s-English.mp4)：本机 Microsoft Zira 配音，包含可关闭的英文软字幕。',
      '- [无旁白音乐版](E-musician-Showcase-240s-Music-Only.mp4)：同一画面，保留试听与配乐，不含旁白或字幕；已取消为旁白设置的音乐压低。','',
      '两版均为 **240 秒、1920×1080、30 fps、7200 帧、48 kHz 双声道**。已完整解码检查，两个版本的画面码流一致；全部指定试听段都有声音，没有解码后的满幅削波样本。','',
      '| 版本 | 文件大小 | 综合响度 | True peak |','|---|---:|---:|---:|']
    for role,label in [('english','英文'),('music_only','无旁白')]:
        f=films[role];l=f['audio']['loudness']
        lines.append(f'| {label} | {f["bytes"]/1024/1024:.2f} MiB | {l["input_i"]} LUFS | {l["input_tp"]} dBTP |')
    lines+=['','片段以实际 DAW 录屏和实际界面截图剪辑；未绘制假的操作状态、播放头或录音波形。D4 在 02:48–03:48 使用同一条原创工程音频从 0 到 60 秒连续播放，画面切换不重启声音。','',
      '**还需要你补的镜头：03:01–03:10 的萨克斯分屏。** 当前左侧是已有萨克斯轨，右侧是抽象萨克斯动效；它不是实时录音过程。用真实麦克风录入画面和你已有的演奏视频替换这一段，并依据共同音频瞬态对齐。','',
      '发布前完整试听一遍，确认声音平衡、画面与解说节奏。自动指标不能替代听感验收。这里使用固定历史模型结果，不连接 SSH 或 API，不代表本次发生新推理，也不代表显示的等待是模型实际耗时。YuE2/ACE 是约 32 秒草稿，Tea for Two 是 16 秒摘录。','',
      '- [返回拍摄包入口](../START-HERE.md)',
      '- [英文分镜](../scripts/2026-11-22-showcase-script-en.md) · [中文对照](../scripts/2026-11-22-showcase-script-zh.md)',
      '- [最终镜头及声音映射](../scripts/shot-map-final-2026-11-22.json) · [剪辑接手说明](../scripts/FINAL-CUT-HANDOFF.md)',
      '- [英文 SRT](../narration/voice-en.srt) · [中文 SRT](../narration/voice-zh.srt)',
      '- [技术验证](FINAL-TECHNICAL-QA.json) · [抽帧总览](qa/final-film-contact-sheet.png) · [视觉检查](VISUAL-REVIEW.json)','',
      '最终 SHA-256（用于复核文件未变）：','']
    for role in ('english','music_only'):
        f=films[role];lines += [f'- `{Path(f["path"]).name}`：`{f["sha256"]}`']
    (KIT/'exports/DELIVERY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    entry=KIT/'START-HERE.md';s=entry.read_text(encoding='utf-8')
    inserted='**先看成片：** [英文旁白版](exports/E-musician-Showcase-240s-English.mp4) · [无旁白音乐版](exports/E-musician-Showcase-240s-Music-Only.mp4) · [交付与待补镜头](exports/DELIVERY.md)。两版都是 4 分钟；萨克斯实时录音分屏仍需你补拍。\n\n'
    if '**先看成片：**' not in s:s=s.replace('# E-musician 拍摄包入口\n\n','# E-musician 拍摄包入口\n\n'+inserted)
    s=s.replace('[声音与待补镜头清单](scripts/FIRST-CUT-HANDOFF.md)','[最终声音与待补镜头清单](scripts/FINAL-CUT-HANDOFF.md)')
    entry.write_text(s,encoding='utf-8')
    m=json.loads((KIT/'scripts/shot-map-final-2026-11-22.json').read_text())
    handoff=['# Final-cut audio and capture handoff','',
      'This final map supersedes FIRST-CUT-HANDOFF.md and shot-map-firstcut-draft.json. Those earlier draft files are retained for audit. All final picture/audio paths are available; no pending nulls remain.','',
      '| Film timeline | Audio source | Source in | Gain |','|---|---|---:|---:|']
    for a in m['audio']:
        handoff.append(f'| {a["timeline_start"]:g}–{a["timeline_start"]+a["duration"]:g}s | {a["label"]} | {a.get("source_in",0):g}s | {a.get("gain_db",0):g} dB'+(' with VO ducking' if a.get('gain_envelope') else '')+' |')
    handoff+=['','YuE Preview begins at source zero on the first captured Previewing state. C01/W03 native frames are restored to their recorded wall times; audio starts at their actual first-frame musical positions (0.400s / 0.259895833s). Four manually observed musical-time readouts per clip agree with the capture timestamps to within 80ms. This is visual timeline alignment, not sample-accurate device synchronization. No-narration output retains source clocks/cuts and removes VO ducking.','',
      'Demo4 is one continuous 0–60-second source at film 168–228 seconds. The sampler close-up occurs after its audible 15–18-second trigger, not a newly performed trigger. D403 (181–190s) is a real existing sax-track crop beside abstract motion. Replace it with genuine recording/performer footage before describing the sequence as an incoming-recording demonstration. No synthetic recording waveform or meter was drawn.','',
      'Real final visuals combine native capture videos and static native screenshots. C01/T01 crop unrelated old Agent replies; O02/T04 crop the internal capture project header. These are editorial crops only. Fixed historical model results are used without new inference.','',
      '[Final map](shot-map-final-2026-11-22.json) · [Frame timing evidence](../captures/final-edit/NATIVE-TIME-ALIGNMENT.json) · [Film delivery](../exports/DELIVERY.md) · [Technical QA](../exports/FINAL-TECHNICAL-QA.json)']
    (KIT/'scripts/FINAL-CUT-HANDOFF.md').write_text('\n'.join(handoff)+'\n',encoding='utf-8')
    files=['showcase_motion.py','showcase_assemble.py','showcase_firstcut.py','showcase_finalcut.py','showcase_final_qa.py','showcase_delivery.py','showcase_sync.py']
    for name in files:shutil.copy2(Path('scripts')/name,KIT/'motion/source'/name)
    checked=[]
    for path in [entry,KIT/'exports/DELIVERY.md',KIT/'scripts/FINAL-CUT-HANDOFF.md']:
        for dest in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
            if dest.startswith(('http:','https:','#')):continue
            target=(path.parent/unquote(dest.split('#')[0])).resolve();assert target.exists(),target
            checked.append(str(target))
    help_check=subprocess.run([sys.executable,'scripts/showcase_bundle.py','--help'],capture_output=True,text=True)
    assert help_check.returncode==0 and '--reset-projects' in help_check.stdout and '--out' in help_check.stdout
    old=json.loads((KIT/'tests/ENTRY-DOC-VALIDATION.json').read_text())
    for launcher in old['launchers']:assert Path(launcher['exe']).is_file();assert digest(launcher['path'])==launcher['sha256']
    old.update(status='passed',relative_links_verified=len(checked),reset_cli_help_checked=True,reset_executed=False,
      entry_sha256=digest(entry),final_films_verified=True,visual_review=str(KIT/'exports/VISUAL-REVIEW.json'),
      source_copies={name:digest(KIT/'motion/source'/name) for name in files})
    write(KIT/'tests/ENTRY-DOC-VALIDATION.json',old)
    print(json.dumps({'status':'delivered','films':{k:v['path'] for k,v in films.items()},'entry_links':len(checked),'visual_review':str(KIT/'exports/VISUAL-REVIEW.json')},indent=2))


if __name__=='__main__':main()
