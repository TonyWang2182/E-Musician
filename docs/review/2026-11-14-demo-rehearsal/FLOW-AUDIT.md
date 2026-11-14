# 演示操作流程只读审查

2026-11-14，针对 0.13.3 与原 4 分钟分镜。本审查只读取实际代码和既有档案，没有调用模型、打开 GUI、改用户工程或验收声音；自然语言提示词的真实运行证据由本轮主验收另记。

## 结论

原分镜的六项 Agent 音乐任务均有真实接口：YuE2、ACE、SCNet、ChordMini、Beat This!、TransKun。应保留“一次请求一个任务→真实候选→Preview/审阅→Apply changes”的拍法。Demo 4 的采样加载、装置试听、第三方插件及录音应拍手动操作；当前 Agent 不能包办这些步骤。

有五处必须写清：

1. **Scope 下拉只有 Current selection / Whole project。** 内部虽然有 `clip` 模式，但当前网页没有第三个“Whole clip”选项。不能指导用户去找该按钮。分析/Warp应先整理成独立短 clip，选中整个 clip，并确认没有只覆盖其中一部分的时间选区。
2. **有人声需要非空歌词。** `start_generation` 的描述与歌词是两个字段；未提供歌词的默认路线是纯器乐。自然语言请求应明确提供要唱的歌词，不能仅写 female vocals 然后把结果是否有人声当作接口保证。
3. **64 小节的要求与当前任务上限冲突。** 90 BPM / 4/4 的 64 小节是 170.667 秒，当前接口只接受 10–120 秒。4 分钟演示用 32 秒（相当于 12 小节）的短生成；音乐结构、小节数与自然结束仍是生成条件，不是模型保证。文字描述字段最多 2,000 字符，歌词另有 4,096 字符限额。
4. **Sampler 的 Release 只在 Gate 模式生效。** 若拍“调 Release→松键尾音改变”，需先关闭 One-shot；Drum Rack 的单次采样通常用 One-shot，不适合拿 Release 做听感对比。
5. **方案冻结后不要再移动播放头选区、换项目或编辑。** 至少工程修订和音乐选择改变会使方案过期；显示 stale/changed 应重新提出方案，不能一直点 Apply。

## 各镜头的操作修正

| 镜头 | 可执行顺序 | 验收重点 |
|---|---|---|
| G01–G05 | 新工程 90 BPM / 4/4、播放头起点、Whole project；分别请求 YuE2、ACE，提供相同 brief/lyrics/32 秒。每版真实 Preview 后接受到不同工程副本，并保存 assets。 | 两次任务不能在同一次 Agent 请求中要求同时生成；不同模型真实 ID 可读；只保留待应用卡片不保证重开恢复。Preview 不是已加入工程。 |
| G06–G07 | 在选中的生成版工程中选择完整音频 clip；Current selection；SCNet 四分轨；候选→Apply；手动把源轨 Mute。 | 四轨一次导入；四个 stem 同起点、完整原源保留；源轨静音后听分轨，避免声音翻倍。 |
| G08 | 所有 Solo 关闭；除 Drums 外三条 stem Mute；播放中依次解除 Bass、Other、Vocals 的 Mute。需要上下排序可用 Edit → Move track up/down。 | 不移动 clip 起点，不把“四次解除静音”讲成“四次模型生成”。Mute/排序是手动操作。 |
| A02–A03 | New Light 独立 15–25 秒 clip；Current selection；Cloud ChordMini→候选标签→Apply。 | 正确命名为和弦轨，不是钢琴 MIDI；标签及切换时间来自实际结果；至少人工听查两个转换点。 |
| A04–A06 | 再选源音频整块；Local Beat This!→audio_to_project 方案；核查 BPM/首拍→Apply；Source 只查看已有 Warp，不重复应用。 | 工程 BPM/拍号保持；原来源和弦按相同仿射时间映射跟随；首拍尽量对齐到能保留开头的后一个小节，不强迫挤到时间零。 |
| T01–T05 | 真实 Tea for Two 钢琴分轨摘段→Cloud TransKun→Apply→手动给新 MIDI 轨挂已测试的钢琴音源→双击 MIDI clip→expand 或 Ctrl+Alt+E。 | MIDI 本身不发声；原钢琴/新 MIDI 分开试听；踏板只有实际输出时才展示；不能拿 Keyboard.mp3 旧结果冒充本次转录。 |
| P01 | Library → Instruments → Drum Rack；加载 kick/snare/hat；下栏选对应垫，点垫右下三角形或双击垫试听。 | 单击普通垫主体主要是选垫；三角形/双击才是明确试听路径。ready 后可试听，muted pad 不应发声。 |
| P02 | Library → Instruments → Sampler；load sample…；等待波形/ready；设 Gate；点击 play 或弹 MIDI 键盘，调起止/Release。 | 在 Gate 下比较松键尾音；根音 MIDI 60 对测试 C4 采样。调整参数后应试听，不只拍静态旋钮。 |
| P03 | 拍摄前预载并验证选定 VST3，设备链选它→打开真实编辑器→弹奏→收起。 | 不在 4 秒镜头里临时扫描/首次加载大型采样音源；不声称全部插件兼容。 |
| P04–P05 | Devices / I/O 选择对应输入；只 Arm 当前目标轨；Monitor 按监听方式设置；count-in 开、1 bar；全局 Record→真实两小节→Stop；等待 Finishing recording 结束。 | 两段都保留连续 Record/预备拍/录制/Stop，实际新音符/波形可回放；录屏是否捕获 ASIO 声音必须人工回看，不能以电平代替。 |

## 建议进入主验收的英文提示词

下列为接口审查后的候选输入，**本文件不宣称它们已通过本轮真实 LLM**。生成先用一次 32 秒；若主任务为节约预算使用较短探针，应在结果中明确实际测试秒数。

### YuE2；ACE 用相同正文，仅改模型名

```text
Use cloud YuE2 to generate about 32 seconds at the current project tempo and time signature, starting at the current playhead. Create warm neo-soul with Rhodes, clean guitar, a rounded bass line, laid-back drums, and an intimate female lead vocal. Aim for a short intro, verse, hook, and natural ending. Use these exact English lyrics as the sung lyrics, not an instrumental: [Verse] We found a rhythm in the quiet / Let the city fade away. [Hook] Stay until the morning light / Hold this feeling through the night. Prepare the result for preview before adding it to the project.
```

ACE 替换首句中的 `YuE2` 为 `ACE-Step 1.5 XL`。真正相同的对照需保持其余正文、时长和工程节拍一致。Neo-soul 试听效果仍需人工判断；检查没有无意省略 lyrics。

### SCNet

```text
Use cloud SCNet to separate the selected audio clip into vocals, drums, bass, and other. Keep the source clip unchanged. Prepare a four-track import proposal for me to review.
```

### ChordMini

```text
Use cloud ChordMini to analyze the chords in the selected audio clip. Show the detected labels and prepare a chord-track import proposal for review. Do not change the source audio or the project tempo.
```

### Beat This! 与 Warp

```text
Use local Beat This! to analyze the selected audio clip's tempo and downbeats. Show the detected BPM and first downbeat. Prepare a plan to align the whole clip to the current project tempo while preserving pitch and retaining the opening audio. Keep the project BPM and time signature unchanged. Let me review the plan before applying it.
```

如果检测错，输入具体已人工核对的 BPM/首拍值另提新方案；不要写一条未填值的“修正到正确节拍”，那并不提供可执行参数。

### TransKun

```text
Use cloud TransKun to transcribe the selected piano audio to MIDI. Preserve any pedal events actually returned by the model. Prepare a MIDI-track import proposal for me to review. Keep the source audio unchanged.
```

### 可选装置 Agent 镜头（Whole project，已有采样，独立请求）

```text
On the already loaded Sampler on the track named Sampler Keys, set Gate mode and Release to 250 ms. Keep all other parameters and project content unchanged. Show me the change for review.
```

这条应编译成 **一个** `set_native_pad`，携带 `one_shot=false` 和 `release_ms=250`。不能同一方案再加载文件、创建采样器或要求同时改另一个装置。按原分镜拍手动调参更短，不必额外加入这个镜头。

## 代码依据

- `scripts/music_agent/web/index.html:91`：可见 Scope 只有 selection/project。
- `scripts/music_agent/generation.py:23`：独立 prompt/lyrics、默认歌词为空、10–120 秒、duration_bars 换算，候选导入单独确认；`runtime.py` 限制每请求一次生成。
- `scripts/music_agent/analysis.py:38`：实际模型/位置选择，明确模型不静默替换；beats 与其他分析走不同应用方案。
- `scripts/music_agent/tempo.py:41`、`:136`：整 clip 授权、audio_to_project 保持工程速度、默认对齐位置保留开头。
- `apps/desktop/EngineSessionWarp.inc:133`：与源 clip 关联的已接受和弦按同一时间映射更新。
- `scripts/music_agent/native_catalog.py:88`、`plans.py:126`、`selection.py:128`：已加载采样、Whole project、单动作、无路径/创建权限。
- `apps/desktop/NativeDevicePanel.cpp:39`、`:248`：三角形/双击试听、One-shot 下 Release 禁用。
- `apps/desktop/MainComponent.cpp:973`、`:1054`、`:2541`：卷帘展开、预备拍开关/1–4 bars、轨道上下移动。
- `apps/desktop/SelectedTrackPanel.cpp:123`、`MainComponent.cpp:1129`：录音输入与 Monitor 属 GUI；全局录音从已 Arm 的真实输入录制。

本审查没有改任何应用源码，也没有把接口可达或旧测试结果写成新模型推理通过。当前用户的真实 MIDI、人声录音、插件可见窗口、音乐质量及资源管理器操作仍由用户人工完成。
