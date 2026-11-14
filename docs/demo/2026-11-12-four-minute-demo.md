# E-musician／易乐师：4 分钟演示拍摄稿

2026-11-14 操作补充：0.13.3 的实际提示词、唯一来源轨名、32秒生成预算与逐步操作，请使用[新版操作稿](2026-11-14-demo-operations.md)；本文件保留镜头、旁白和240秒时间轴。实测结果见[彩排证据](../review/2026-11-14-demo-rehearsal/RESULTS.md)，不将脚本预期当作已通过。

版本：v1，2026-11-12（Asia/Shanghai）。成片 **04:00，240 秒**；英文界面、英文旁白与主字幕，中文逐句对照供录制和剪辑使用。建议输出 1920×1080 / 30 fps。

本稿替代旧版 7 分 50 秒脚本作为本次拍摄依据，旧稿保留。依据当前 0.13.2 功能记录与代码编写；**脚本已编排，不代表本次拍摄、模型调用或人工验收已经完成**。本轮未启动推理、录音或修改用户工程。

## 1. 这条视频要讲清什么

观众应看懂这条线：**描述想法 → 比较生成结果 → 拆成可编辑声部 → 理解现有音乐 → 把钢琴音频转为音符 → 用装置和真实录音继续制作。** Agent 负责组织操作，音乐模型负责相应任务，结果回到同一个 DAW 工程，由人试听、确认和编辑。

Demo 1 是主展示，给模型试听和声部叠加留空间；Demo 2 展示“分析结果能参与编辑”；Demo 3 只讲钢琴转 MIDI；Demo 4 用真实录制补足“这也是一个能做音乐的 DAW”。本片不额外塞入全部模型、自动混音或配置教程。

| 部分 | 成片时间 | 时长 | 观众应记住的内容 |
|---|---|---:|---|
| 开场 | 00:00–00:24 | 24 秒 | Logo、名称、代码网址；Agent、分析、编曲和装置的预告 |
| Demo 1 | 00:24–01:40 | 76 秒 | 同一提示词，YuE2 / ACE 两个结果；选一个，再分离成四轨逐层加入 |
| Demo 2 | 01:40–02:32 | 52 秒 | New Light：Agent 和弦分析 → 和弦轨 → 节拍检测 → 对齐与 Warp |
| Demo 3 | 02:32–03:06 | 34 秒 | Tea for Two 已分离钢琴 → TransKun → 可编辑、可播放的 MIDI |
| Demo 4 | 03:06–03:48 | 42 秒 | 自制 hip-hop：Drum Rack、Sampler、第三方插件、MIDI 和人声录制过程 |
| 结尾 | 03:48–04:00 | 12 秒 | 回到 Logo 和网址，邀请试用与反馈 |

### 全片声音与动效规则

- 开头和结尾用 **Demo 4 自制 hip-hop 的无人声伴奏**作 BGM，首尾用同一动机。实际演示试听时撤掉这条 BGM，让观众听到 DAW 的真实输出。
- 英文旁白用自然语速，约 125–140 词/分钟；表中标为“原声”的片段不说话。中文字幕是翻译对照，可另做字幕轨，不必两种语言同时挤在画面上。
- 录屏界面保持英文，工程和演示轨名用英文。章节标题由后期添加，不把字幕做成伪造的应用按钮或模型结果。
- 沿用纸白 `#FEFEFD`、墨黑 `#171817`、青绿 `#527D7A` 与低饱和轨道色。转场用短淡入、裁切推近、线条展开；Logo 可做轮廓揭示，不能把原始简笔画改成另一套风格。
- 每次只突出一个区域：指令／结果／轨道／装置。Agent 提交、目标范围、模型名和 **Apply changes** 至少各有一次清晰可读的镜头。
- 保留真实等待的开头和结果出现的结尾，中间跳切；字幕 `Processing time shortened`（处理等待已剪短）。复用预先完成的结果则标 `Previously generated result` 或 `Previously analyzed result`，不能剪成“几秒完成所有推理”。
- 下述秒数是**成片占用时间**。现场录制可以更长，每镜头前后留 2–3 秒，录音过程另见 Demo 4 的连续镜头要求。

## 2. 精确分镜、英文稿与中文对照

### 开场：00:00–00:24

这三句旁白连起来是一段产品简介。动画用后续真实录屏的裁切画面制作，先拍 Demo 再做片头。

| 镜号／时间 | 画面、操作与后期 | English voice-over | 中文对照／声音 |
|---|---|---|---|
| I01 · 00:00–00:06 | 纸白背景，树乐师 Logo 线条揭示，出现 `E-musician` 和小字 `易乐师`；第 3 秒淡入 `github.com/TonyWang2182/E-Musician`。 | Meet E-musician, a music workspace with a built-in assistant. | 认识一下 E-musician：一个内置音乐助手的创作工作区。BGM 从第一帧进入，旁白稍后开始。 |
| I02 · 00:06–00:14 | Logo 缩至角落；Agent 侧栏、真实生成候选、四轨分离结果依次进入画面。后期短标签：`Create` → `Separate` → `Analyze`。 | Describe an idea, compare generated music, and turn audio into stems, chords, and editable notes. | 描述想法、比较生成的音乐，再把音频转成分轨、和弦和可编辑音符。 |
| I03 · 00:14–00:24 | 依次展示编曲区、和弦轨、展开卷帘、Drum Rack；最后落到 Demo 1 的干净工程。角标 `Generate · Analyze · Record · Edit`。 | Then keep creating with native devices, plug-ins, and recording, all in the same project. | 接着使用原生装置、插件和录音，在同一个工程里继续创作。24 秒处淡出片头 BGM。 |

### Demo 1：00:24–01:40，同一想法的两个版本

建议使用有短句人声的 90 BPM hip-hop / neo-soul 提示词，方便四声部都有可辨识内容。完整可复制指令在第 3 节。若改用之前的 UK jungle 纯器乐提示词，vocals 可能接近静音，应如实展示；不要为凑四轨把另一段人声混进去。

| 镜号／时间 | 画面、具体操作与后期 | English voice-over | 中文对照／声音 |
|---|---|---|---|
| G01 · 00:24–00:33 | 章节小字 `01 / From an idea to four stems`。显示工程 90 BPM、4/4；展开 Agent，粘贴相同音乐正文的 YuE2 请求，Scope=Whole project。只高亮模型、时长与音乐描述，不要求观众读完长文本。 | Start with one musical idea. I’ll use the same brief with YuE2 and ACE-Step. | 从一个音乐想法开始。我会把同一段描述交给 YuE2 和 ACE-Step。 |
| G02 · 00:33–00:43 | 两次真实请求的短镜头：YuE2 任务→候选；ACE 任务→候选。用匹配剪辑切换，显示两个真实模型名和等待省略字幕。两次请求顺序执行。 | The assistant sends each request to the chosen model and brings back a result to audition. | 助手分别调用选定的模型，把结果带回来供我试听。 |
| G03 · 00:43–00:49 | YuE2 候选 Preview，显示 `YuE2 / Preview`。选有代表性的约 6 秒，不展示不存在的双模型比较面板。 | — | **6 秒 YuE2 原声，无旁白、无额外 BGM。** |
| G04 · 00:49–00:55 | ACE 候选 Preview，显示 `ACE-Step / Preview`；与前段试听音量接近。 | — | **6 秒 ACE 原声。** 仅为两个创意版本，不标“客观胜者”。 |
| G05 · 00:55–01:01 | 选择实测更适合的候选，拍到真实导入方案和 **Apply changes**，音频出现在编曲区。默认剪辑脚本按选择 ACE 拍，若选 YuE2 只换结果镜头。 | I’ll keep this version and add it to the timeline. | 我保留这个版本，把它加入时间线。 |
| G06 · 01:01–01:10 | 选中刚导入的完整音频 clip，Scope=Current selection；发送 SCNet 指令。任务→四声部候选，用一次等待跳切。 | Now I’ll ask the assistant to separate it into drums, bass, vocals, and other sounds. | 现在让助手把它分成鼓、贝斯、人声和其他声音。 |
| G07 · 01:10–01:16 | 审阅四轨导入方案，点 **Apply changes**；显示四条对齐波形，保留并静音原始混音。四轨按 drums、bass、other、vocals 整理顺序，准备播放。 | All four stems arrive together, aligned with the source. | 四个声部一起进入工程，并与原音频对齐。 |
| G08 · 01:16–01:32 | 播放事先试听选好的连续段落，按小节逐个解除 Mute：`Drums` → `+ Bass` → `+ Other` → `+ Vocals`。每次加入用轨道色高亮。 | — | **16 秒声部叠加，无旁白。** 90 BPM 下每小节约 2.67 秒；四阶段各约一小节，余下约 5 秒听完整合奏。进场跟真实音乐强拍，不硬凑秒点。 |
| G09 · 01:32–01:40 | 拉回编曲全景，四轨真实波形可见；短暂选中一个声部，显示它是普通可编辑音频 clip。 | I can now work with each part separately, inside the same project. | 现在，每个声部都可以在同一个工程里独立编辑。 |

**关键拍法：**分离结果是一次导入四轨；“逐段加入”体现为播放时逐层开声，不是模型依次生成四次。四个 clip 的起点不移动，原始混音保持静音，避免声音翻倍。若需做正式渐进编曲，可另在副本中裁切各声部的进入点，但本片用 Mute 演示更直观。

### Demo 2：01:40–02:32，让分析进入编曲

素材用 John Mayer 的 New Light。先从原曲选出和声与鼓都清楚的连续 15–25 秒，**整理成独立 clip 后再分析**；整块选中才能授权 Warp。实际摘段起止和标签在彩排时确定，不预填推测的 BPM 或和弦。

| 镜号／时间 | 画面、具体操作与后期 | English voice-over | 中文对照／声音 |
|---|---|---|---|
| A01 · 01:40–01:47 | 章节 `02 / Understand and align audio`；独立 New Light 工程，显示源 clip。角标 `John Mayer — New Light`；播放选定短句。 | — | **7 秒原曲片段**，先让观众知道分析的是哪段声音。 |
| A02 · 01:47–01:59 | 选完整摘段，Agent 请求 Cloud / ChordMini 和弦分析。拍到指令、任务和真实标签候选；等待跳切。 | With New Light, I’ll ask the assistant to identify the chords in this section. | 以 New Light 为例，我让助手识别这一段的和弦。 |
| A03 · 01:59–02:08 | 点 **Apply changes**；放大新和弦轨与下方源波形，播放头经过至少两个实际标签。 | I review the result, then add a chord track alongside the audio. | 我先检查结果，再把和弦轨加入音频旁边。不要字幕虚构和弦名。 |
| A04 · 02:08–02:19 | 重新选源音频整块，Agent 请求 Local / Beat This! 节拍与首拍分析、对齐方案。展示检测 BPM、拍号、首拍及目标工程 120 BPM；确认无误后 **Apply changes**。 | Next, I check the detected tempo and first downbeat, then align the clip to the project. | 接着检查识别出的速度和首拍，再让片段对齐工程。 |
| A05 · 02:19–02:25 | 打开 Source，特写真实 **Warp on / Source BPM / Target BPM**；回到首拍和小节线，和弦轨保持对应位置。这里不重复点击一次 Warp Apply。 | Warp adjusts the timing while preserving the pitch. | Warp 调整时长，同时保持音高。这里不使用“绝对无损”的描述。 |
| A06 · 02:25–02:32 | 同一短句匹配剪辑，`Original` 约 3 秒 → `Aligned to project` 约 4 秒。后段看得到播放头与网格，可加节拍器检查拍点。 | — | **7 秒原声 A/B**。保留原调；片段不要用明显不同音量制造“改善”。 |

**关键拍法：**本版本的 Align audio／Agent 对齐方案已经同时处理固定比例保音高拉伸与首拍位置。Source 镜头是展示已应用状态，不是第二次加工。先导入的来源关联和弦会跟随相应时间映射，彩排仍需逐个检查。若首拍或半倍／倍倍速度识别错误，先放弃旧 Agent 方案，把核对后的 BPM／首拍交给 Agent 重新提出方案，再审核应用；只改 Beats 面板输入框不会更新已经冻结的旧方案。也可手动修正后点 Align audio，但镜头须如实显示为手动修正。不能声称任意曲目一键准确对齐。

### Demo 3：02:32–03:06，把钢琴音频变成可编辑音符

| 镜号／时间 | 画面、具体操作与后期 | English voice-over | 中文对照／声音 |
|---|---|---|---|
| T01 · 02:32–02:38 | 章节 `03 / Piano audio to MIDI`；打开 Tea for Two 分轨副本，选 `Separated / piano` 中独立摘段，其他轨静音。角标 `Previously separated piano stem`。 | Here’s a piano stem from Tea for Two. | 这是 Tea for Two 的一条钢琴分轨。后约 2 秒留钢琴原声。 |
| T02 · 02:38–02:48 | Agent 请求 Cloud / TransKun 转录；展示真实任务和候选。等待跳切，审阅后 **Apply changes**。 | TransKun turns the piano performance into MIDI that I can inspect and edit. | TransKun 把钢琴演奏转成可以检查和编辑的 MIDI。 |
| T03 · 02:48–02:56 | 新 MIDI clip 出现，双击并展开卷帘；展示真实音符与力度。新轨已按操作流程加载经过验证的钢琴音源。 | The notes appear in the piano roll, ready to play through a piano instrument. | 音符出现在钢琴卷帘里，可以通过钢琴音源播放。 |
| T04 · 02:56–03:02 | 同位置 A/B：`Piano stem` 3 秒，`Transcribed MIDI` 3 秒；播放 MIDI 时原钢琴分轨静音。 | — | **6 秒原声对比。** 比较音高与节奏，不暗示能还原原钢琴的音色。 |
| T05 · 03:02–03:06 | 选一个实际需要修正的音符，调整长度或位置；若无需修正，就演示一次小改动并 Undo。 | I can refine individual notes. | 我还可以继续调整每一个音符。 |

不展示尚不存在的完整五线谱排版，也不把 Keyboard.mp3 的旧转录结果换名冒充 Tea for Two。模型返回了踏板事件才可以附加相应字幕，本片不必专门讲踏板。

### Demo 4：03:06–03:48，回到真正的制作过程

自制 90 BPM / 4/4 hip-hop 工程。提前准备鼓与贝斯底，留出真正待录的键盘和人声轨。建议短句 `Find the groove, make it move.`（找到律动，让它动起来）。下面 MIDI 和人声两段是必须保留的**连续过程镜头**。

| 镜号／时间 | 画面、具体操作与后期 | English voice-over | 中文对照／声音 |
|---|---|---|---|
| P01 · 03:06–03:12 | 章节 `04 / Make it your own`；下栏打开 Drum Rack，点击垫上三角形或双击鼓垫，试听 kick／snare／hat。 | Build the beat with Drum Rack. | 用 Drum Rack 搭起鼓组。后半留鼓点原声。 |
| P02 · 03:12–03:17 | 切 Sampler，展示真实波形，调整采样起点或 Release，按键试听。 | Shape a sample into an instrument. | 把一段采样变成可演奏的乐器。保留短试听。 |
| P03 · 03:17–03:21 | 打开已预加载、已通过本机彩排的第三方 VST3 音源窗口，按一下琴键有声音，再收起。 | Add a tested plug-in. | 加入经过验证的插件。角标用实际插件名；不写“All plug-ins supported”。 |
| P04 · 03:21–03:30 | **不中断**：镜头开头能看到目标 MIDI 轨已 Arm；点击全局 Record → 一小节预备拍 → 弹两小节 → Stop。录屏角落可加真实手部机位。 | — | **9 秒 MIDI 实录过程。** 90 BPM 下一小节预备拍约 2.67 秒，两小节演奏约 5.33 秒，其余约 1 秒停止；确实生成新的 MIDI clip。 |
| P05 · 03:30–03:40 | **不中断**：只给人声音频轨 Arm，点 Record → 一小节预备拍 → 录两小节短句 → Stop。拍到输入电平和新波形；手部／麦克风小窗可选。 | — | **10 秒人声实录过程。** 相同预备拍与两小节结构，最后留约 2 秒停止和波形完成。不要用提前录好的波形替代这个过程。 |
| P06 · 03:40–03:48 | 关闭 Arm，回放刚录的 MIDI 和人声；下栏掠过真实 EQ／Compressor 装置，回编曲全景，Ctrl+S。 | Record, edit, and keep building. | 录下来、编辑它，再继续创作。旁白约 2 秒，其余听新录的合奏。 |

**演奏安排：**P04 可录 Sampler Keys 或已验证的钢琴插件轨，避免临时更换音源；P05 用耳机监听，其他轨取消 Arm，麦克风只录目标输入。若使用声卡硬件直通监听，软件监听关闭，避免双重监听。录屏捕获必须实测能收到 ASIO 输出和输入，不能仅凭画面电平判断成片有声音。

### 结尾：03:48–04:00

| 镜号／时间 | 画面、操作与后期 | English voice-over | 中文对照／声音 |
|---|---|---|---|
| O01 · 03:48–03:54 | 最后一段合奏延续，编曲区缩成细线，过渡为树乐师 Logo；出现 `E-musician / 易乐师`。使用片头同一动效反向收束。 | From the first idea to the next take. | 从第一个想法，到下一次录制。 |
| O02 · 03:54–04:00 | Logo 与代码网址静止至少 4 秒：`github.com/TonyWang2182/E-Musician`；短句 `Explore the code. Try it. Share feedback.`。二维码可后期生成并实扫。 | Explore the code, try E-musician, and share what you make. | 查看代码，试用 E-musician，分享你的作品。BGM 落在自然尾音。 |

网址是项目入口。视频简介另给**当时实际发布的演示构建／分支**，不假定默认 main 已含本片所有功能，也不承诺云端推理免费开放。

## 3. 可以直接复制的英文 Agent 指令

下列是拍摄用输入；实际自然语言调用须先彩排。每次只提交一个任务，选择范围在提交前核对。Agent 返回候选／方案不等于已经修改工程：先 Preview／审阅，再点 **Apply changes**。原生面板对应按钮是 Add track(s)、Add MIDI track、Add chord track，拍 Agent 流程时不要把它们混称为同一个按钮。

### Demo 1：两次生成，相同音乐正文

工程先手动设为 **90 BPM / 4/4**，播放头放起点；Scope=Whole project。预算约 32 秒，不要求两个模型精确等长。以下仅模型名不同，其他要求保持相同。

**第一次：YuE2**

```text
Use YuE2 to generate about 32 seconds of music at the current project tempo and time signature. Music brief: warm hip-hop and neo-soul, dusty punchy drums, a rounded bass line, mellow electric piano chords, subtle vinyl texture, and a short soulful vocal hook. Keep the four parts clearly audible. Lyrics: "Find the groove, let it flow / Take a breath, make it grow." Use the current playhead position. Let me preview the result before adding a track.
```

**第二次：ACE-Step**

```text
Use ACE-Step 1.5 XL to generate about 32 seconds of music at the current project tempo and time signature. Music brief: warm hip-hop and neo-soul, dusty punchy drums, a rounded bass line, mellow electric piano chords, subtle vinyl texture, and a short soulful vocal hook. Keep the four parts clearly audible. Lyrics: "Find the groove, let it flow / Take a breath, make it grow." Use the current playhead position. Let me preview the result before adding a track.
```

中文意思：用当前工程速度和拍号生成约 32 秒温暖的 hip-hop / neo-soul，包含清楚的鼓、贝斯、电钢琴和短人声 hook；生成后先试听，再决定是否入轨。歌词意为“找到律动，让它流淌／深吸一口气，让它生长”。

两个请求使用同一正文和预算，但模型的音乐实现、长度和结尾可能不同；这段是创意比较，不是准确率或速度跑分。若听感检查发现截断，保留记录，展示时选完整短句，不把截断结果称为完整成曲。

**保留、选择和分离**

1. 先完整录下 YuE2 的任务与 Preview，保存真实候选／结果标识；再做 ACE。两次比较试听不同时播放。
2. 当前 Agent 方案不保证长期保留两个待应用卡片。最稳妥是两版分别录下真实 Preview／Apply changes，把**已接受的音轨和完整 assets**保存到 `D1-YuE2`、`D1-ACE` 项目副本，再从所选副本继续。只保存含未接受候选的工程，不保证重开后候选还在。不要为补拍盲目重新生成另一首。
3. 确定采用哪一个；G05 使用该结果真实接受入轨的录屏。若希望当场找回首次结果，原生 Generate 面板的 **Recent generations** 可查看历史候选；要继续拍 Agent 接受，就按真实结果标识让 Agent 重新提出导入方案并审核。若直接点原生 Add track，则如实表现为手动导入。不能把打开旧工程剪成一次新的 Agent Apply。最终分离工程中只播放所选源，另一版本保存在副本即可。
4. 选入轨后的完整 clip，Scope=Current selection，发送：

```text
Use cloud SCNet to separate the selected audio clip into vocals, drums, bass, and other. Keep the original audio. Prepare the four tracks for review before adding them.
```

中文：用云端 SCNet 将选中音频分成四个声部，保留原始音频，先准备四轨导入方案供审阅。

5. 审阅→Apply changes；停止播放，原音频 Mute。整理四轨名称、颜色和可见高度；先只开 Drums，再按真实小节开 Bass、Other、Vocals。录制连续叠加原声，保留一份四轨全开的混音对照。

### Demo 2：和弦、节拍与 Warp

独立项目，工程 **120 BPM / 4/4**；分析素材应是已经整理好的 15–25 秒独立 New Light clip，完整选择该 clip，Scope=Current selection。

```text
Use cloud ChordMini to identify the chords in the selected audio clip. Let me review the labels before adding a chord track.
```

中文：用云端 ChordMini 分析选中片段的和弦，先检查标签，再加入和弦轨。

接受和弦后重新点选源音频整块，发送：

```text
Use local Beat This! to analyze the selected audio clip's tempo and downbeats. Prepare a plan to align the entire clip to the current project tempo, preserving pitch and keeping the project BPM and time signature unchanged. Preserve the opening audio. Show me the detected tempo and first downbeat before applying.
```

中文：用本地 Beat This! 分析速度和小节首拍，准备把整个片段对齐当前工程的方案；保持音高、工程速度和拍号，保留开头音频，应用前展示识别结果。

操作顺序：核查检测值→必要时放弃旧方案，带校正后的半倍／倍倍速度或首拍值重新提方案→审阅目标→Apply changes→Source 查看 Warp→与原版副本 A/B。修改 GUI 字段后不能直接接受未更新的旧方案。不要把关闭 Warp 时界面默认的 Source BPM 当成识别结果。目标首拍应能容纳原片段开头，不能为了对齐而偷偷删前奏。

若所选摘段检测速度恰好接近 120、拉伸变化很小，彩排时可把**这个演示工程**目标改成经检测速度的约 95%，整段镜头保持同一目标值，旁白无需改词。不对已有多轨作品临时改全局速度。

### Demo 3：钢琴转录

在分轨副本中，从 `Separated / piano` 选出 12–20 秒短句，先整理成独立 clip；Scope=Current selection。

```text
Use cloud TransKun to transcribe the selected piano audio to MIDI. Preserve any pedal events the model returns. Let me review the notes before adding the MIDI track.
```

中文：用云端 TransKun 把选中钢琴音频转成 MIDI，保留模型实际返回的踏板事件，先检查音符再导入。

操作顺序：候选→审阅→Apply changes→给新 MIDI 轨挂已测试的钢琴音源→双击 clip→展开卷帘→原钢琴与 MIDI 分别试听→单音编辑。**MIDI 本身不会发声**，也不包含原音源音色。若使用旧结果补拍，保留旧结果标识并注明 Previously analyzed result。

## 4. 提前准备的工程和素材

### 已找到的素材位置

本轮只读取路径和工程清单，未试听这些素材，也未证明其可公开发布范围。

| 素材 | 已有位置／来源 | 需要做什么 |
|---|---|---|
| 认可的树乐师 Logo | `E:/MusicAgent&DAW/worktrees/audio-analysis/assets/brand/yi-yue-shi-logo.png` | 使用原件，复制到剪辑素材目录；导出片头／片尾动效，不另画替代 Logo |
| New Light 原曲 | `E:/E-musician/test-projects/test9-newlight/New Light()/New Light.mp3` | 选一个和声与鼓清楚的短段，记录精确起止；保留完整原文件不改动 |
| Tea for Two 原曲 | `E:/E-musician/test-projects/test6-MIR task 1/tea for 2.mp3` | 仅作来源与原曲对照，Demo 3 直接使用已有钢琴分轨 |
| Tea for Two 六分轨项目 | `E:/E-musician/test-projects/test7-MIR task 2/T42-2.emproj` | 已读到 `Separated / piano` 等六条分轨及旧 `Transcribed MIDI`。另存演示副本；旧 MIDI 不充当新 TransKun 输出 |
| 上述项目的钢琴资产 | `E:/E-musician/test-projects/test7-MIR task 2/T42-2.assets/a3ae0af6ad564f97a02099b556276e7c/2376f6baa7fe420d9f084da3379dfc2d.wav` | 来源由工程 `analysis_role=piano` 和 asset_id 对应；先试听串音和音量，再选转录短句 |
| 另一个已有 T42 工程 | `E:/E-musician/test-projects/test8-demo（T42）/test8-demo.emproj` | 也有六分轨和旧 MIDI，可作参考；不要误当本次需要新做的 hip-hop Demo 4 |
| 鼓与采样素材 | `E:/E-musician/test-projects/test5-sampler&rack/` | kick→36、snare→38、closed hat→42、open hat→46；Sampler 的 `07-piano-C4.wav` 可设根音 MIDI 60。位置以本次 pad 映射为准 |
| 项目网址 | `https://github.com/TonyWang2182/E-Musician` | 片头／片尾用短网址；发布前检查访客可见性、实际演示版本入口与二维码 |

建议拍摄资产存放在以下**新目录**；这是准备结构，本轮不复制大文件、不新建音乐工程：

```text
E:/MusicAgent&DAW/demo-video/2026-11-12/
  01-projects/       D1-YuE2 / D1-ACE / D1-stems / D2-NewLight /
                     D3-TeaForTwo / D4-HipHop（各自工程及完整 assets）
  02-source-audio/   原曲摘段、自录人声、鼓与采样副本
  03-model-results/  真实生成音频、四 stems、MIDI、和弦与节拍结果记录
  04-screen-raw/     按镜号保存未剪录屏
  05-audio-raw/      DAW 原声、英文旁白、BGM、录制 take
  06-graphics/       原 Logo、章节标题、二维码、片头片尾
  07-edit/           剪辑工程、字幕、工程引用的素材
  08-export/         最终视频与字幕
  TAKES.md          每条任务／录屏／模型结果的对应记录
```

### 四个演示工程预设

| 工程 | 拍摄前状态 | 应保留的节点副本 |
|---|---|---|
| D1 | 90 BPM，4/4；音乐正文固定；两个模型候选真实试听完成；选一个有可辨人声的连续段 | 生成前、YuE2 结果、ACE 结果、四轨导入后、叠加试听准备好 |
| D2 | 120 BPM，4/4；New Light 独立摘段；无旧和弦轨冒充新结果 | 原始、和弦已入轨、节拍待应用、对齐完成；保存原版 A/B |
| D3 | 仅保留本次要展示的钢琴摘段和必要来源；准备好可用钢琴音源 | 转录前、真实 TransKun 候选、MIDI 导入并可播放；保留旧 MIDI 仅作参考 |
| D4 | 90 BPM，4/4；8–16 小节自制 hip-hop；Drums／Bass／Sampler Keys／Plugin Keys／Vocal Take 命名清楚、轨道染色；两条待录目标轨确实空着 | 拍摄前空 take、MIDI 实录后、人声实录后、最终混音；保留原始录音 take |

## 5. 必须提前录制的素材清单

先完成一次真实全流程彩排，再录干净镜头。云端生成和分析不必在剪辑时重跑，但每个展示的结果都必须能对应原始任务。

| 素材包 | 必须拍／保存的内容 | 在成片中的用途 |
|---|---|---|
| V01：界面素材 | 完整工作区、Agent 开关、Library、真实和弦轨、卷帘、Rack，各 5–8 秒干净录屏 | 开场动画素材，由后期裁切组合 |
| V02：YuE2 | 输入→提交→真实状态→候选→Preview；原始生成 WAV、实际长度、任务 ID／模型名、提示词 | G01–G03；6 秒试听另存无旁白原声 |
| V03：ACE | 同一正文、同一工程速度与预算的第二次真实任务；同样保存候选与原声 | G02、G04–G05；6 秒试听，与 YuE2 音量接近 |
| V04：四轨分离 | Agent 请求→SCNet 结果→Apply changes→四轨；连续录一遍逐层开声和一遍完整合奏 | G06–G09；尤其保留不间断的 16 秒叠加段 |
| V05：New Light | 原音短句、ChordMini 请求／标签／导入、Beat This! 检测／审核／应用、Source Warp 状态 | A01–A05；字幕中的值来自实际结果 |
| V06：Warp A/B | 同一音乐短句的原版和对齐版各至少 8 秒，响度近似，保存对应工程 | A06；后期各取 3–4 秒 |
| V07：Tea for Two | 钢琴原声、TransKun 调用、候选、导入、加载音源、卷帘、音符编辑 | T01–T05；钢琴源与 MIDI 各留至少 8 秒原声 |
| V08：原生装置 | Rack 三个 pad 的试听、Sampler 起点或包络调整前后、EQ 与 Compressor 短镜头 | P01–P02、P06；不能只拍静态旋钮 |
| V09：第三方插件 | 选定一款实测可用的 VST3，打开真实窗口、按键发声、收起 | P03；不需要在 4 秒内展示整个扫描安装过程 |
| V10：MIDI 实录 | 从 Record、预备拍、键盘动作到 Stop 与新 clip 的完整连续录屏；可加同步手部镜头 | P04；不能只放最终钢琴卷帘 |
| V11：人声实录 | 从 Record、预备拍、演唱／念句到 Stop、新波形的完整连续镜头；录到真实麦克风输入 | P05；与 DAW 原声对齐 |
| V12：收尾和声音 | 新录片段合奏、保存动作；Demo 4 无人声 BGM；英文旁白干声；Logo 原件 | P06、片头片尾、最终混音 |

**录制顺序建议：**先 D4（它提供 BGM 和录音素材）→ D1 两次生成与分离 → D2 → D3 → 补界面空镜 → 录旁白 → 做动画 → 剪成 240 秒。所有原录屏保留，不用反复运行收费任务来补“等待画面”。

## 6. 开拍前要测试好的功能

以下全部是**待本次人工勾选**。历史自动测试通过只能作为参考，不能代替当前云端可用性、音乐质量和真实录音检查。

| 检查项 | 通过标准 | 状态 |
|---|---|---|
| 版本与语言 | 启动 0.13.2；Settings → Language → English；新 Agent 对话、方案、状态为英文；M/S/R 可读 | [ ] |
| 录屏与音频 | 试录 10 秒，回看有 UI、有 DAW 声音、声画同步；ASIO 输出和麦克风都真正进录制通道，没有重复监听 | [ ] |
| 画面布局 | 1080p 成片中轨名、模型、Apply changes 可读；打开 Agent／下栏不遮关键按钮 | [ ] |
| Agent 上下文 | Whole project 与 Current selection 切换正确；读取已有 BPM，不要求重复输入；目标 clip ID／轨道与画面一致 | [ ] |
| 两模型生成 | YuE2、ACE 分别实际调用成功；相同音乐正文和预算；可 Preview、可接受入轨，结果长度与截断已检查 | [ ] |
| 四轨分离 | 选定生成音频经 SCNet 得到四个真实 stem；四轨同步、可独立听；保留原音；没有混音叠加翻倍 | [ ] |
| Agent 接受／撤销 | 候选不会自动改工程；Apply changes 后可见结果，一次 Undo 可撤销相应导入；再恢复并保存 | [ ] |
| New Light 和弦 | 标签来自 ChordMini 实际输出，能加入和弦轨；至少人工听查两个转换点，不宣称全曲准确率 | [ ] |
| 节拍／首拍 | Beat This! 本地可用；BPM／拍号／首拍经过试听复核；需要修正就明确修正 | [ ] |
| Warp | 整个 clip 获授权；一次对齐后源音频、首拍、小节线与和弦位置对应；音高和音质听查可接受，可 Undo | [ ] |
| Tea for Two 转录 | 输入确为已有钢琴分轨；TransKun 真正运行；新 MIDI 可见、挂乐器后能播放，检查漏音／八度／过长音 | [ ] |
| Rack／Sampler | 下栏能显示波形；pad／样本可独立试听；实际调参有听得出的效果；载入过程不挡住拍摄操作 | [ ] |
| 插件 | 选一款已通过本机实际加载、可见窗口、播放、保存重开测试的 VST3；不依赖仍未解决的八项插件问题 | [ ] |
| MIDI 录音 | 正确键盘输入，仅目标轨 Arm；一小节预备拍→两小节录入→停止有新音符→取消 Arm 后回放正常 | [ ] |
| 人声录音 | M-Audio 实际连接；麦克风输入正确、无明显削波／反馈；录后有新波形，回放能听到本次 take | [ ] |
| 成片用工程保存 | 四个演示工程及 assets 保存重开正常；已接受的音频／MIDI／和弦仍在；保存不会改原始测试项目 | [ ] |
| 素材和公开入口 | New Light、Tea for Two、BGM、插件画面等的公开展示范围已确认；项目网址与实际演示版本链接可访问 | [ ] |
| 结果可追溯 | 每个模型任务对应输入范围、结果 ID、实际文件和录屏；只剪等待，不拼接伪成功流程 | [ ] |

**失败时怎么处理：**保存错误与任务记录，修复后再拍；若仅需补镜头，用同一真实结果补拍并明确预生成／预分析，不把手动按钮操作说成 Agent 成功调用。当前离线探针通过不等于所有第三方插件或 M-Audio 实际录音已验收。没有通过关键录音检查，不用成品音频替代“实录过程”。

### 每次模型任务和 take 的最小记录

复制到拍摄目录的 `TAKES.md`，不记录密钥或 SSH 密码：

| 镜号 | 工程／版本 | 输入文件与范围 | 模型／位置 | 提示词版本／任务或结果 ID | 真实总等待 | 结果路径／录屏路径 | 听感／内容检查 |
|---|---|---|---|---|---|---|---|
| 例如 G02 | D1 / 0.13.2 | 生成任务，无输入音频 | YuE2 / Cloud | 本稿 v1；实际 ID 待填 | 实际秒数 | 待填 | 是否完整、是否有可用四声部 |

真实等待记录用于追溯，不一定出现在宣传字幕中；若展示耗时，标明是否包含加载、上传和下载。

## 7. 交给剪辑的最终检查

- [ ] 总时长 240 秒；章节边界为 00:24、01:40、02:32、03:06、03:48、04:00。
- [ ] 六段标题与中英翻译一致；旁白按镜号单独录制，试听段没有旁白盖住音乐。
- [ ] G03／G04 各 6 秒、G08 16 秒、A06 7 秒、T04 6 秒纯试听；保住这些时间，再压缩菜单停顿。
- [ ] P04、P05 保留 Record→预备拍→演奏／人声→Stop 的连续过程；可裁画面、加机位，不能剪掉实际录制过程而假装连续。
- [ ] 推理等待跳切标记清楚；预先完成的结果不冒充本次实时生成；不显示推测的 BPM、和弦、音符或假波形。
- [ ] A/B 音量近似；模型试听与录音段无额外 BGM；所有音频无意外叠加和削波。
- [ ] 模型名／目标轨／确认入轨按钮清晰；具体错误、终端、密钥配置、账号余额不进入演示画面。
- [ ] 片头 Logo 与片尾同款；最后网址至少静止 4 秒；二维码实际扫描；视频简介附实际演示版本。
- [ ] 保存最终 mp4、独立英文字幕、可选中文字幕、剪辑工程和完整原始素材。不要只留下最终成片。

## 8. 功能依据与本稿边界

- [当前模型与操作分工](../review/2026-11-08-plugin-agent-stability/MODEL-MAP.md)：GPT/Kimi 为指令 Agent；本片实际音乐任务使用 YuE2、ACE、SCNet、ChordMini、Beat This!、TransKun。Warp 和原生装置是 DAW 处理。
- [七模型及节拍／Warp 人工流程](../review/2026-11-08-cloud-reconnect-ui/MODEL-TESTS.md)：任务候选、明确接受、试听与保存分开验收。
- [当前插件兼容矩阵](../review/2026-11-08-plugin-agent-stability/plugin/COMPATIBILITY.md)：45/53 为有界审计结果，不是任意插件保证；拍摄选定插件仍需实测。
- [品牌与界面规范](../../DESIGN.md)、[Logo 来源](../../assets/brand/README.md)：本片后期沿用现有设计。
- 代码核对：`scripts/music_agent/runtime.py` 每请求一次生成及方案流程；`scripts/music_agent/web/app.js` 的 Preview／Apply changes；`apps/desktop/EngineSessionWarp.inc` 对齐、Warp 与来源和弦映射。
- 旧[7 分 50 秒脚本](../review/2026-11-08-cloud-reconnect-ui/DEMO-SCRIPT.md)作为历史资料保留。本稿不包含新的模型部署、GUI 改造、运行性能测试或成片制作。
