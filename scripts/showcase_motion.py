"""Offline 240-second film kit: original procedural motion, local Zira voice, scripts.

No network, model call, DAW launch or user-project mutation. Brand artwork is copied
without modification. Movie backgrounds are authored mathematical fields, not
frames extracted from the reference film. Run with --mode docs/render/tts/verify.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
import textwrap
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
URL = "https://github.com/TonyWang2182/E-Musician"
LOGO_HASH = "6b94245a35170ebbcab97a1cec0a5d5bde08233f1c8bbe8f671f314fd34005a2"
ROOT = Path(__file__).resolve().parents[1]

# One ordered source keeps the English, Chinese, TTS and caption timelines aligned.
# id, start, end, English voice, Chinese voice, English operation, Chinese operation, edit.
SHOTS = [
    ("O01", 0, 8, "Meet E-musician: an open-source music workspace with an assistant built into the creative process.", "认识 E-musician：一个将智能助手融入创作过程的开源音乐工作台。", "Play opener-1080p30.mp4. Keep the approved tree-musician logo, product name and repository URL readable.", "播放新片头，完整显示原版树乐师 logo、产品名称与开源网址。", "Brand reveal; restrained slow light, no fast cuts."),
    ("O02", 8, 18, "Generate ideas, explore audio, and shape every detail. The software helps; the musical decisions remain yours.", "生成想法、探索音频，再亲手塑造每处细节。软件提供帮助，音乐的决定仍由你来做。", "Cut between the English arrangement, Agent result, chord track and piano roll. Use actual screen recordings from later chapters.", "依次剪入英文编曲界面、Agent 结果、和弦轨与钢琴卷帘；使用后面章节的真实录屏。", "Four 2–3-second previews; gentle instrumental bed under voice."),
    ("G01", 18, 25, "I start with a neo-soul idea and ask YuE2 for a vocal sketch.", "先从一个 neo-soul 想法出发，请 YuE2 给出带人声的音乐草稿。", "Open New ideas, open Agent, paste P1 and send once. Keep the project at 90 BPM, 4/4, playhead zero.", "打开 New ideas，展开 Agent，粘贴 P1 并发送一次。工程保持 90 BPM、4/4，播放头归零。", "Use chapter-01-generation for 0.6 seconds, then zoom to prompt; trim typing pauses."),
    ("G02", 25, 31, "The result stays separate from my project until I choose to use it.", "在我决定使用之前，结果会作为候选保留，不直接改变工程。", "Hold on the working state; jump-cut or speed up the middle of the wait. End on the YuE2 result and Preview control.", "拍到处理状态；中间等待可跳剪或加速，结束时停在 YuE2 结果与 Preview 按钮。", "No stopwatch or speed claim. Keep cursor still after the click."),
    ("G03", 31, 37, "", "", "Click Preview on YuE2 and listen for six seconds; stop preview before applying.", "点 YuE2 的 Preview，留六秒纯试听；应用前停止预览。", "No narration or extra music; retain actual candidate audio."),
    ("G04", 37, 42, "I apply this version, then request another interpretation with ACE.", "先应用这个版本，再请 ACE 给出另一种演绎。", "Click Apply changes. Show the newly added YuE2 track. Paste P2 and send once without renaming the first track.", "点 Apply changes，展示新增 YuE2 轨；不改轨名，粘贴 P2 并发送一次。", "Track insertion gets a brief emphasis; keep workflow in one project."),
    ("G05", 42, 49, "Both options use the same workspace, so I can compare them directly.", "两个版本都在同一个工作台里，可以直接比较。", "Show ACE processing and its result card. Do not apply until after audition.", "展示 ACE 的处理状态与结果卡；先试听再应用。", "Compress only the wait; preserve Preview → Apply order."),
    ("G06", 49, 55, "", "", "Click ACE Preview and listen for six seconds; stop preview.", "点 ACE 的 Preview，留六秒纯试听，然后停止预览。", "Match audition loudness in editing without changing the project result."),
    ("G07", 55, 66, "I prefer this one. I add it to the arrangement, then remove the first track myself.", "我更喜欢这一版。把它加入编曲，再亲手删掉第一个版本的轨道。", "Apply ACE. Select the YuE2 track header and delete that track, not the ACE clip. Leave ACE's existing name unchanged; select its audio clip.", "应用 ACE；选中 YuE2 轨头并删除整条轨道，避免误删 ACE 片段。ACE 保留原名，选中它的音频片段。", "Show both tracks briefly, then the manual deletion and the remaining selected clip."),
    ("S01", 66, 74, "Next, I ask SCNet to separate the selected track into vocals, drums, bass, and other.", "接着，请 SCNet 把选中轨道分成人声、鼓、贝斯与其他四部分。", "Keep the ACE source selected and its name unchanged. Send P3. Capture the working state and four-result proposal.", "保持选中 ACE 来源，轨名不变；发送 P3，拍到处理状态与四轨结果方案。", "0.6-second chapter-02-separation transition, then the source selection and prompt."),
    ("S02", 74, 80, "I apply the four stems and mute the original.", "应用四个分轨，再把原曲静音。", "Click Apply changes. Mute the original ACE track. Make sure no other source is audible. Enable Solo on drums first.", "点 Apply changes；手动 Mute 原 ACE 轨，确认没有其他原曲叠放，先开启 drums 的 Solo。", "Frame all four track headers; emphasize the original M button once."),
    ("S03", 80, 94, "", "", "Audition drums, then add bass Solo, other Solo, and vocals Solo while retaining previous Solo states. Use roughly 3.5 seconds per layer.", "先听鼓，再依次开启 bass、other、vocals 的 Solo，保留前面已开的 Solo，每层约 3.5 秒。", "Continuous audio; no voice. Verify additive Solo behaviour before recording, and return all Solo switches off at the end."),
    ("C01", 94, 99, "", "", "Open New Light, with its 24-second excerpt already imported. Play five seconds of the source.", "打开 New Light，录制前已导入 24 秒摘段；先播放五秒原曲。", "0.6-second chapter-03-harmony transition included in this slot; source audio comes forward."),
    ("C02", 99, 107, "With an existing song, the assistant can estimate its harmony. I ask it to analyze New Light.", "面对已有歌曲，助手也能估计它的和声。我请它分析 New Light。", "Stop playback, select the source clip, and send P4. Wait for the prepared chord analysis.", "停止播放，选中来源片段，发送 P4，等待和弦分析候选。", "Focus follows selection → prompt → result; do not claim perfect recognition."),
    ("C03", 107, 114, "Then I open Analysis and apply the result as an editable chord track.", "随后打开 Analysis，把结果应用为可编辑的和弦轨道。", "Open the lower Analysis panel, choose the latest completed Chords result in Recent analyses, and apply it to a chord track. After rerunning analysis, close and reopen the list to refresh it.", "手动展开底部 Analysis，选中已完成的 Chords 结果，通过面板操作应用到和弦轨。", "Keep the manual panel application visible; do not replace it with an Agent Apply shot."),
    ("C04", 114, 122, "The chords follow the timeline, so I can inspect them in the context of the music.", "和弦与时间线对应，我可以结合音乐检查这些结果。", "Play the source with the chord lane visible. Frame readable chord labels and the moving playhead.", "显示和弦轨并播放来源，让标签和移动播放头同时可见。", "One slow crop that follows the relevant bars; no invented chord labels in post."),
    ("W01", 122, 130, "Next, I ask it to detect the beat and align this audio to the project's tempo.", "接着请它检测节拍，并把音频对齐到工程速度。", "Keep the same New Light project and source. Send P5; retain the 120 BPM project tempo and review the source tempo of 125 BPM.", "继续使用同一 New Light 工程与来源，发送 P5；工程保持 120 BPM，检查来源速度 125 BPM。", "0.6-second chapter-04-timing transition; emphasize 125 → 120 only after actual values appear."),
    ("W02", 130, 135, "I review the alignment and apply pitch-preserving Warp.", "检查对齐方案后，应用保音高的 Warp 拉伸。", "Click Apply changes. Open Source if needed and show Warp enabled, with source and target tempo visible.", "点 Apply changes；必要时打开 Source，展示 Warp 已开启及来源、目标速度。", "Do not say lossless or perfect. Keep the real changed clip alignment on screen."),
    ("W03", 135, 142, "", "", "Audition the warped audio against the grid. Keep the chord track visible if it follows the accepted mapping.", "沿网格试听 Warp 后音频；若和弦轨已随映射调整，保持它可见。", "Seven seconds of audio, no narration; do not add a fake metronome or grid animation."),
    ("T01", 142, 148, "Here is an isolated piano performance from Tea for Two.", "这里是一段来自 Tea for Two 的钢琴分轨演奏。", "Open Tea for Two with the existing 16-second piano source. Briefly play the source, then select its clip.", "打开 Tea for Two，使用已有 16 秒钢琴来源，短暂播放后选中片段。", "0.6-second chapter-05-transcription transition; let the last two seconds be source audio."),
    ("T02", 148, 155, "I ask TransKun to turn the performance into editable MIDI.", "请 TransKun 把这段演奏转换成可编辑的 MIDI。", "Send P6. Capture working state and the completed MIDI proposal.", "发送 P6，拍到处理状态与 MIDI 候选结果。", "Show the operation, not logs; no note-accuracy claim."),
    ("T03", 155, 161, "I apply the notes and load a piano instrument.", "应用音符，再加载一个钢琴音源。", "Apply changes, select the new MIDI track, and add the installed Keyscape piano through Library/Add plugin. Mute the source audio before the MIDI audition.", "应用结果，选中新增 MIDI 轨，通过 Library/Add plugin 添加已安装的 Keyscape 钢琴；试听前静音原音频。", "Cut the instrument's loading wait; show actual loaded editor/preset and piano roll."),
    ("T04", 161, 168, "", "", "Play the MIDI through the loaded piano. Frame the 132-note piano-roll result without implying perfect transcription.", "用加载的钢琴回放 MIDI；展示包含 132 个音符的卷帘结果，不宣称转录完全准确。", "Seven seconds of MIDI piano audio only. Never substitute source audio for the MIDI output."),
    ("D401", 168, 173, "This is my own production, playing inside E-musician.", "这是我自己的作品，正在 E-musician 中播放。", "In production version 0.13.6, open a filming copy of test drive and start at project time zero. Music now continues through the entire chapter.", "切换到正式版 0.13.6，打开 test drive 的拍摄副本，从工程零秒开始；本章音乐持续播放。", "0.6-second chapter-06-workspace transition; use one continuous DAW audio recording underneath."),
    ("D402", 173, 181, "The piano roll exposes the notes, while VST support brings my existing instruments into the same project.", "钢琴卷帘让音符清晰可编辑，VST 支持则把原有音源带进同一个工程。", "Show MAIN DRUM's piano roll with BM-VOID, then EP's notes with Keyscape. Preload both instruments before the take.", "展示 MAIN DRUM 的卷帘与 BM-VOID，再展示 EP 音符和 Keyscape。拍摄前预加载两款音源。", "Use short detail inserts captured separately at matched project times; return to arrangement before project time 13.031 seconds."),
    ("D403", 181, 190, "Audio recording keeps the performance inside the arrangement.", "音频录音让演奏直接进入编曲。", "At project time 13.031 seconds, show the configured recording target and genuine incoming signal. Pair it with the same performance video when provided; otherwise use the abstract sax motion insert.", "工程约 13.031 秒处展示已设好输入的录音目标和真实输入信号；有同段演奏视频时与之分屏，暂缺时使用抽象萨克斯动效。", "55% DAW / 45% performer or abstract insert. Never fabricate a growing recording waveform. The abstract asset is not a person or proof of a live take."),
    ("D404", 190, 197, "Samples become playable instruments, with direct control over the sound.", "采样可以成为可演奏的乐器，声音细节也能直接控制。", "Open SAMPLE-RISE's Sampler and its waveform/trim controls while playback continues. Its arrangement trigger was at project time 15–18 seconds.", "播放继续，打开 SAMPLE-RISE 的 Sampler，展示波形与区间控制；该片段实际触发于工程 15–18 秒。", "This is a device-detail shot, not an assertion that the sampler is sounding at this moment. Use a synchronized earlier insert if highlighting its audible rise."),
    ("D405", 197, 206, "The Drum Rack puts individual sounds and their controls within reach.", "Drum Rack 把每个声音及其控制集中在眼前。", "Open RACK, frame the four populated pads, and select one pad to show its sample. The MIDI part is active between project time 18.75 and 44.413 seconds.", "打开 RACK，框出四个已加载素材的垫，选一垫展示采样；其 MIDI 在工程 18.75–44.413 秒间活动。", "Crop to pads → waveform; do not trigger extra pads over the continuous soundtrack unless that audition is intentionally recorded."),
    ("D406", 206, 218, "An ordered effects chain keeps equalization, dynamics, filtering, and space close to the track.", "按顺序排列的效果链，让均衡、动态、滤波与空间处理紧邻轨道。", "Show DRUM 2 EQ Eight, then RACK Compressor/Auto Filter and sax_player Reverb/Delay. Only demonstrate an audible adjustment if its actual output is captured.", "依次展示 DRUM 2 的 EQ Eight、RACK 的 Compressor/Auto Filter、sax_player 的 Reverb/Delay；若调参数，声音必须来自实际操作。", "Three close-ups, 3–4 seconds each; let the response graph, gain reduction or knob be the focus. Keep transport audio unbroken."),
    ("D407", 218, 228, "The assistant and the editor share one workspace. I can work by instruction, by hand, or move between them.", "助手与编辑器共享同一个工作台。我可以发指令，也可以亲手调整，随时切换。", "Return to the full arrangement. Let the original track approach its ending; do not restart playback or open an unrelated project.", "回到全编曲画面，让原创曲自然接近尾声，不重新播放、不切换无关工程。", "Widen slowly; retain the project's real master fade. Narration ends before the closing invitation."),
    ("E01", 228, 240, "E-musician is built around the musician. Explore the open-source project, try it, and help shape what comes next.", "E-musician 围绕音乐创作者而构建。欢迎探索开源项目、亲自试用，并一起塑造它的下一步。", "Play closer-1080p30.mp4. Hold the logo and full repository URL long enough to read. Fade music with the final frame.", "播放新片尾，给 logo 与完整开源网址足够阅读时间，随最后画面淡出音乐。", "Keep the final URL static for at least five seconds; no feature list or metrics on the closing card."),
]

PROMPTS = {
    "P1": "Use YuE2 to create a short neo-soul idea at 90 BPM in 4/4, with warm Rhodes, mellow electric guitar, rounded bass, laid-back drums, and intimate female vocals. Include a short intro, verse, and chorus. Let me preview it before adding it.",
    "P2": "Use ACE-Step for another take of the same neo-soul brief at 90 BPM in 4/4. Keep the warm Rhodes, mellow guitar, rounded bass, laid-back drums, and intimate female vocal. Let me preview it before adding it.",
    "P3": "Use SCNet to separate the selected audio into vocals, drums, bass, and other. Keep the original track and its name. Let me apply all four stems together.",
    "P4": "Analyze the chords in the selected New Light clip with ChordMini. Let me review them in Analysis before adding a chord track.",
    "P5": "Detect the beats in the selected audio and align it to this 120 BPM project with pitch-preserving Warp. Keep the chord track aligned.",
    "P6": "Transcribe the selected Tea for Two piano stem to MIDI with TransKun. Let me review it before adding a MIDI track.",
}

EDITS_ZH = {
    "O01": "品牌缓缓显现，柔光慢移，不使用快速跳切。",
    "O02": "四个各约2–3秒的预告镜头；旁白下铺轻柔器乐。",
    "G01": "先用生成章背景0.6秒，再推近提示词；剪掉输入时停顿。",
    "G02": "不显示秒表、不做速度宣称；点击后把指针停稳。",
    "G03": "无旁白、无额外配乐，保留真实候选音频。",
    "G04": "短暂强调轨道加入，始终保持同一个工程。",
    "G05": "只压缩等待，保留先 Preview 再 Apply 的操作顺序。",
    "G06": "后期将两次试听的响度尽量匹配，不修改原始工程结果。",
    "G07": "先短暂显示两轨，再拍手动删除及剩下的选中片段。",
    "S01": "0.6秒分离章背景，然后突出来源选择与提示词。",
    "S02": "让四个轨头同时入画，短暂强调原曲的 M 按钮。",
    "S03": "音乐连续、没有旁白；拍前验证多个 Solo 可叠加，结束后恢复所有 Solo 关闭。",
    "C01": "0.6秒和弦章背景包含在本镜时间内，随后让原曲声音进入前景。",
    "C02": "焦点跟随来源选择、提示词、结果，不宣称识别完全准确。",
    "C03": "保留手动在 Analysis 中应用的画面，不能换成 Agent Apply 镜头。",
    "C04": "缓慢推近相关小节，不在后期添加伪造和弦标签。",
    "W01": "0.6秒节拍章背景；实际数值出现后才强调125到120的变化。",
    "W02": "不说绝对无损或完美；显示真实改变后的片段与网格。",
    "W03": "七秒纯音频；不添加伪造节拍器声或网格动画。",
    "T01": "0.6秒转录章背景，最后两秒留给原钢琴声音。",
    "T02": "展示操作而非技术日志，不做音符准确率宣称。",
    "T03": "可剪掉音源加载等待，但要展示真实加载好的界面、音色与卷帘。",
    "T04": "七秒仅听MIDI钢琴；不能拿原音频代替MIDI回放。",
    "D401": "0.6秒工作台章背景，底下使用同一次录下的连续DAW输出。",
    "D402": "可分次补拍局部，但须按工程时间对齐；工程13.031秒前回到编曲界面。",
    "D403": "左侧DAW占55%，右侧演奏者或抽象动效占45%；不能伪造增长的录音波形，抽象素材也不代表真人或实录证据。",
    "D404": "这是装置细节展示，不宣称此刻正在触发；若要突出采样音色，可用与15–18秒同步的早先插镜。",
    "D405": "从垫推近到波形；除非确实录入试听声，否则不要在连续配乐上额外敲垫。",
    "D406": "三个各3–4秒特写，重点看响应图、压缩量或旋钮，音乐不断。",
    "D407": "缓慢拉回全景，保留工程真实主音量淡出；旁白结束后进入结尾邀请。",
    "E01": "最终网址至少静止五秒，不在片尾堆功能清单或性能数字。",
}

CAPTION_CLAUSES = {
    'O01': ['Meet E-musician: an open-source music workspace', 'with an assistant built into the creative process.'],
    'O02': ['Generate ideas, explore audio, and shape every detail.', 'The software helps; the musical decisions remain yours.'],
    'G07': ['I prefer this one. I add it to the arrangement,', 'then remove the first track myself.'],
    'S01': ['Next, I ask SCNet to separate the selected track', 'into vocals, drums, bass, and other.'],
    'C02': ['With an existing song, the assistant can estimate its harmony.', 'I ask it to analyze New Light.'],
    'C04': ['The chords follow the timeline,', 'so I can inspect them in the context of the music.'],
    'W01': ['Next, I ask it to detect the beat', "and align this audio to the project's tempo."],
    'D402': ['The piano roll exposes the notes,', 'while VST support brings my existing instruments into the same project.'],
    'D406': ['An ordered effects chain keeps equalization, dynamics,', 'filtering, and space close to the track.'],
    'D407': ['The assistant and the editor share one workspace.', 'I can work by instruction, by hand, or move between them.'],
    'E01': ['E-musician is built around the musician.', 'Explore the open-source project, try it,', 'and help shape what comes next.'],
}

CHAPTERS = [
    ("chapter-01-generation", "dark", 0.0),
    ("chapter-02-separation", "dark", 1.1),
    ("chapter-03-harmony", "silver", 2.0),
    ("chapter-04-timing", "aqua", 2.8),
    ("chapter-05-transcription", "silver", 4.0),
    ("chapter-06-workspace", "dark", 5.1),
]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tc(s):
    m, sec = divmod(int(s), 60)
    return f"{m:02}:{sec:02}"


def srt_time(s):
    ms = round(s * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def dump(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args, log):
    t = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([str(a) for a in args], capture_output=True)
    log.write_bytes(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError(f"exit {proc.returncode}: {log}")
    return {"command": [str(a) for a in args], "seconds": time.monotonic() - t,
            "exit": proc.returncode, "log": str(log)}


def resolve_logo():
    p = ROOT / "assets/brand/yi-yue-shi-logo.png"
    if not p.exists():
        p = Path(__file__).parent / "yi-yue-shi-logo.png"
    assert sha(p) == LOGO_HASH, "Approved logo changed; do not silently substitute it"
    return p


class Motion:
    def __init__(self, logo):
        # Lower-resolution continuous fields followed by full-resolution fine grain.
        self.x, self.y = np.meshgrid(np.linspace(-1, 1, 640), np.linspace(-1, 1, 360))
        rng = np.random.default_rng(20261122)
        self.grain = rng.normal(0, 0.65, (H, W, 1)).astype(np.float32)
        self.logo = Image.open(logo).convert("RGBA")
        self.regular = "C:/Windows/Fonts/segoeui.ttf"
        self.semibold = "C:/Windows/Fonts/seguisb.ttf"
        self.fonts = {s: ImageFont.truetype(self.regular, s) for s in (27, 32, 40, 52, 92)}

    def background(self, t, kind="dark", offset=0, period=6):
        a = 2 * math.pi * t / period
        x, y = self.x, self.y
        light = np.zeros_like(x)
        for i in range(5):
            centre = -0.94 + i * 0.47 + 0.085 * np.sin(a + i * 1.6 + offset)
            bend = 0.035 * np.sin(4.4 * y + a + i) + 0.02 * np.cos(9 * y - a + offset)
            width = 0.075 + 0.025 * np.sin(a + 0.8 * i + offset) ** 2
            beam = np.exp(-((x - centre - bend) / width) ** 2)
            height = 0.15 + 0.85 * np.exp(-((y - 0.35 * np.sin(a + i + offset)) / 0.85) ** 2)
            light += beam * height * (0.56 + 0.15 * np.cos(a - i))
        broad = 0.3 * np.exp(-((x - 0.22 * np.sin(a)) / 0.7) ** 2 - ((y + .2) / 1.5) ** 2)
        if kind == "dark":
            base = np.array([2.0, 7.0, 9.0])
            colour = np.array([4.0, 105.0, 115.0])
            rgb = base + (light * .72 + broad)[..., None] * colour
        elif kind == "silver":
            base = np.array([219.0, 229.0, 235.0])
            colour = np.array([76.0, 87.0, 96.0])
            lower = (0.28 + 0.72 * (y + 1) / 2)
            rgb = base - (light * lower * .78 + broad * .25)[..., None] * colour
        else:
            ribbon = np.exp(-((y - .42 * np.sin(a + offset) - .2 * np.sin(x * 2.5 + a)) / .34) ** 2)
            rgb = np.array([224., 235., 237.]) - (ribbon * .77 + light * .14)[..., None] * np.array([139., 49., 47.])
        im = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize((W, H), Image.Resampling.BICUBIC)
        rgb = np.asarray(im).astype(np.float32) + self.grain
        return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).convert("RGBA")

    @staticmethod
    def ease(t, start, duration):
        k = max(0, min(1, (t - start) / duration))
        return 1 - (1 - k) ** 3

    def overlay(self, t, closer=False):
        im = Image.new("RGBA", (W, H))
        reveal = self.ease(t, .10, 1.15)
        # The original black-line logo is used unchanged on the pale film surface.
        logo = self.logo.resize((320, 320), Image.Resampling.LANCZOS)
        logo.putalpha(logo.getchannel("A").point(lambda p: round(p * reveal)))
        im.alpha_composite(logo, (238, round(350 + 18 * (1 - reveal))))
        d = ImageDraw.Draw(im)
        items = [(.35, 350, "E-musician", 92, (17, 28, 34)),
                 (1.15, 484, "Your music. Your decisions." if not closer else "Make music. Shape what comes next.", 40, (31, 58, 65)),
                 (1.65, 565, "A music workspace with an integrated assistant." if not closer else "Explore the code. Try it. Share your feedback.", 32, (44, 67, 74)),
                 (2.10, 665, URL, 27, (32, 70, 78))]
        for start, y, text, size, col in items:
            alpha = round(255 * self.ease(t, start, .75))
            d.text((650, y), text, font=self.fonts[size], fill=(*col, alpha), anchor="lt")
        return im

    def render(self, name, t):
        if name.startswith("opener") or name.startswith("closer"):
            close = name.startswith("closer")
            overlay = self.overlay(t, close)
            if "overlay" in name:
                return overlay
            bg = self.background(t, "silver", .25 if close else 1.3, 12 if close else 8)
            # Quiet the centre behind the logo and text while preserving edge light.
            wash = Image.new("RGBA", (W, H), (229, 236, 240, 90))
            bg = Image.alpha_composite(bg, wash)
            return Image.alpha_composite(bg, overlay)
        if name == "sax-abstract":
            bg = self.background(t, "dark", 1.4, 9)
            d = ImageDraw.Draw(bg)
            # One connected cubic gesture evokes a brass instrument without a fake performer.
            paths = [((720, 270),(820, 200),(920, 240),(920, 355)),
                     ((920,355),(920,500),(870,700),(955,790)),
                     ((955,790),(1060,900),(1240,820),(1240,670)),
                     ((1240,670),(1240,620),(1255,575),(1310,553))]
            dx = 8 * math.sin(t * 2 * math.pi / 9)
            pts=[]
            for points in paths:
                p0,p1,p2,p3=[np.array(p) for p in points]
                for k in range(50):
                    s=k/49
                    pos=(1-s)**3*p0+3*(1-s)**2*s*p1+3*(1-s)*s*s*p2+s**3*p3
                    pts.append((float(pos[0]+dx),float(pos[1])))
            d.line(pts, fill=(176, 190, 171, 235), width=7)
            d.ellipse((1270+dx,530,1400+dx,575),outline=(198,209,190,240),width=5)
            d.line([(720+dx,270),(683+dx,290)],fill=(198,209,190,240),width=12)
            for i in range(6):
                yy = 365 + i * 46
                xx = 950 + dx - 7 * math.sin(i / 2)
                alpha = round(110 + 110 * (.5 + .5 * math.sin(t * 2 * math.pi / 9 + i)))
                d.ellipse((xx-8, yy-8, xx+8, yy+8), fill=(166, 190, 177, alpha))
            return bg
        kind, off = next((k, o) for n, k, o in CHAPTERS if n == name)
        return self.background(t, kind, off)


def encode(motion, name, seconds, dst, ffmpeg, logs):
    alpha = "overlay" in name
    args = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "warning", "-f", "rawvideo", "-pixel_format", "rgba",
            "-video_size", f"{W}x{H}", "-framerate", str(FPS), "-i", "-", "-an"]
    if alpha:
        args += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "24", "-deadline", "good", "-cpu-used", "4", "-auto-alt-ref", "0"]
    else:
        args += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    args += [str(dst)]
    started = stamp()
    with (logs / f"{name}.log").open("wb") as log:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            for i in range(seconds * FPS):
                p.stdin.write(motion.render(name, i / FPS).tobytes())
            p.stdin.close()
            if p.wait():
                raise RuntimeError(f"Encoding failed: {dst}")
        except BaseException:
            p.kill()
            p.wait()
            raise
    print(f"Rendered {dst.name}", flush=True)
    return {"file": dst.name, "seconds": seconds, "frames": seconds*FPS, "sha256": sha(dst), "started": started, "finished": stamp(), "command": args}


def render(a):
    out = a.out / "motion"
    for c in ("logs", "source", "stills"):
        (out / c).mkdir(parents=True, exist_ok=True)
    logo = resolve_logo()
    motion = Motion(logo)
    shutil.copyfile(logo, out / "source/yi-yue-shi-logo.png")
    shutil.copyfile(__file__, out / "source/showcase_motion.py")
    assets = [(name, 6) for name, _, _ in CHAPTERS] + [("opener", 8), ("closer", 12), ("opener-overlay", 8), ("closer-overlay", 12), ("sax-abstract", 9)]
    records = []
    prior = out / "RENDER-MANIFEST.json"
    if a.only and prior.exists():
        records = [r for r in json.loads(prior.read_text())['assets'] if not r['file'].startswith(a.only+'-')]
    selected = [(n,s) for n,s in assets if not a.only or n == a.only]
    assert selected, "Unknown --only asset"
    for name, secs in selected:
        ext = "webm" if "overlay" in name else "mp4"
        records.append(encode(motion, name, secs, out / f"{name}-1080p30.{ext}", a.ffmpeg, out / "logs"))
        for t in (0, min(3, secs-1), secs-1/FPS):
            motion.render(name, t).save(out / "stills" / f"{name}-{t:.3f}.png")
    tiles = []
    for name, _ in assets:
        im = motion.render(name, 3)
        if "overlay" in name:
            b = Image.new("RGBA", im.size, (220, 228, 232, 255));b.alpha_composite(im);im = b
        im = im.convert("RGB").resize((480, 270))
        ImageDraw.Draw(im).text((12, 12), name, fill="white", stroke_width=2, stroke_fill="black")
        tiles.append(im)
    sheet = Image.new("RGB", (1440, 270*math.ceil(len(tiles)/3)), "#171d20")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i%3)*480, (i//3)*270))
    sheet.save(out / "stills/contact-sheet.png")
    dump(out / "RENDER-MANIFEST.json", {"created": stamp(), "logo_sha256": sha(logo), "reference": "visual direction only; no extracted video pixels", "width": W, "height": H, "fps": FPS, "assets": records})
    gallery = ''.join(f'<section><h2>{name}</h2><video controls loop muted preload="metadata" src="{name}-1080p30.{"webm" if "overlay" in name else "mp4"}"></video></section>' for name,_ in assets)
    (out / "preview.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>E-musician motion kit</title><style>body{margin:40px auto;max-width:1200px;background:#e4eaed;color:#13242a;font:18px system-ui}h1{font-weight:500}main{display:grid;grid-template-columns:1fr 1fr;gap:32px}h2{font-size:17px;font-weight:500}video{width:100%;background:#dce5e9}section{min-width:0}</style><h1>E-musician motion kit</h1><p>Silent 1080p30 assets. Use the separate narration track in your editor.</p><main>'+gallery+'</main></html>',encoding='utf-8')
    (out / "README.md").write_text("# Motion kit\n\nSix text-free chapter backgrounds: 6 seconds each, 1080p30, cyclic analytic motion. Use 0.6–1.0 seconds at chapter boundaries, or loop them as needed. Grain is deterministic and static so the seam does not pop.\n\nOpener: 8 seconds. The opening section is 18 seconds; fill its remaining 10 seconds with real product shots. Closer: 12 seconds. Alpha WebM overlays contain the unchanged logo and editable text design; import over your own background, with black lettering intended for light surfaces. Font files are referenced from Windows and not redistributed.\n\nThe nine-second sax-abstract clip is a replaceable original abstract insert, not a human performance or a recording-verification asset. The internal shot list identifies it explicitly.\n\nEditable source: `source/showcase_motion.py`; use --mode render --out <new-output-folder> --ffmpeg <ffmpeg.exe> --ffprobe <ffprobe.exe>. Dependencies: Python, NumPy and Pillow. Never overwrite the original reference film.\n", encoding="utf-8")


def docs(a):
    out = a.out / "scripts"
    out.mkdir(parents=True, exist_ok=True)
    for key, prompt in PROMPTS.items():
        (out / f"{key}.txt").write_text(prompt + "\n", encoding="utf-8")
    dump(out / "shot-list.json", [{"id":r[0],"start":r[1],"end":r[2],"voice_en":r[3],"voice_zh":r[4],"action_en":r[5],"action_zh":r[6],"edit_en":r[7]} for r in SHOTS])
    titles = [("Opening", "开场",0,18),("D1 · Two musical ideas", "D1 · 双模型生成",18,66),("D1 · SCNet separation", "D1 · SCNet 分离",66,94),("D2 · Chord analysis", "D2 · 和弦分析",94,122),("D2 · Beat and Warp", "D2 · 节拍与 Warp",122,142),("D3 · Piano to MIDI", "D3 · 钢琴转 MIDI",142,168),("D4 · Making music", "D4 · 原创工程制作",168,228),("Closing", "结尾",228,240)]
    for zh in (False,True):
        title = "E-musician 四分钟影片脚本——中文对照稿" if zh else "E-musician · 4-minute investor film — English production script"
        s = f"# {title}\n\n日期：2026-11-22。总时长 **04:00 / 240 秒**，16:9、1920×1080、30fps；镜号、操作与英文稿逐一对应。\n\n" if zh else f"# {title}\n\nDate: 2026-11-22. Master: **04:00 / 240 seconds**, 16:9, 1920×1080, 30fps. English DAW interface throughout. The timings below are final edit time, not processing duration.\n\n"
        s += ("## 时间分配\n\n" if zh else "## Timing\n\n")
        s += "| 章节 | 时间 | 时长 |\n|---|---|---|\n" if zh else "| Section | Time | Duration |\n|---|---|---|\n"
        for en,cn,lo,hi in titles:s += f"| {cn if zh else en} | {tc(lo)}–{tc(hi)} | {hi-lo}s |\n"
        s += "\n" + ("## 拍摄前准备\n\n" if zh else "## Preparation\n\n")
        if zh:
            s += "- 前三个工程使用独立 showcase-v1 英文版：New ideas、New Light、Tea for Two；最后一段用 0.13.6 中的 test drive 拍摄副本。不要覆盖原工程。\n- 拍前完整走一遍 Preview → Apply → Undo/Redo；检查三工程可重置、来源选择正确、原曲与候选不叠放。\n- 录屏至少 1080p30；若需要局部放大，建议更高分辨率录屏。系统/DAW 输出与麦克风分开录，先回看 10 秒测试。ASIO 能听见不代表录屏有声音。\n- Keyscape、BM-VOID、BM-HUSTLE 预加载；拍摄中不要重新扫描插件。录音输入/Arm/Monitor 由使用者预先检查，确保仅目标轨录制。\n- 清理通知、桌面弹窗和悬浮宠物；保留清晰指针和真实按钮状态。不要露出 API 密钥、SSH 或个人文件。\n- 六个背景仅在各章起始占 0.6–1 秒，已包含在段落时长内，不另加时长。开场动效 8 秒，其余 10 秒为产品预告；片尾 12 秒。\n- 旁白使用本机 Microsoft Zira 的离线合成稿；英文 WAV、分镜 WAV、英文 SRT 和中文对照 SRT 均可替换。纯试听镜头不叠旁白或额外 BGM。\n\n"
        else:
            s += "- Use the isolated showcase-v1 English build for New ideas, New Light and Tea for Two. Film the final production chapter in 0.13.6 from a copy of test drive, preserving the original.\n- Rehearse Preview → Apply → Undo/Redo, project reset, source selection, and no doubled playback before recording.\n- Capture at least 1080p30; higher-resolution capture gives room for crops. Record DAW output and microphone separately. Review a 10-second test: hearing ASIO output does not prove the screen recorder captured it.\n- Preload Keyscape, BM-VOID and BM-HUSTLE. Do not scan plug-ins during the take. Configure the recording input, Arm and Monitor beforehand; only the intended track may record.\n- Hide notifications, desktop overlays and floating pets. Keep real cursor/control states. Never reveal API keys, SSH credentials or personal files.\n- Six chapter backgrounds occupy 0.6–1.0 seconds within the assigned slots. The eight-second opener is followed by ten seconds of actual UI preview; the closer is twelve seconds.\n- Offline Microsoft Zira narration, per-shot WAVs, the 240-second voice track, English SRT and aligned Chinese SRT are editable. Keep marked audition shots free of voice and extra BGM.\n\n"
        s += "## " + ("逐镜脚本" if zh else "Shot-by-shot script") + "\n\n"
        for r in SHOTS:
            id,lo,hi,en,cn,op,opcn,edit=r
            s += f"### {id} · {tc(lo)}–{tc(hi)}\n\n"
            voice = cn if zh else en
            s += f"**{'旁白' if zh else 'Voice-over'}:** {voice or ('— 纯试听，无旁白 —' if zh else '— Audition only; no narration —')}\n\n"
            s += f"**{'操作与画面' if zh else 'Action / picture'}:** {opcn if zh else op}\n\n"
            s += f"**{'剪辑与声音' if zh else 'Edit / sound'}:** {EDITS_ZH[id] if zh else edit}\n\n"
        s += "## " + ("可复制提示词" if zh else "Copy-ready prompts") + "\n\n"
        for key,prompt in PROMPTS.items():s += f"### {key}\n\n```text\n{prompt}\n```\n\n"
        s += "## " + ("Demo4 精确对齐与验收" if zh else "Demo4 alignment and acceptance") + "\n\n"
        if zh:
            s += "- test drive：160 BPM、4/4、九轨，工程零秒对应成片 02:48。Sax 在工程 13.03125 秒（成片约 03:01.031）进入，至约 47.973 秒结束；来源截取偏移为 13.367045 秒。请用同一段音频的瞬态校准演奏者视频，不能仅按文件起点对齐。\n- sax_player 现有保存状态没有指定音频输入；拍摄前必须设置。新录音使用工程副本与独立录音目标，避免覆盖已有素材或把原 sax 与新录音叠加。没有真实录入时，不可将播放画面配成‘刚刚录下’的结果。\n- 当前缺少演奏者视频路径，先用九秒抽象萨克斯动效作为可替换视觉插入，它不假装真人实录。左侧真正录音过程仍由使用者拍摄。\n- Sampler 仅在工程 15–18 秒触发；脚本后续镜头讲的是装置能力。RACK 在 18.75–44.413 秒发声，有四个已装采样垫。\n- test drive.wav 虽有 62 秒，但保存时间早于工程。拍摄时从当前工程录一条连续输出，不直接把旧导出当作最终声音。若录了新 Sax，成片声音必须包含同一次真实录音。\n- 按镜号验证：P1/P2 可分别 Preview/Apply，删除只影响 YuE2；P3 得到四轨且来源不改名；P4 由 Analysis 面板加入真实和弦轨；P5 源 125→工程 120 BPM 且保音高；P6 为已有 TransKun 132 音符结果，钢琴试听须来自 MIDI+插件；D4 必须实际录音。\n\n"
        else:
            s += "- test drive is a nine-track, 160 BPM, 4/4 project. Its zero corresponds to film 02:48. Sax enters at project 13.03125 seconds (film about 03:01.031), ending around 47.973 seconds; source offset is 13.367045 seconds. Align performer footage by matching audio transients, not file start time.\n- The saved sax_player track has no audio input assigned. Configure one before filming. Use a filming copy and a separate record target to avoid overwriting or doubling the existing sax clip. Playback alone is not evidence that a new performance has been recorded.\n- The performer-video path is currently unavailable. The nine-second abstract sax insert is a replaceable visual asset, not a person or a live-performance claim. Genuine recording footage on the DAW side is still supplied by the user.\n- Sampler triggers only at project 15–18 seconds; its later shot explains the device controls. RACK sounds at 18.75–44.413 seconds and contains four populated pads.\n- test drive.wav lasts 62 seconds but predates the saved project. Record one continuous output from the current project for the film. If a new sax take is recorded, use that same take in the soundtrack.\n- Check by shot: P1/P2 each Preview/Apply; delete only YuE2. P3 returns four tracks without renaming the source. P4 is accepted through Analysis. P5 maps 125 BPM source to the 120 BPM project while preserving pitch. P6 uses the existing 132-note TransKun result; piano audition must be MIDI plus the plug-in. D4 requires an actual recording.\n\n"
        s += "## " + ("内部制作事实与范围" if zh else "Internal production facts and boundaries") + "\n\n"
        s += ("前三章拍摄版复用已存在的模型产物，并设置可重复的等待节奏；本次不连接 SSH、不调用 API、不运行新的云端推理。界面保持干净，脚本不将等待演出称为真实推理耗时，不将既有结果说成此次重新生成。生成只称短片段，不承诺完整 64 小节或严格段落。质量、复杂自然语言理解与通用性能不由这套固定流程证明。来源文件/哈希由素材清单记录。\n\n本交付是可录制程序配套的拍摄与剪辑素材包，不包含最终合成的四分钟实录视频。New Light / Tea for Two 的曲名与表演来源保留在内部资料中，公开分发前由使用者确认适当的使用范围；不会把这些音乐称为原创或随开源代码分发。\n" if zh else "The first three project workflows reuse existing model artifacts with repeatable presentation waits. This production makes no SSH connection, API call or new cloud inference. The UI stays clean; narration does not represent the staged wait as measured inference latency or claim the outputs were regenerated during filming. Generation is described as a short excerpt, not a complete 64-bar song or guaranteed structure. This fixed workflow does not establish model quality, broad natural-language reliability or general performance. The asset manifest records provenance and hashes.\n\nThis is a filming/editing kit, not the final four-minute screen-recorded film. New Light / Tea for Two source credits remain in internal materials; the user confirms the intended public-use scope. These recordings are not described as original compositions or redistributed as part of the open-source code.\n")
        name = f"2026-11-22-showcase-script-{'zh' if zh else 'en'}.md"
        (out / name).write_text(s, encoding="utf-8")
        if (ROOT / "docs/demo").exists():
            (ROOT / "docs/demo" / name).write_text(s, encoding="utf-8")
    (out / "voice-en.txt").write_text("\n\n".join(f"[{r[0]} {tc(r[1])}]\n{r[3]}" for r in SHOTS if r[3]),encoding="utf-8")
    (out / "voice-zh.txt").write_text("\n\n".join(f"[{r[0]} {tc(r[1])}]\n{r[4]}" for r in SHOTS if r[4]),encoding="utf-8")
    editable=a.out/'motion/source';editable.mkdir(parents=True,exist_ok=True)
    assembler=ROOT/'scripts/showcase_assemble.py'
    if assembler.exists() and assembler.resolve()!=(editable/'showcase_assemble.py').resolve():shutil.copyfile(assembler,editable/'showcase_assemble.py')
    howto=ROOT/'docs/demo/2026-11-22-showcase-editing.md'
    if howto.exists():shutil.copyfile(howto,out/'ASSEMBLY.md')
    print(f"Wrote synchronized scripts ({len(SHOTS)} shots, 240 seconds)",flush=True)


def tts(a):
    out = a.out / "narration"
    for c in ("raw", "clips", "logs"):(out/c).mkdir(parents=True,exist_ok=True)
    entries=[{"id":r[0],"text":r[3],"start":r[1]+.2,"slot_end":r[2]-.2} for r in SHOTS if r[3]]
    dump(out/"tts-input.json", entries)
    ps = r'''param([string]$InputJson,[string]$OutputDir)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice('Microsoft Zira Desktop')
$synth.Rate = 0
$synth.Volume = 100
$items = Get-Content -LiteralPath $InputJson -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($item in $items) {
  $target = Join-Path $OutputDir ($item.id + '.wav')
  $synth.SetOutputToWaveFile($target)
  $synth.Speak($item.text)
  $synth.SetOutputToNull()
  Write-Output $item.id
}
$synth.Dispose()
'''
    script=out/"speak-local.ps1";script.write_text(ps,encoding="utf-8-sig")
    records=[run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",script,"-InputJson",out/"tts-input.json","-OutputDir",out/"raw"],out/"logs/synthesis.log")]
    final=np.zeros(240*48000,dtype=np.float32)
    aligned=[]
    for e in entries:
        raw=out/"raw"/(e['id']+'.wav')
        with wave.open(str(raw)) as w:duration=w.getnframes()/w.getframerate()
        available=e['slot_end']-e['start']
        speed=max(1.0,duration/available)
        if speed>1.22:raise RuntimeError(f"Narration too long for {e['id']}: {duration:.2f}/{available:.2f}; revise text")
        dest=out/"clips"/(e['id']+'.wav')
        records.append(run([a.ffmpeg,"-y","-hide_banner","-loglevel","error","-i",raw,"-af",f"atempo={speed:.7f},loudnorm=I=-18:TP=-2:LRA=7","-ar","48000","-ac","1","-c:a","pcm_s16le",dest],out/"logs"/(e['id']+'.log')))
        with wave.open(str(dest)) as w:audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
        start=round(e['start']*48000);end=start+len(audio)
        assert end<=round(e['slot_end']*48000)+480, e['id']
        final[start:end]+=audio
        aligned.append({**e,"end":end/48000,"raw_seconds":duration,"speed":speed,"sha256":sha(dest)})
    pcm=(np.clip(final,-1,1)*32767).astype('<i2')
    with wave.open(str(out/"voice-en-240s-48k.wav"),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(pcm.tobytes())
    dump(out/"NARRATION-MANIFEST.json",{"created":stamp(),"voice":"Microsoft Zira Desktop","method":"Windows System.Speech local synthesis; no network","track_seconds":240,"sample_rate":48000,"entries":aligned,"records":records})
    write_captions(out, aligned)
    print(f"Synthesized {len(aligned)} voice clips and measured captions",flush=True)


def caption_groups(text, zh):
    """Balance cues rather than leaving a tiny one-word final caption."""
    maximum = 44 if zh else 80
    remaining=text;groups=[]
    count=math.ceil(len(text)/maximum)
    while count>1:
        target=len(remaining)/count
        candidates=range(max(1,round(target)-12),min(len(remaining)-1,round(target)+13)) if zh else [i for i,c in enumerate(remaining) if c==' ']
        cut=min(candidates,key=lambda i:abs(i-target)-(4 if remaining[i-1] in '.,;!?，。；！？' else 0))
        groups.append(remaining[:cut].strip());remaining=remaining[cut:].strip();count-=1
    groups.append(remaining)
    return ['\n'.join(textwrap.wrap(g,width=23 if zh else 44,break_long_words=zh,break_on_hyphens=False)) for g in groups]


def caption_lines(text):
    if len(text)<=44:return text
    splits=[i for i,c in enumerate(text) if c==' ' and i<=44 and len(text)-i-1<=44]
    if not splits:return '\n'.join(textwrap.wrap(text,width=44))
    cut=min(splits,key=lambda i:abs(i-len(text)/2))
    return text[:cut]+'\n'+text[cut+1:]


def write_captions(out, aligned):
    srts={False:[],True:[]}
    for zh in (False,True):
        count=0
        for e in aligned:
            row=next(r for r in SHOTS if r[0]==e['id']);words=row[4] if zh else e['text']
            # Cue splits are estimated inside the measured utterance, not claimed word alignment.
            pairs=caption_groups(words,zh) if zh or e['id'] not in CAPTION_CLAUSES else [caption_lines(g) for g in CAPTION_CLAUSES[e['id']]]
            total=sum(len(x) for x in pairs);cursor=e['start']
            for i,txt in enumerate(pairs):
                end=e['end'] if i==len(pairs)-1 else cursor+(e['end']-e['start'])*len(txt)/total
                count+=1;srts[zh].append(f"{count}\n{srt_time(cursor)} --> {srt_time(end)}\n{txt}\n")
                cursor=end
        (out/f"voice-{'zh' if zh else 'en'}.srt").write_text("\n".join(srts[zh]),encoding="utf-8-sig")


def captions(a):
    out=a.out/'narration'
    manifest=json.loads((out/'NARRATION-MANIFEST.json').read_text())
    write_captions(out,manifest['entries'])
    print('Balanced English/Chinese cues updated within measured voice windows')


def verify(a):
    checks=[];out=a.out/"motion";report=a.out/"VALIDATION.json"
    last=0
    for r in SHOTS:
        assert r[1]==last and r[2]>r[1],r[0]
        last=r[2]
    assert last==240
    for id,clauses in CAPTION_CLAUSES.items():
        assert ' '.join(clauses)==next(r[3] for r in SHOTS if r[0]==id),id
    script_en=(a.out/'scripts/2026-11-22-showcase-script-en.md').read_text()
    script_zh=(a.out/'scripts/2026-11-22-showcase-script-zh.md').read_text()
    assert not re.search(r'[\u4e00-\u9fff]',script_en),'Chinese text in English-only script'
    for r in SHOTS:assert f'### {r[0]} · ' in script_en and f'### {r[0]} · ' in script_zh
    caption_checks=[]
    for lang in ('en','zh'):
        entries=(a.out/f'narration/voice-{lang}.srt').read_text(encoding='utf-8-sig').strip().split('\n\n')
        previous=0;minimum=999
        def parse_time(t):
            h,m,s,ms=map(int,re.split('[:,]',t));return h*3600+m*60+s+ms/1000
        for i,entry in enumerate(entries,1):
            lines=entry.splitlines();assert int(lines[0])==i
            lo,hi=[parse_time(t) for t in lines[1].split(' --> ')]
            assert lo>=previous and hi>lo and hi<=240
            assert len(lines[2:])<=2
            previous=hi;minimum=min(minimum,hi-lo)
        assert minimum>=1.0,(lang,minimum)
        caption_checks.append({'language':lang,'cues':len(entries),'minimum_seconds':minimum,'no_overlap':True,'maximum_lines':2,'note':'Clause timing is estimated inside measured utterance boundaries; no word-level alignment claim'})
    decoded_thumbs=[]
    for file in sorted(out.glob("*.mp4"))+sorted(out.glob("*.webm")):
        raw=subprocess.check_output([str(a.ffprobe),"-v","error","-count_frames","-show_entries","stream=codec_name,width,height,pix_fmt,avg_frame_rate,nb_read_frames:stream_tags=alpha_mode:format=duration","-of","json",str(file)])
        data=json.loads(raw);stream=data['streams'][0]
        assert (stream['width'],stream['height'],stream['avg_frame_rate'])==(1920,1080,'30/1')
        duration=float(data['format']['duration'])
        expected=8 if file.name.startswith('opener') else 12 if file.name.startswith('closer') else 9 if file.name.startswith('sax') else 6
        assert abs(duration-expected)<.05,file
        assert int(stream['nb_read_frames'])==expected*30,file
        run([a.ffmpeg,"-v","error","-i",file,"-f","null","-"],out/"logs"/(file.stem+'.decode.log'))
        decoder=["-c:v","libvpx-vp9"] if file.suffix=='.webm' else []
        b=subprocess.check_output([str(a.ffmpeg),"-v","error",*decoder,"-ss","3","-i",str(file),"-frames:v","1","-f","image2pipe","-vcodec","png","-"])
        decoded=Image.open(io.BytesIO(b)).convert('RGBA')
        decoded.save(out/'stills'/(file.stem+'-encoded.png'))
        if file.suffix=='.webm':
            backing=Image.new('RGBA',decoded.size,(220,228,232,255));backing.alpha_composite(decoded);decoded=backing
        thumb=decoded.convert('RGB').resize((480,270));ImageDraw.Draw(thumb).text((12,12),file.stem,fill='white',stroke_width=2,stroke_fill='black');decoded_thumbs.append(thumb)
        if file.suffix=='.webm':
            assert stream.get('tags',{}).get('alpha_mode')=='1'
            b=subprocess.check_output([str(a.ffmpeg),"-v","error","-c:v","libvpx-vp9","-ss","3","-i",str(file),"-frames:v","1","-f","image2pipe","-vcodec","png","-"])
            im=Image.open(io.BytesIO(b)).convert('RGBA');ex=im.getchannel('A').getextrema();assert ex[0]==0 and ex[1]==255
        checks.append({"file":file.name,"probe":data,"sha256":sha(file),"decoded":True})
    sheet=Image.new('RGB',(1440,270*math.ceil(len(decoded_thumbs)/3)), '#172025')
    for i,im in enumerate(decoded_thumbs):sheet.paste(im,((i%3)*480,(i//3)*270))
    sheet.save(out/'stills/encoded-contact-sheet.png')
    with wave.open(str(a.out/"narration/voice-en-240s-48k.wav")) as w:
        assert w.getnframes()==240*48000 and w.getframerate()==48000
        audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')
    assert np.max(np.abs(audio.astype(np.int32)))<32767
    workspace=a.out/'workspace/manifest.json'
    if workspace.exists():
        scenarios=json.loads(workspace.read_text())['scenarios']
        assert [PROMPTS[k] for k in PROMPTS]==[s['prompts'][0] for s in scenarios], 'Script prompts differ from executable scenarios'
    for r in SHOTS:
        if not r[3]:assert np.count_nonzero(audio[int(r[1]*48000):int(r[2]*48000)])==0
    # Cyclic endpoints are identical analytically, with no time-varying random noise.
    motion=Motion(resolve_logo())
    seams=[]
    for name,_,_ in CHAPTERS:
        first=np.asarray(motion.render(name,0),dtype=np.int16)
        last=np.asarray(motion.render(name,6-1/FPS),dtype=np.int16)
        cyclic=np.asarray(motion.render(name,6),dtype=np.int16)
        assert np.max(np.abs(first-cyclic))<=1
        seams.append({"name":name,"last_to_first_mean_abs":float(np.mean(np.abs(first-last))),"full_period_max_abs":int(np.max(np.abs(first-cyclic)))})
    dump(report,{"created":stamp(),"status":"passed","timeline_seconds":240,"shot_count":len(SHOTS),"motion":checks,"seams":seams,"voice_peak":int(np.max(np.abs(audio.astype(np.int32)))),"silent_audition_slots_verified":True,"captions":caption_checks,"exact_scenario_prompt_alignment":True,"note":"Technical decode/timing checks; human listening and final DAW screen recording remain separate acceptance."})
    print(f"Verified 11 motion assets, seamless cycles, voice duration and silent audition slots: {report}",flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--ffmpeg',type=Path,required=True);p.add_argument('--ffprobe',type=Path,required=True);p.add_argument('--mode',choices=('docs','render','tts','captions','verify','all'),default='all');p.add_argument('--only',help='Re-render just one named motion asset; preserves other manifest entries');a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    for name,fn in [('docs',docs),('render',render),('tts',tts),('captions',captions),('verify',verify)]:
        if a.mode in (name,'all'):fn(a)


if __name__=='__main__':
    main()
