# 英文版 0.13.3 手动模型入口

> 版本说明：本页是 0.13.3 历史入口记录。0.13.4 已修 Cloud → Beats 的隐藏筛选遗留，无需先切 Local；新流程见[0.13.4 操作手册](../../demo/2026-11-14-demo-runbook-v0134.md)。本页其他手动模型路径仍可参考，不代表已补验真实 GPT 指令。

2026-11-14。适用于演示时 Agent 的语言 API 额度不足、返回 429，而音乐模型服务仍可用的情况。以下按钮与参数依据当前源码核对，**本轮未实际用鼠标逐项验收**；真实模型、DAW 管线和原样英文提示词的实测结果分别以本目录 `RESULTS.md` 为准。手动成功不能写成 Agent 自然语言理解已通过。

这些入口直接向同一套 DAW 任务接口提交音乐任务，不经过 GPT/Kimi，不消耗它们的语言 API 额度。YuE2、ACE、SCNet、ChordMini、TransKun 仍需要已连接的云端音乐服务、模型环境与可用算力；Beat This! 使用本地已注册模型。它们不是离线占位结果。

## 开始前

- 使用英文版，停止全局播放；每种演示另存一个工程版本。
- 生成工程设为 **90 BPM、4/4**，播放头移到 **0 秒**；New Light 与钢琴演示保持 **120 BPM、4/4**。
- 分析前选中**音频片段本身**，不是只点轨道头。下栏来源名称应对应目标轨道；显示 `Select one audio clip` 时不能开始。
- 本页是手动入口，不读取 Agent 的 `Scope`。配套 Agent 提示词仍用 `Whole project`；手动分析则明确作用于当前选中的音频片段，两者并不矛盾。若已通过手动按钮加入结果，不要再点击旧 Agent 方案的 `Apply changes`；有旧待应用方案时用 `Discard` 放弃它。
- 全片分析不要额外拖选时间范围。进入 `Options` 核对 `Start / s` 与 `Length / s`，然后 `Done`。独立裁片的起点填 `0`，不填原歌曲中的 60 秒或 20 秒。
- 已有真实候选时优先用 `Recent generations` / `Recent analyses` 找回；不要因为 Agent 失败就重复扣费推理。

## D1：YuE2 / ACE 生成

入口：顶部 **`add...` → `Generate music…`**，打开 `Generate music` 下栏。模型下拉分别选择 **`YuE2`** 或 **`ACE-Step 1.5 XL`**；同一正文测两个模型时分别保存工程，避免混淆候选与来源。

在 **`Describe the music`** 粘贴下面正文。这是已通过 ACE 实测请求的实际音乐 brief，与 Agent 操作指令不是同一段文本：

```text
Neo-soul excerpt with warm, intimate production: Warm Rhodes electric piano, mellow clean electric guitar (light chorus/reverb), rounded electric bass, laid-back drums (soft kick, brushed/snappy snare, relaxed hi-hat), and an intimate female lead vocal. Short intro, verse, chorus, and a natural ending; keep arrangement sparse and warm so the vocal sits clearly. Aim for a smooth neo-soul groove, subtle dynamics, and melodic hooks appropriate for verse + chorus structure. Mix for vocal presence and vintage-modern warmth.
```

在 **`Lyrics · optional`** 单独粘贴：

```text
[Verse]
We found a rhythm in the quiet
Let the city fade away
[Chorus]
Stay until the morning light
Hold this feeling through the night
```

**`Seconds` 填 `32`，`Seed` 留空**。确认面板上下文显示项目 90 BPM、4/4、0 秒位置，然后点 **`Generate`** 一次。等待真实候选就绪后点 **`Preview`** 试听，`Stop` 停止试听，喜欢后点 **`Add track`**。这是手动接受按钮，不叫 Agent 的 `Apply changes`。

当前生成任务允许 10–120 秒；32 秒是拍摄短段。64 小节、90 BPM、4/4 约 170.67 秒，不能用一次当前任务实现，也不能保证模型按小节精确分段或生成完整结尾。实际时长和人声/结构质量要试听；出现 token 限制提示时不要把截断音频拍成完整作品。

正文证据：`E:/MusicAgent&DAW/demo-video/2026-11-14/rehearsal/D1-ACE-4e9201887e84/report.json` 的 `request.prompt`、`request.lyrics`、`request.duration_seconds`；`cases.json` 的 D1-YuE2 `generation_request` 复用同一音乐正文。模型相同参数仍可能生成不同音频。

源码：`MainComponent.cpp:2412` 菜单；`GenerationPanel.cpp:50` 直接 `start_generation`；`:67` 模型名称；`:98` 英文字段与按钮；`:36` 试听和 `accept_generation_result`。

## D1：SCNet 四轨分离

将选中的生成音频轨重命名为 **`Chosen Neo Soul`**，选中唯一音频片段。

1. 顶部 **`analyze`** → 下栏 **`Separate`**。
2. 执行位置选 **`Cloud`**，模型选 **`scnet`**。云端 SCNet 固定请求四轨，界面会隐藏本地的 4/6 轨数与质量选项，不需要再找四轨开关。
3. `Options`：`Start / s = 0`，`Length / s` 保留该片段实际完整长度（通常约 32 秒）；不要填超过音频结尾的值。
4. 点 **`Analyze`**，等四个真实结果；可选中结果行后点 **`Listen`**，`Stop` 停止试听。
5. 点 **`Add tracks`**。在编曲中将原始完整混音轨 **Mute**；四个结果轨也先 Mute，再逐一取消 Mute，拍摄鼓 → 贝斯 → other → 人声的叠加。不要把原始混音与分离轨同时播放来冒充叠加。

源码：`AnalysisPanel.cpp:23` 模式名；`:344` 模型按 Cloud/Local 筛选且显示原始 model ID；`:466` 请求；`:485` 云端分离强制 `stems=4`；`:375` `Add tracks`；`:735` 隐藏云端无效选项。

## D2：ChordMini 和弦轨

输入：`E:/MusicAgent&DAW/demo-video/2026-11-14/sources/new-light-60-84.wav`。它已经是 24 秒独立裁片。唯一音频轨命名 **`New Light Source`**，选中该片段。

**`analyze` → `Chords` → `Cloud` → `chordmini` → `Options`（Start `0`，Length `24`）→ `Analyze` → 审阅和弦标签 → `Add chord track`**。

先另存为 `D2-NewLight-Chords`，再做下一步 Warp。云端 ChordMini 没有本地 `Common chords` / `Major / minor` 的词表选项；不要去改一个当前不可见的本地设置。检测标签由模型输出，不预先承诺每个爵士和弦正确。

源码：`AnalysisPanel.cpp:327` 标签；`:375` `Add chord track`；`:485` 云端其他分析参数为空；`:735` 词表只在本地 Chords 可见。

## D2：Beat This! → Warp（保留开头、保持项目速度）

继续选中 **New Light Source 的音频片段**，不是和弦轨。在上述和弦已加入的工程中操作。

**0.13.3 有已从源码确认的路由遗留问题：`Chords` 选了 Cloud 后直接切 `Beats`，Cloud 会被保留，但路由下拉又被隐藏，可能显示 `Model unavailable`。本轮没有修产品代码。**

可操作绕法：

1. 仍在 **`Chords`** 标签时，把 **`Cloud` 改为 `Local`**，然后才点 **`Beats`**。即使切到 Local 后 Chords 暂时显示模型未就绪，也无需运行和弦任务，直接切 Beats。
2. `Beats` 使用当前注册的本地节拍提供者（本方案为 **`beat-this-final0`**）。这里不会显示模型/执行位置下拉。
3. 选择 **`Auto meter`**，`Options` 设 Start `0`、Length `24`，点 **`Analyze`**。
4. 检查 **`BPM`** 和 **`First / s`**。半速/倍速可用 **`/2`**、**`x2`** 修正；点击图中的拍线能重选第一小节拍。`First / s` 是分析选区内的秒数，不是原歌曲绝对时间。
5. 点 **`Align audio`**。它使用保留音高的 Warp，使音频跟随项目速度，并把首个小节拍对到合适的小节线，保留首拍之前的音频。**不要点 `Use this tempo`**：那个按钮会改变项目 BPM/拍号，与本次保持项目 120 BPM 的目标不同。
6. 完成后到 **`source`** 检查 Warp 状态、试听与和弦位置；无需再盲点第二次 `Apply`。另存为 `D2-NewLight-Aligned`。可用 Undo 对比原始时间映射。

保持开头不代表强行把首拍塞到第 1 小节：引擎会选择能容纳开头音频的小节位置。对齐后看到片段或首拍位置向后调整属于此策略。

源码：路由不重置 `AnalysisPanel.cpp:235`；按路由筛选 `:344`；Beats 隐藏下拉 `:733`；按钮语义与 `audio_to_project` / `project_to_audio` `:594`。保留前奏的小节目标与 `preserve_pitch` 在 `EngineSessionAnalysis.inc:340`；官方本地模型 ID 注册在 `scripts/audio_analysis/register.py:147`。

## D3：TransKun 钢琴转 MIDI

输入：`E:/MusicAgent&DAW/demo-video/2026-11-14/sources/tea-piano-20-36.wav`。它已经是 16 秒独立钢琴裁片。唯一音频轨命名 **`Tea Piano Source`**，选中该片段。

**`analyze` → `MIDI` → `Cloud` → `transkun` → `Options`（Start `0`，Length `16`）→ `Analyze` → 观看音符候选 → `Add MIDI track`**。

云端模式隐藏本地 Basic Pitch 的乐器、Threshold 与 Min note 参数；不需要找 `Piano` 开关。加入 MIDI 后，双击新片段打开钢琴卷帘；为新 MIDI 轨加载已测试的钢琴乐器，Mute 原始钢琴音频后再回放对比。**有音符不等于自带钢琴声音**。踏板仅保留真实模型返回且管线接收的事件，不承诺凭空补齐。

源码：`AnalysisPanel.cpp:23` 中转录标签为 `MIDI`；`:110` 仅本地转录显示音符阈值；`:375` `Add MIDI track`；`:735` 云端隐藏乐器选项；`:583` 调用统一 `accept_analysis_result`。

## 失败时只查这几件事

| 现象 | 下一步 |
|---|---|
| Agent 返回语言 API 429 / insufficient_quota | 停止反复发 Agent 指令，用本页按钮；不要把额度问题误当成音乐模型失败。 |
| 模型名字后带 `· unavailable` / `Model unavailable` | 检查音乐服务、模型是否就绪；若发生在 Cloud 和弦后切 Beats，先按上面 Local 绕法。 |
| `Analyze` 灰色 | 确认选中准备好的音频片段、模型就绪、没有录音或未完成任务，检查来源名称和范围。 |
| 结果已有但加入按钮灰色 | 检查是否已加入、源片段是否后来被剪切/移动/改速导致候选过期，以及是否仍在运行任务。不要重复生成来试按钮。 |
| 生成 `Preview` 不可用 / MIDI 没声音 | 先停止全局播放再 Preview；MIDI 另查轨道乐器、Mute/Solo、输出和监控，不拿它判断转录失败。 |
| Beat This! 识别出半速/倍速 | 审听后用 `/2` 或 `x2` 修正，再检查首拍；不是要求重新跑云模型。 |

人工入口与 Agent 都走候选审阅后再入工程的路径。真实音乐计算、鼠标交互、听感和硬件录音须分别验收；本页只承诺已核对的操作路径与已注明边界。
