# Showcase v1：录屏与动效装配

这份说明对应两个逐镜稿和固定 240 秒时间轴。装配器只使用清单里提供的真实本地截图、视频与声音；没有画面时会报错，不会生成 DAW 界面、按钮状态、录音波形或播放头。

## 录制素材与编辑清单

- 英文逐镜稿：`2026-11-22-showcase-script-en.md`；中文对应稿：`2026-11-22-showcase-script-zh.md`。
- 素材包根目录：`E:/MusicAgent&DAW/demo-video/showcase-v1`。
- `motion/`：六个无字背景、8 秒片头、12 秒片尾、两份透明品牌叠层、9 秒抽象萨克斯插镜。`preview.html` 可逐个播放检查。
- `narration/`：25 段本机 Microsoft Zira 英文配音、带留白的 240 秒总 WAV、英文与中文 SRT。字幕根据实际合成语音时长定位；仍需人工检查发音与阅读速度。
- `scripts/shot-map-template.json`：31 镜头的可替换清单。每镜含时间、实际旁白时间窗、旁白结束后可留给音乐的秒数，以及画面要求。`media: null` 表示需要实拍素材。

模板中的 `kind: image` 仅是截图镜头的默认输入方式，不意味着这段操作已经录像。涉及 Preview、Apply、删除轨、和弦应用或录音等关键操作时，优先用连续录屏；截图可用于概览、装置特写和讲解插镜。最终装配报告会保留哪些镜头是静态图片。

## 清单字段

每个 `shots` 项保留原有 `id/start/end`，不得通过删镜头掩盖缺失功能。

```json
{
  "id": "G01",
  "start": 18,
  "end": 25,
  "media": "E:/recordings/G01.mp4",
  "kind": "video",
  "source_in": 2.5,
  "playback_rate": 1,
  "crop": null,
  "zoom": [1, 1.035],
  "focus_start": [0.5, 0.5],
  "focus_end": [0.65, 0.5],
  "allow_last_frame_hold": false,
  "background_intro": {
    "media": "E:/MusicAgent&DAW/demo-video/showcase-v1/motion/chapter-01-generation-1080p30.mp4",
    "duration": 0.6
  },
  "chapter_title": null
}
```

`source_in` 是源视频入点。`playback_rate` 只用于实际录屏的速度调整，不能用来宣称模型速度。`crop` 是源图像的 `[x,y,width,height]`；`zoom` 与 `focus_*` 控制轻微推近与画面中心移动，不会修改界面内容。`background_intro` 用 0.6 秒无字背景替换本镜头开头的画面，然后接回同一时间点的录屏，避免把声画推迟 0.6 秒；拍摄时将关键点击安排在这之后。它不会增加总时长。`chapter_title` 可选，默认没有文字叠层。短视频若需末帧停留，必须明确填写 `allow_last_frame_hold: true`。

音频在顶层 `audio` 单独指定，录屏里的声音不会被默默混入。例：

```json
{
  "media": "E:/recordings/ACE-preview.wav",
  "timeline_start": 49,
  "source_in": 6,
  "duration": 6,
  "gain_db": 0,
  "fade_in": 0.02,
  "fade_out": 0.02
}
```

加入 YuE2、ACE、四分轨逐层叠加、New Light、Warp、钢琴 MIDI 的真实试听录音，以及 Demo4 从头连续的 DAW 输出。片头和片尾 BGM 另加条目。带旁白的音乐适当降低增益，纯试听段保持可辨；装配器只进行显式增益、淡入淡出和最终峰值限制，不会自动重混工程。Demo4 的持续输出不可用一个旧导出冒充新录音。

## 执行

先复制模板为 `shot-map.json`，填入真实素材。用同一清单先检查，再输出到新文件：

```powershell
python scripts/showcase_assemble.py --map "E:/MusicAgent&DAW/demo-video/showcase-v1/scripts/shot-map.json" --output "E:/MusicAgent&DAW/demo-video/showcase-v1/E-musician-showcase-240s.mp4" --ffmpeg "E:/SUMIN/ABC_Ocean/_tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe" --ffprobe "E:/Users/28712/AppData/Local/Programs/Audio Jam/lib/win32/ffprobe.exe" --check-only
```

检查通过后去掉 `--check-only`。已有成片不会被覆盖；需要明确添加 `--overwrite` 或改用新文件名。没有音乐映射时默认拒绝输出；`--allow-voice-only` 仅用于内部声音未齐的剪辑检查。

需要同时导出无旁白版时，追加 `--no-narration-output "E:/MusicAgent&DAW/demo-video/showcase-v1/E-musician-showcase-music-only-240s.mp4"`。它直接复制同一条已编码画面，只重新混合 `audio` 中的真实声音，不重新渲染 31 个镜头，也不加入旁白或字幕流。所有试听入点、长度和源时钟保留；可选的 `gain_envelope` 旁白压低会移除。各段仍沿用 `gain_db`，或显式填写 `no_narration_gain_db` 作无旁白版专用增益。对应记录为 `*-work/NO-NARRATION-RESULT.json`，检查 240 秒、7200 帧、完整解码，以及与主版画面流的哈希一致。

片段、中间画面、命令日志、输入哈希、镜头类型与最终技术检查都保留在输出文件旁的 `*-work/`。技术通过表示解码、时长和结构正确，不代替完整观看、字幕阅读、听感检查、真实操作验收或推理能力验证。必须在交付记录里保留这一区分。

## 最终检查

当前首剪使用两类真实来源：`captures/workflow-final` 的实际操作视频，以及 `captures/demo4` 的实际静态界面。静态界面的轻微推近或拼接属于剪辑，不能据此宣称播放头在走、按钮被点击或麦克风刚录入。`captures/editorial/D403-sax-split-1080p30.mp4` 左侧是已有萨克斯轨裁图，右侧是原创抽象图形；最终需要展示录音过程时，替换为同一次真实输入、波形增长和用户演奏者视频，并使用该次录音的声音。不要为静态界面补画录音波形或播放指示。D402 已采用本工程 EP 轨真实 Keyscape 编辑器，音色为 Rhodes - LA Custom Suitcase；不要与 Tea for Two 的钢琴音色镜头混用。

1. 00:00–04:00 连续，无漏镜、黑帧或多余尾帧。六个无字转场均包含在章节预算内。
2. 关键操作采用真实连续录屏；鼠标、按钮、结果与声音相符。生成等待仅作剪辑节奏，不标为实际延迟。
3. YuE2 与 ACE 各留六秒纯试听；四轨逐层叠加没有原曲加倍；钢琴转 MIDI 试听确实来自 MIDI 和插件。
4. Demo4 的音乐贯穿整段，真实录音与分屏同段演奏对齐。抽象萨克斯插镜不得描述为真人演奏素材。
5. 开源网址可读，片尾至少静止五秒；英/中字幕镜号和语义一致，不能遮住关键控件。
