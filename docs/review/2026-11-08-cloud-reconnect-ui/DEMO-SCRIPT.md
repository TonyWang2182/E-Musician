# E-musician demo — English interface, 7 minutes 50 seconds

2026-11-08。用途：可直接照拍的产品演示脚本。操作说明用中文，实际界面、字幕、输入给 Agent 的指令与旁白用英文。以下为拍摄计划，不是本轮新主机验收结论；只有真实运行成功的镜头才进入成片。

## 拍摄前准备

- 使用本轮最终交付入口，先在 Settings → Language 选择 English，重开 Agent 侧栏确认语言一致；画面里不出现终端、连接密码或密钥配置。
- 建立独立演示工程 `E-musician Demo`，默认120 BPM / 4/4。准备一份8小节的可循环小工程：`Drums`、`Sampler Keys`、`Reference Audio`、`Piano Reference`。另存副本，避免拍摄中覆盖原作品。
- 原生装置来自 Library：Sampler、Drum Rack、EQ Eight、Compressor、Delay、Reverb、Auto Filter。提前给五个效果器准备可听到差别但不会突然变响的设置；不要现场连续加载未测的第三方大音源。
- Rack素材可用 `E:/E-musician/test-projects/test5-sampler&rack/`：01-kick→36、02-snare→38、03-closed-hihat→42、04-open-hihat→46；05-clap→39、06-tom→41。这些位置是本演示的映射，文件名不是固定引擎规则。Sampler可用07-piano-C4或08-flute-C4，Root MIDI note=60；使用MIDI编号避免八度命名差异。
- 模型测试的现有原文件是 `E:/E-musician/test-projects/test9-newlight/New Light()/New Light.mp3` 和 `E:/E-musician/test-projects/test9-newlight/Keyboard.mp3`。公开成片选择自录或允许展示的音乐；用相同任务流程替换参考曲即可。录屏包含真实声音，模型结果不要用绘制波形或另一首歌代替。
- 云端模型分别先通过 [MODEL-TESTS](MODEL-TESTS.md)。保存真实生成/分析结果用于补拍；补拍调用 `Recent analyses` / `Recent generations` 时，字幕标明 `Previously generated result`。
- 1920×1080或更高分辨率，界面文字保持可读，鼠标移动有停顿。每次A/B或声部试听留2–4秒纯声音。耗时过程可剪短，但加字幕 `Processing time shortened`；不要把剪辑后的几秒当推理速度宣传。
- Audio/MIDI设备与输入事先确认；演示录音时只让目标轨Arm与Monitor生效。模型运行时的播放流畅性可以真实拍摄，但没有测量不能配上“zero latency”或“never glitches”的文案。

## 主片分镜

| 时间 | 屏幕操作与画面 | English voice-over / on-screen text |
|---|---|---|
| 00:00–00:20 | 展示树乐师Logo和完整工作区，播放已有8小节工程。短暂停留在顶部Transport、左侧Library、下栏装置、右侧Agent开关。 | **“This is E-musician: a desktop music workspace for recording, editing, native sound processing, and model-assisted creation. Your arrangement stays at the centre of the workflow.”** 字幕：`Record · Edit · Analyze · Create`。 |
| 00:20–00:50 | 停止。拖动、裁剪一个音频片段；右键轨头选择Track colour。缩放标尺，按Ctrl+4关闭/开启吸附，拍到虚线/实线变化。双击MIDI片段，展开卷帘，画两枚音符并调整长度，再返回。 | **“Audio clips and MIDI notes share a precise timeline. I can colour tracks, edit notes, and switch snapping with one shortcut. The grid becomes more detailed as I zoom in.”** 字幕：`Ctrl+4 — Toggle snap`。不必为了展示1/16384把画面放大到不可读。 |
| 00:50–01:30 | 选Drums，下栏打开Drum Rack。先单击一个鼓垫主体选中它，停留真实波形；再点击鼓垫右下角三角形试听，依次演示三种采样。也可双击鼓垫主体试听；普通单击主体只负责选择，不发声。切至已准备的录音输入，启用预备拍，Arm目标轨，录入4–8秒MIDI鼓点，停止、解除Arm、回放并看卷帘。 | **“The Drum Rack gives each pad its own sample and controls. I can audition a sound without starting the timeline, then record a pattern and edit the recorded notes.”** 录音与回放各留约3秒原声。 |
| 01:30–02:00 | 选Sampler Keys，打开Sampler，试听样本；拖动真实波形起止，调Attack/Release，切gate/one-shot。用键盘或已有MIDI片段听变化；保持Root=60。 | **“Sampler turns an audio file into a playable instrument. I can trim the sample, set its root note, and shape the envelope. Gate follows note-off; one-shot plays through the sample.”** |
| 02:00–02:55 | 播放循环。用下栏装置链左右切换五个效果器：EQ拖一个节点并看频谱；Compressor调整threshold并看GR；Delay改delay/feedback；Reverb改decay/dry-wet；Auto Filter扫cutoff。每个停留约8秒，最后一次Undo恢复最近调整。 | **“The native effects use the same control language. EQ shapes the spectrum, compression controls dynamics, delay adds repeats, and reverb adds space. Auto Filter adds movement. Changes can be auditioned while dragging, then undone as one edit.”** 每个镜头字幕只放装置名；频谱与GR必须来自真实播放，包络/滤波曲线不称作音频测量。 |
| 02:55–03:30 | 停止。选整条Drums轨并打开Agent，Scope为Selection。发送下面的压缩器指令A，拍到目标轨/装置和参数前后值；点 **Apply changes**，打开Compressor核对，再Undo。 | **“The assistant works with the selected track and its actual devices. It proposes supported changes for review. I stay in control: apply the plan, inspect the result, or undo it.”** 字幕：`Select → Review → Apply → Undo`。不要把自然语言响应剪成固定确定性速度。 |
| 03:30–04:05 | 选Reference Audio，Analyze → Separate，执行位置Cloud、模型scnet；Options设8–20秒范围，Analyze。等待段压缩并标注；选vocals/drums候选，Listen短试听；点Add tracks，展示四条对齐新音轨和保留的原片段。 | **“Separation creates four editable stem candidates: vocals, drums, bass, and other. I can listen before adding them. The original recording stays in place.”** 字幕：`SCNet · Cloud · 4 stems`。不能展示成主唱/和声/吉他/钢琴八分轨能力。 |
| 04:05–04:45 | 选Piano Reference，Analyze → MIDI → Cloud / transkun，Analyze；候选→Add MIDI track，打开卷帘并配置已验证乐器试听。后半切到事先真实跑出的muscriptor多乐器结果，显示实际轨数/乐器，不虚构未检测到的轨。 | **“TransKun converts piano audio into editable MIDI, including pedal events when the model returns them. MuScriptor provides another route for multiple instrument parts. These are estimates to review, and MIDI needs an instrument for playback.”** 字幕依次：`TransKun — Piano to MIDI`、`MuScriptor — Instrument tracks`；补拍结果标记Previously generated result。 |
| 04:45–05:10 | Reference Audio → Chords → Cloud / chordmini，Analyze；看标签→Add chord track。展示编曲区和弦轨，双击一个和弦，核对起止/名称，必要时修正。 | **“Chord analysis puts readable harmony on the arrangement. I can review the labels and correct them against the recording. The chord track remains editable.”** 字幕：`ChordMini — Editable chord estimates`。不宣称任意爵士和弦均正确。 |
| 05:10–05:45 | 选择有清晰节奏的片段，Beats → Local →已登记的Beat This!，Analyze；检查BPM、拍号、First / s，必要时半倍/倍倍修正；Align audio。随后Source里打开Warp on，核对Source BPM，设置Target BPM或Follow tempo，再Apply，对比前后。 | **“Beat analysis helps locate the pulse and the first bar. I review the tempo before aligning the clip. Warp then changes its duration while preserving pitch, with the original audio kept intact.”** 字幕：`Review BPM → Align → Warp`；固定比例拉伸不称作可变Warp标记或无损音质。 |
| 05:45–06:20 | Score → Cloud / sheetsage2，Analyze；依次切Notes、Chords、Beats、Sections，展示实际有输出的分项；Add score后切Saved score，并显示卷帘/和弦轨。 | **“Score analysis brings notes, chords, and available timing or structure estimates into one review. I can inspect each component before adding it. Accepting the score does not automatically change the project tempo.”** 字幕：`SheetSage2 — Notes · Chords · Beats · Sections`。这里是现有图形/列表与卷帘视图，不配不存在的五线谱走带镜头；空分项如实展示。 |
| 06:20–07:20 | add... → Generate music…，先选ACE-Step 1.5 XL，Seconds=12，输入提示词B，Generate→Preview→Add track。再通过Agent发送提示词C明确选择YuE2；完成后试听、核对实际长度与截断状态，再经确认加入。两次运行都展示真实模型名。 | **“I can also generate a new musical idea with ACE-Step or YuE2. The request uses the project context, and the result comes back as a candidate. I preview it before adding a new audio track. Generation length and musical details still need a listening check.”** 字幕：`Generate → Preview → Add track`。YuE2用“about 12 seconds”，若截断不掩去提示。 |
| 07:20–07:50 | Ctrl+S保存。做一次可逆小编辑，点击窗口关闭，展示新样式Save changes?与Save/Discard/Cancel，点Cancel保持工程；再保存并重开已保存工程，播放刚导入的一个结果。结尾回完整工作区。 | **“Manual editing, native devices, and model-assisted tasks all return to the same project. Accepted results are saved locally, so I can keep editing them even when the cloud is disconnected.”** 只有完成真实断云重开测试后才保留最后一句。收尾字幕：`E-musician — Your music, one workspace.` |

## 屏幕输入的英文原文

### A — Agent操作现有原生装置

前置：选中整条Drums轨；该轨已有一个Compressor。Scope=Selection。

```text
On the selected track, set the existing Compressor threshold to -18 dB and its ratio to 3:1. Leave all other settings unchanged. Show me the changes before applying them.
```

若拍摄素材没有Compressor，先手动添加并验证，避免指令里暗含不存在的装置。若模型提出不相关步骤，拒绝该方案并保留问题记录，不把错误执行当成功。

### B — 手动ACE生成

Seconds填12，Lyrics留空；工程保持当前BPM。

```text
Instrumental electronic groove at the project tempo. Tight drums, warm electric piano, rounded sub-bass, and a spacious, restrained mix. No vocals.
```

### C — Agent调用YuE2

```text
Use YuE2 to generate about 12 seconds of instrumental electronic music at the current project tempo: tight drums, warm electric piano, rounded sub-bass, and no vocals. Use the current time signature and playhead position. Let me preview the result before adding a track.
```

### 可替换的Agent分析镜头

以下每次仅选一个适用片段，不要连续提交七个任务再等待：

```text
Use cloud SCNet to separate the selected audio range into stems. Let me preview the candidates before adding tracks.
```

```text
Use cloud TransKun to transcribe the selected piano audio to MIDI. Preserve any pedal controller events the model returns. Let me review before adding it.
```

```text
Use ChordMini to identify chords in the selected audio range. Show me the labels before adding a chord track.
```

## 拍摄通过标准与素材整理

保存最终工程、原录屏、真实模型结果、模型名/输入范围/任务耗时与视频工程；视频剪掉等待不改变原始记录。每段音频对比保持相近试听音量，不以变响冒充音质提升。界面自产生的状态、方案卡和确认按钮在English模式下应为英文；用户原始中文歌词、文件名或指令保持原文不算界面翻译失败。

录音、英文LLM回答、右键菜单/下拉/关闭提示、保存重开和物理声卡播放必须在本轮实际界面确认。若任一功能未通过，先修复或延后对应镜头，不使用静态图假扮运行成功。模型准确率、无损拉伸、任意插件兼容、云端永久在线、自动租卡/迁移不属于本片可宣称成果。

实现依据：[0.13人工清单](../2026-11-07-hybrid-pipeline/MANUAL-CHECK.md)、[Agent人工清单](../2026-11-07-hybrid-pipeline/agent/MANUAL-CHECK.md)、[原生装置验收](../2026-11-06-workspace-brand/MANUAL-CHECK.md)、当前AnalysisPanel/GenerationPanel/MainComponent与native_catalog源码。此次只编写脚本，没有据此认定新主机或拍摄已验收。
