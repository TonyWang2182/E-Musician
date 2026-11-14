# 4 分钟演示：可复制提示词与操作流程

> 0.13.4 更新：本页保留 0.13.3 的实测原样提示词与历史彩排步骤。新侧栏按钮、同工程双结果选择、Beats 修复、Jungle 素材和实际动效请以[新版操作手册](2026-11-14-demo-runbook-v0134.md)为准；新按钮叫 Apply。原样提示词的真实语言验证状态没有因 UI 升级自动变为通过。

版本：2026-11-14 / DAW 0.13.3。配套[4 分钟中英分镜](2026-11-12-four-minute-demo.md)。本稿用于实际操作，分镜稿用于旁白、镜头和剪辑。

**先看验证状态：ACE 已通过真实 GPT 提示词完整操作链；之后 OpenAI 返回 HTTP429，一次小请求确认 `insufficient_quota`。其余五条提示词须待 API 额度恢复后补验，当前只能分别核验实际音乐模型与 DAW 管线。最终结果见[RESULTS.md](../review/2026-11-14-demo-rehearsal/RESULTS.md)。** 六条英文提示词与[测试案例 cases.json](../review/2026-11-14-demo-rehearsal/cases.json)逐字一致；六条均使用 **Whole project**，分析工程中只有一条来源音频轨，并使用下文唯一英文轨名。Whole project 表示允许整个演示副本进入操作范围，因此只在这些独立演示工程中使用，不在现有正式作品里照抄执行。

API 额度恢复前，可以用[手动模型入口](../review/2026-11-14-demo-rehearsal/MANUAL-FALLBACK.md)调用音乐模型，不经过 GPT；但这种录屏不能解说成 Agent 自动执行。该文档也提供音乐生成正文与独立歌词字段，以及 Cloud 和弦切本地 Beats 的现有界面绕法。要录制真正的 Agent 操作镜头，先恢复 API 可用性，并对下面未完成的五条原样提示词逐一补验。

实测会分别记录实际模型任务、候选、Apply、回读、Undo/Redo、保存重开；这些检查不代替试听、鼠标操作或真实声卡录音。不要把“接口完成”写成“和弦一定准确”或“音乐一定好听”。

六条英文另存为纯文本，可直接打开复制：`E:/MusicAgent&DAW/demo-video/2026-11-14/prompts/`，文件名依次是 `D1-YuE2.txt`、`D1-ACE.txt`、`D1-SCNet.txt`、`D2-Chords.txt`、`D2-Warp.txt`、`D3-Piano.txt`。正文与本稿及测试案例保持一致，不需手工替换轨名或模型名。

## 0. 开始前的 2 分钟准备

1. 从 `E:/MusicAgent&DAW/Start E-musician 0.13.3.cmd` 打开，检查标题 **0.13.3**。settings → Language → English；打开 Agent，确认 **DAW connected**。DAW connected 只代表连接本机，不能证明语言 API 有额度。
2. 打开录屏程序，先试录 10 秒并回看：画面、DAW 输出、麦克风通道和声画同步都正确。ASIO 输出能听见，不代表录屏一定录到了。
3. 确认 M/S/R 字母可读、没有误开的 Solo/Arm；先以较低监听音量试听。源音频和分离结果不要叠着同时播放。
4. 每段演示独立工程，保存到 `E:/MusicAgent&DAW/demo-video/2026-11-14/` 下的新拍摄子目录；保留 `.emproj` 与其完整 `.assets` 文件夹。不要覆盖测试器生成的工程或旧项目。
5. Agent 设 **Whole project**；发送后先等候选/方案，避免中途改工程、切换项目或重复发送。出现方案后先试听/检查，再点 **Apply changes**。
6. 推理耗时不算成片时间。录下真实等待的开头和完成的结尾，剪辑时注明 `Processing time shortened`；复用旧结果注明 `Previously generated/analyzed result`。

### 本次使用的素材

| 用途 | 直接导入的文件 | 来源 |
|---|---|---|
| Demo 1 生成与分离 | 由 YuE2/ACE 本轮生成，分离使用已接受的 ACE 版本 | 不预置假结果；模型实际长度以任务结果为准 |
| Demo 2 New Light | `E:/MusicAgent&DAW/demo-video/2026-11-14/sources/new-light-60-84.wav` | 原曲第 60–84 秒，共 24 秒 |
| Demo 3 Tea for Two 钢琴 | `E:/MusicAgent&DAW/demo-video/2026-11-14/sources/tea-piano-20-36.wav` | 已有真实钢琴分轨第 20–36 秒，共 16 秒 |
| Demo 4 鼓与钢琴采样 | `E:/E-musician/test-projects/test5-sampler&rack/` | kick、snare、hat 及 `07-piano-C4.wav` |

原件路径与 SHA-256 见[SOURCES.json](../review/2026-11-14-demo-rehearsal/SOURCES.json)。上述两个分析摘段已单独导出，原件保持；摘段音乐内容是否适合镜头仍需试听。使用自己新录的人声作为 Demo 4 的录音演示素材。

## 1. Demo 1：YuE2 → ACE → SCNet 四轨叠加

对应 **G01–G09，00:24–01:40**。本段先展示两个生成版本，再在所选版本上做分离。

本次生成 **32 秒 neo-soul 短段**，不是此前请求的完整 64 小节歌曲。90 BPM / 4/4 下，32 秒约等于 12 小节；64 小节需要约 170.67 秒，超过当前单次 120 秒上限。提示词中的段落和自然结束是创作要求，不能保证模型严格按小节交付。

### D1-YuE2：第一次生成

**前置：**新建空工程，90 BPM、4/4，播放头放在起点；Agent=Whole project。可通过 Edit → Tempo, meter and loop range… 设置速度与拍号。先另存为 `D1-YuE2-Before.emproj`。

完整复制以下英文：

```text
Use cloud YuE2 to generate one 32-second neo-soul excerpt at the current project tempo and time signature, starting at the current playhead. Warm Rhodes, mellow clean guitar, rounded bass, laid-back drums, and an intimate female lead vocal. Aim for a short intro, verse, chorus, and natural ending. Put these English lyrics in the generation lyrics field; this must not be an instrumental request:
[Verse]
We found a rhythm in the quiet
Let the city fade away
[Chorus]
Stay until the morning light
Hold this feeling through the night
Prepare an import proposal so I can preview the result before applying it. Generate once; do not retry.
```

1. 发送一次，录下真实任务状态与模型名称。
2. 方案出现后用 **Preview** 试听。记录实际时长，检查人声、鼓、贝斯和电钢琴是否可辨，有没有突然截断。
3. 点 **Apply changes**，应新增一条音频轨；停止 Preview 后再用全局播放试听，避免两个播放源同时出声。
4. 另存 `D1-YuE2-Accepted.emproj`，保存真实结果标识和录屏。只保存“尚未接受的候选”不能保证重开仍可取回候选。

**镜头：**G01–G03；选一段约 6 秒真实试听，无旁白和额外 BGM。候选已经导入后补拍时，注明使用已生成结果。

### D1-ACE：第二次生成

**前置：**另建空工程，同样 90 BPM、4/4、播放头起点、Whole project。不要同时播放前一个工程的试听。另存 `D1-ACE-Before.emproj`。

```text
Use cloud ACE-Step 1.5 XL to generate one 32-second neo-soul excerpt at the current project tempo and time signature, starting at the current playhead. Warm Rhodes, mellow clean guitar, rounded bass, laid-back drums, and an intimate female lead vocal. Aim for a short intro, verse, chorus, and natural ending. Put these English lyrics in the generation lyrics field; this must not be an instrumental request:
[Verse]
We found a rhythm in the quiet
Let the city fade away
[Chorus]
Stay until the morning light
Hold this feeling through the night
Prepare an import proposal so I can preview the result before applying it. Generate once; do not retry.
```

流程与 YuE2 相同：发送一次→Preview→检查→Apply changes→另存 `D1-ACE-Accepted.emproj`。两个请求的音乐正文、歌词、工程节拍和32秒预算一致，仅模型不同。

**镜头：**G02、G04–G05。试听同样保留约 6 秒，与 YuE2 音量接近。当前实测分离链选 **ACE** 输出，不代表判定 ACE 音乐质量一定更好；若拍摄决定改用 YuE2，先对那份真实音频单独完成一次 SCNet 分离检查。

### D1-SCNet：分离并逐层加入

**前置：**打开已接受 ACE 的副本，保证只有一条来源音频轨、该轨只有一个音频 clip。选轨后 F2，把轨名改成 **`Chosen Neo Soul`**，大小写和空格按此写；另存 `D1-Stems-Before.emproj`。Whole project。

```text
Use cloud SCNet to separate the only audio clip on the track named Chosen Neo Soul into vocals, drums, bass, and other. Keep the original audio unchanged. Prepare a four-track import proposal for review; do not apply it yet.
```

1. 发送一次→等待四个真实 stem 候选→检查方案包含 vocals / drums / bass / other。
2. 点 **Apply changes**。应一次新增四条音频轨，来源轨保留；四个结果按来源对齐。
3. 停止播放，手动开启来源轨 `Chosen Neo Soul` 的 **M**。确认所有轨的 **S** 都关闭。
4. 给结果轨用 F2 改成清楚的 `Drums`、`Bass`、`Other`、`Vocals`；想按此排序，用 Edit → Move track up/down。只整理轨道，**不移动 clip 起点**。
5. 先让 Drums 开声，Bass/Other/Vocals 开 Mute；从同一个位置播放，按真实音乐强拍依次解除 Bass → Other → Vocals 的 Mute。
6. 连续录一段不少于 16 秒，再录四声部全开的完整合奏。另存 `D1-Stems-Layered.emproj`。

**镜头：**G06–G09。四分轨是一次导入；逐层加入是手动解除静音，不是模型逐轨生成。验收时至少单独听每条 stem，并比较源轨单独播放与四轨合奏；不要把两者叠着听。

## 2. Demo 2：New Light 和弦轨 → 节拍与 Warp

对应 **A01–A06，01:40–02:32**。

### D2-Chords：分析并添加和弦轨

**前置：**新建 120 BPM / 4/4 工程，只导入 `new-light-60-84.wav`，放在时间线起点；来源轨命名为 **`New Light Source`**，一轨一个音频 clip。Whole project。另存 `D2-NewLight-Original.emproj`，保留给 A/B。

```text
Use cloud ChordMini to identify the chords in the only audio clip on the track named New Light Source. Show the detected labels and prepare a chord-track import proposal for review. Keep the source audio and project tempo unchanged.
```

1. 先播放短句，录下 A01 的约 7 秒原声。
2. 发送→等真实和弦候选→检查标签和时间范围→**Apply changes**。
3. 确认新和弦轨出现，播放头能经过实际标签；音频未被移动/改速，工程仍为 120 BPM / 4/4。
4. 至少听查两个和弦变化点。不确定的标签保留为模型结果，不在字幕中夸大准确率。
5. 另存 **`D2-NewLight-Chords.emproj`**，后一步从它继续，不另导入第二份音频。

**镜头：**A02–A03。不要把和弦标签轨称作已经生成了伴奏 MIDI。

### D2-Warp：分析节拍并对齐

**前置：**打开刚保存的 `D2-NewLight-Chords.emproj`；来源仍是唯一音频轨 **`New Light Source`**，已经有刚导入的和弦轨。120 BPM / 4/4，Whole project。

```text
Use local Beat This! to analyze the tempo and downbeats of the only audio clip on the track named New Light Source. Show the detected BPM and first downbeat. Prepare a plan to align the entire clip to the current project tempo, preserving pitch and retaining the opening audio. Keep the project BPM and time signature unchanged. Let me review the alignment before applying it.
```

1. 发送→核查检测 BPM、首拍、目标工程速度。半速/倍速或首拍明显错时，**先不要 Apply**。
2. 检查无误后 **Apply changes**。对齐方案已经包含固定比例保音高拉伸与位置调整，不用再单独做一次 Warp。
3. 选来源 clip，打开 **Source**，确认 Warp 开启、Source BPM 与实际核对值一致、Target BPM 为 120；返回编曲区看首拍和小节线。
4. 工程仍应为 120 BPM / 4/4，开头音频保留，先前和弦轨随来源时间映射对应。首拍可能对齐到后一个小节以保留前奏，不要求 clip 左边缘一定为时间零。
5. 另存 `D2-NewLight-Aligned.emproj`。与 `D2-NewLight-Original.emproj` 比较同一句音乐，原版约3秒→对齐版约4秒；音量接近，后段可开节拍器核查。

**镜头：**A04–A06。说“保音高拉伸”，不说“任何拉伸都绝对无损”。若必须人工修正 BPM/首拍，用确认过的具体数值让 Agent 另提新方案；不要只改面板字段后继续应用旧冻结方案。实际如何修正及是否需要修正，以本轮结果和试听为准。

## 3. Demo 3：Tea for Two 钢琴转 MIDI

对应 **T01–T05，02:32–03:06**。

**前置：**新建 120 BPM / 4/4 工程，只导入 `tea-piano-20-36.wav`，轨名 **`Tea Piano Source`**，一轨一个音频 clip；Whole project。另存 `D3-TeaForTwo-Before.emproj`。

```text
Use cloud TransKun to transcribe the only audio clip on the track named Tea Piano Source to MIDI. Preserve any pedal events actually returned by the model. Prepare a MIDI-track import proposal for review. Keep the source audio unchanged.
```

1. 先单独播放钢琴摘段，字幕 `Previously separated piano stem`。
2. 发送→等待候选→检查有真实音符→**Apply changes**，应新增 MIDI 轨与 clip。
3. **手动给新 MIDI 轨挂已验证的钢琴音源。** MIDI 本身不发声，也不包含原钢琴插件音色；可以用已加载钢琴样本的 Sampler 或已验证的 VST3 钢琴。
4. 双击新 MIDI clip，点 **expand**，或 **Ctrl+Alt+E** 展开卷帘。
5. 源钢琴开声时 MIDI 静音；播放 MIDI 时源钢琴静音。比较相同位置的音高、节奏、漏音/多音和过长音，分别留3秒 A/B。
6. 选一个音符修改长度/位置，然后 Undo；确认是实际可编辑数据。踏板事件只有结果实际返回时才展示或说明。
7. 另存 `D3-TeaForTwo-MIDI.emproj`；停止后重开一次，检查音符、音源状态与回放。

不使用 Keyboard.mp3 的旧结果代替 Tea for Two，也不展示当前没有的完整五线谱排版。

## 4. Demo 4：原生装置、插件和真实录音

对应 **P01–P06，03:06–03:48**。这段按原分镜拍 **手动操作**，不使用上述 Agent 提示词。新建90 BPM / 4/4 hip-hop工程，轨道可命名 `Drums`、`Bass`、`Sampler Keys`、`Plugin Keys`、`Vocal Take`；提前做好8–16小节伴奏，只给准备录音的轨留空。

开拍前关闭 Agent 或放宽窗口，避免窗口宽度不足时 Library 被隐藏；在 Library → Instruments 双击装置，或用 Open / add 添加。提前加载全部鼓采样、Sampler 与第三方音源。每段录音开拍前，先在 **devices → I/O + sends** 设输入和 Monitor、只 Arm 目标轨、设1 bar预备拍、移好播放头；9–10秒成片镜头只容纳实际 Record→预备拍→演奏→Stop，不包含配置过程。

| 镜头／成片时间 | 操作流程 | 开拍前必须通过 |
|---|---|---|
| P01，03:06–03:12 | 展示已装好采样的 Drum Rack：kick→MIDI36，snare→38，closed hat→42，open hat→46；点垫右下三角形或双击垫试听。 | 下栏波形能完成加载；每个垫分别出声。普通单击垫主体主要是选垫；加载4个样本提前完成。 |
| P02，03:12–03:17 | Sampler 预载 `07-piano-C4.wav`，根音 MIDI60；模式设 `gate`，调整采样起点或 Release，按键试听。 | 松键能听到 Release 变化；`one-shot` 模式下 Release 不生效，不拿灰掉的旋钮做演示。 |
| P03，03:17–03:21 | 打开提前加载好的已验证 VST3 编辑器，弹一下有声，再收起。 | 当前机器上实际加载、可见窗口、演奏及保存重开已通过；拍摄时不临时扫描/首次加载大型插件，不写“所有插件支持”。 |
| P04，03:21–03:30 | 输入/Arm/Monitor提前设好：Record→一小节预备拍→弹两小节→Stop。 | 连续录屏中能看到实际新 MIDI clip；停止完成后取消Arm，回放新音符有声。90 BPM下一小节约2.67秒，两小节约5.33秒。 |
| P05，03:30–03:40 | 提前切好 `Vocal Take` 麦克风输入并只Arm它：Record→一小节预备拍→唱/念两小节→Stop。可用短句“Find the groove, make it move.” | 实际生成新波形，等 Finishing recording 结束；取消Arm后回放能听到本次take。硬件直通与软件监听避免重复。 |
| P06，03:40–03:48 | 回放新录MIDI和人声，下栏掠过EQ/Compressor，再回编曲全景，Ctrl+S。 | 录屏里确实能听见DAW输出；保存后重开仍有本次take、音符与装置状态。 |

P04、P05 必须保留 Record→预备拍→演奏/演唱→Stop 的连续过程；可以裁画面、加同步手部机位，不能拿预先完成的片段冒充实录。分别另存 `D4-HipHop-Before`、`D4-HipHop-MIDI-Take`、`D4-HipHop-Vocal-Take` 和 `D4-HipHop-Final`，避免补拍覆盖唯一录音。

Agent 目前不能替你开始录音、设置声卡、任意操作第三方插件 GUI、创建采样器或指定路径加载采样；不要把这些手动镜头配成“Agent 自动完成”。

## 5. 本轮验证状态与录屏验收

**六项真实音乐模型与工程管线均已通过；其中只有ACE完成了原样GPT提示词链。** 其余五条受API额度阻断，结构化管线成功不能代替自然语言实测。见[RESULTS.md](../review/2026-11-14-demo-rehearsal/RESULTS.md)。

| 案例 | 机器检查的目标 | 人工仍要确认 | 当前状态 |
|---|---|---|---|
| D1-YuE2 | 结构化YuE2任务、歌词非空、32秒预算；实际31.9987秒且token_budget截断 | 是否有人声、段落完整、值得展示 | 模型/工程链通过；GPT提示词待补验 |
| D1-ACE | 真实GPT及ACE任务，含歌词、候选/导入/保存链 | 人声与结构是否符合要求 | 真实GPT与模型/工程链通过；人工听感待验 |
| D1-SCNet | 从已接受ACE音频得到真实四stem，新增四轨且保留来源 | 四声部可辨、串音、逐层开声无重复来源叠加 | 模型/工程链通过；GPT提示词待补验 |
| D2-Chords | New Light真实24秒输入、和弦候选/和弦轨 | 实际和弦标签和转换点是否合理 | 模型/工程链通过；GPT提示词待补验 |
| D2-Warp | 本地Beat This!真实分析、保工程速度、Warp及来源和弦映射 | 拍点是否贴网格、首拍是否正确、拉伸听感 | 模型/工程链通过；GPT提示词待补验 |
| D3-Piano | Tea for Two真实钢琴16秒输入、TransKun真实音符/CC、导入保存 | 漏音/多音、八度、节奏，挂音源后的播放 | 模型/工程链通过；GPT提示词待补验 |
| D4 | 不以本轮Agent测试代替硬件与鼠标验收 | 鼓垫/采样/插件、真实MIDI/人声录音、录屏捕获声音 | 人工待验 |

每个演示工程至少完成一次：Apply 后结果可见→Undo撤销这次导入/对齐→Redo恢复→保存→关闭重开→播放。做这个检查时不要在两步之间改其他内容，否则Undo可能先撤销你后来的编辑。

## 6. 失败时先看这些地方

| 现象 | 先检查什么 |
|---|---|
| Agent找不到音频/问目标是谁 | Scope是否Whole project；轨名是否与提示词逐字一致；该轨是否只有一个音频clip；是否误在另一工程发送。 |
| Agent生成时又问BPM | 工程是否已经设90 BPM/4/4；先记录原回答与时间，不反复生成。两条生成词已经明确沿用工程节拍。 |
| 生成没有人声 | 看任务是否实际带非空lyrics；若字段正确但模型没唱出来，这是结果质量问题，不能用后期加人声冒充原生成结果。 |
| 显示任务failed/连接错误 | 保留具体错误、模型名与大致时间；检查云主机/SSH服务连接。一次失败先查原因，不连续点击生成。 |
| 任务ready但轨道没增加 | ready只代表候选；先Preview/检查，再Apply changes。 |
| Apply提示工程/范围已变化 | 方案之后是否换项目、修改轨道/clip或改选择；按当前状态重新提方案，不一直点旧方案。 |
| 分离后声音明显变大 | 原始混音是否仍开声；先Mute来源，关闭误开的Solo，再听四轨。 |
| MIDI有音符但没声音 | 新轨是否挂了乐器；来源/目标Mute或Solo状态；输出声卡是否正确。MIDI文件本身没有声音。 |
| Sampler调Release没区别 | 是否Gate模式、采样已就绪、有没有松键；One-shot会播到采样末尾。 |
| Warp首拍不准或半速/倍速 | 先不应用；听查候选，确定实际BPM/首拍后提新方案。不要把猜测值作为已检测结果。 |
| 录音结束不能立即保存 | 等待Finishing recording结束；确认新clip出现，再保存，不在整理take期间反复点Save。 |
| 录屏有电平却没声音 | 回看录屏文件的音轨与ASIO捕获设置；实际听到DAW声音不等于录屏程序已捕获。 |

给问题留最小记录即可：案例ID、工程名、提示词版本、模型/任务ID、错误全文或截图、大致时间、结果文件位置。不要把API密钥或SSH密码放入录屏或TAKES文档。

已通过工程可从 [E盘入口](<E:/MusicAgent&DAW/demo-video/2026-11-14/OPEN-FIRST.md>) 打开；先Save as拍摄副本，不覆盖验证原件。
