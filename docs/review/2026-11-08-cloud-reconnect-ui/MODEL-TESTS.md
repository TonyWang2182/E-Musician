# 新克隆主机：模型与DAW人工测试清单

2026-11-08。目标：确认克隆后的环境、云端任务通路以及DAW导入与保存可用，并单独记录音乐质量。用户已克隆原数据，本轮无需从E盘重传模型。当前重连已确认九套环境的解释器、两个数据库完整性和固定服务版本哈希；补装了克隆机缺失的系统FFmpeg。七项模型能力已就绪，原生客户端经SSH隧道检查通过。本轮七模型已全部通过新主机真实短段推理、DAW接受/Undo/保存离线重开及渲染，见[结果](RESULTS.md)。以下人工操作、ASIO和音乐质量仍待验；不是把连通或原主机通过当作新主机推理通过。

## 测试前

1. 打开本轮交付的DAW，Settings → Language → English。另存为独立测试工程；先确认已有WAV/MP3播放有声音。
2. 确认当前云服务在线且七个模型显示可用。用 **Cloud** 明确选择云模型，避免Auto路由使测试对象不清楚；不要同时启动七项。
3. 前五个分析测试用8–20秒的清晰片段。Analyze → Options 设置 **Start / s**、**Length / s**；确认选择范围与素材名称。第一次包含模型加载，记录首次与后续耗时，不能把旧结果展示当新推理。
4. 基准素材：`E:/E-musician/test-projects/test9-newlight/New Light()/New Light.mp3`；钢琴用 `E:/E-musician/test-projects/test9-newlight/Keyboard.mp3`。这两个路径在编写清单时已确认存在。分析质量需要更长、多风格素材，先短测通路再扩展。
5. 执行期间播放少量已有轨道、拖动视图，观察DAW是否仍响应；记录声卡、采样率、缓冲区、轨道/插件数量。页面不卡与无爆音、模型推理成功与结果准确分别判定。

## 第一轮：七个云端模型

| 顺序 | 模型与手动入口 | 素材/配置 | 要看到什么 | 重点听/看什么 | 人工结果 |
|---|---|---|---|---|---|
| 1 | **SCNet**：Analyze → Separate → Cloud → scnet → Analyze | New Light的8–20秒、含人声和鼓的片段 | vocals/drums/bass/other四个候选；Listen能试听；Add tracks后四条普通音轨，原音频仍在 | 声部串音、鼓瞬态损失、水声伪影、低频缺失；各轨起止/长度对齐。SCNet此部署不是8声部或主唱/和声细分模型 | 待验 |
| 2 | **TransKun**：Analyze → MIDI → Cloud → transkun | Keyboard 8–20秒，最好含和弦、短音与踏板 | Add MIDI track后可见音符；真实返回的CC保留；给新轨挂Sampler/已验证乐器才能听 | 漏音/多音、八度错误、短音起点、长音尾部、踏板释放；音色不必与原钢琴一致。没有返回CC就不宣称恢复了踏板 | 待验 |
| 3 | **MuScriptor**：Analyze → MIDI → Cloud → muscriptor | 先复用Keyboard检查通路，再用清晰的钢琴+贝斯+鼓片段测多乐器 | 按实际输出形成乐器轨，保留乐器/通道和鼓信息 | 乐器是否混淆、节奏是否错位、音符是否挤成一团；当前导出力度为默认值，不能用“力度像原演奏”验收 | 待验 |
| 4 | **ChordMini**：Analyze → Chords → Cloud → chordmini | New Light中和声清晰的8–20秒 | 标签可预览；Add chord track后显示编曲和弦轨，可编辑和撤销 | 根音、性质、转位/斜杠与切换时间；短暂和弦抖动。当前固定170标签词表，不是任意爵士扩展和弦识别器；无置信度时不显示成100% | 待验 |
| 5 | **SheetSage2**：Analyze → Score → Cloud → sheetsage2 | 同一New Light片段，便于和前项对照 | Notes/Chords/Beats/Sections切换；Add score后保留实际分项；Saved score重读工程 | 旋律、和弦、拍点/段落是否合理；缺失分项如实为空。接受结果不自动改变工程BPM/拍号；Score当前不等于完整五线谱排版器 | 待验 |
| 6 | **ACE-Step 1.5 XL**：add... → Generate music… → ACE-Step 1.5 XL | Seconds=12；Lyrics空；短英文纯音乐描述；用工程BPM/拍号 | 完成后Preview有声音；Add track新增一条本地音轨；保留实际模型/长度 | 风格、乐器、人声禁用要求、节奏和音质；检查首尾、异常噪声/削波和是否接近要求，不把生成成功当精确BPM保证 | 待验 |
| 7 | **YuE2**：同一Generate面板切YuE2 | 与ACE相同描述，约12秒预算；先别做整曲 | 正确调用YuE2，得到可试听候选；查看实际时长与截断状态，再Add track | 秒数是预算，不保证精确12秒；结尾截断与自然结束必须区分。检查旋律/节奏连贯性；不能静默改用ACE来算通过 | 待验 |

通用生成描述可直接复制：

```text
Instrumental electronic groove at the project tempo, with tight drums, warm electric piano, rounded sub-bass, and a spacious mix. No vocals.
```

上述七项每项先验证“任务完成、真实结果、可导入”。音乐好不好另列评价，不要求首轮一段8秒材料证明整曲准确率。冷启动、传输、模型推理、导入耗时应分别记录，若界面只有总耗时则明确是总耗时。

## 第二轮：分析和编辑的完整流程

| 项目 | 操作 | 通过标准 |
|---|---|---|
| 节拍/首拍识别 | Analyze → Beats → **Local**，选择已登记的Beat This!，用节奏清楚的8–20秒片段；检查BPM、拍号与First / s，可做半倍/倍倍修正 | 拍线跟随实际强拍；不确定时可人工修正。它不属于上面的七个云模型，不能因云端在线便算此项就绪 |
| 对齐 | 对复核过的节拍候选点Align audio；再Undo | 首个小节拍对齐目标小节，前奏保留；工程速度不被该按钮暗改，Undo恢复。Use this tempo是明确改变工程速度的另一操作 |
| Warp | Source → Warp on；确认Source BPM，调整Target BPM或Follow tempo → Apply | 长度按比例变化、音高尽量保持、试听无明显异常；原素材仍在，可Undo并保存。它是固定比例的保音高处理，不保证绝对无损，也不支持任意Warp锚点曲线 |
| 本地备用算法 | 分别选Local的已安装HTDemucs、Basic Pitch和本地和弦基线 | 云端断开仍可用已安装本地模型；不同算法结果不要求一样。缺模型时明确不可用，不伪装成云端模型成功 |
| 未接受候选 | 任一模型生成候选后先不导入 | 原工程轨数、音乐数据不因候选完成而变化；候选来源与选择范围正确 |
| 接受与历史 | 接受一个结果→Undo→Redo，重复点击接受 | 整批导入一次撤销/恢复；重复接受不重复添轨 |
| 来源变更 | 候选待接受时移动原片段或改变相关来源，再尝试接受 | 提示来源已改变/需重算，不把旧结果错位套用 |
| 取消 | 另起一个短任务并点Cancel | 界面仍能操作；只有远端确认后才显示云端已取消，停止本地等待不能冒充远端停止 |
| 保存与离线 | 保存含生成音频、MIDI/CC、和弦和Score标记的工程；关闭，断开模型连接，重开 | 已接受资产可离线播放/编辑，分析内容保留；新模型任务则明确云端不可用。无需为此关闭或释放云实例 |

## 第三轮：Agent与英文界面

先选整条已有Compressor的轨，Scope=Selection，输入：

```text
On the selected track, set the existing Compressor threshold to -18 dB and its ratio to 3:1. Leave all other settings unchanged. Show me the changes before applying them.
```

检查目标和前后值→Apply changes→查看装置→Undo。然后各做一项生成与分析：

```text
Use cloud SCNet to separate the selected audio range. Let me preview the candidates before adding tracks.
```

```text
Use YuE2 to generate about 12 seconds of instrumental electronic music at the current project tempo and time signature. Let me preview it before adding a track.
```

- Agent应读取工程BPM、拍号、播放头和完整选区，不为已有的BPM反复追问；操作范围不能超出确认的目标。
- 任务状态、方案卡、进度、错误与确认按钮在English模式下使用英文。模型自然语言回答也检查英文；用户原始中文名字、歌词和明确要求的中文回答不应被篡改。
- 七个模型都需做真实手动短测；Agent首轮至少覆盖“原生装置编辑＋一次云分析＋一次云生成”。若要宣称每个模型均已通过自然语言调用，需按上表逐一替换模型执行，不可用手动或固定夹具结果代替。
- 错误复现时保存完整界面文字和大致时间；不要把密钥、SSH密码或私人歌词发进公开问题记录。

## 新样式人工短测

1. File菜单、轨道/片段/标尺右键菜单、模型/网格/语言下拉：浅色纸面、统一字体/行高/选中态，禁用项可辨认，长项不截断关键模型名，键盘方向键/Enter/Esc可用。
2. 改动一个测试工程后直接关闭窗口：Save changes?应与主界面风格一致。Cancel留在原工程；Save成功后才退出；另开测试副本验证Discard。保存被取消或失败不能丢掉未保存工程。
3. 当前DPI、缩窄与最大化各看一次，打开Agent后仍可找到Analyze/Cancel/导入按钮。真实英文状态变化之后再截图，不只看空白初始页。

## 结果记录模板

| 日期/时间 | DAW版本/提交 | 模型与位置 | 素材及起点/长度 | 成功/失败与耗时 | 候选/导入/保存 | 音乐质量与错误 | 任务或结果位置 |
|---|---|---|---|---|---|---|---|
| 待填写 | | | | | | | |

附记测试机器GPU、驱动、声卡、采样率、缓冲区与轨道/插件数量。新主机SSH连通、能力目录就绪、推理通过、DAW导入通过和人工听感是五种不同证据，分别记录。先通过短测再用整首New Light和Keyboard做长任务；整曲压力与音乐质量不能从短测推断。

相关：[视频脚本](DEMO-SCRIPT.md)、[0.13人工验收](../2026-11-07-hybrid-pipeline/MANUAL-CHECK.md)、[Agent验收](../2026-11-07-hybrid-pipeline/agent/MANUAL-CHECK.md)。
