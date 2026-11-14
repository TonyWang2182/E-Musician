# Agent 功能与模型清单

核对日期：2026-11-14。依据当前 Agent 工具、参数目录、本机非密钥设置及模型注册表。新克隆主机已通过原SSH密钥、固定部署文件、九套解释器和两个数据库检查，protocol 2服务已启动，七模型能力均返回available；DAW使用的同款SSH隧道检查通过，登记已刷新。证据见[CLOUD.json](CLOUD.json)、[CONNECTION.json](CONNECTION.json)。**本轮没有运行模型推理或验证语言模型账户额度**，用户自行测试音乐效果。

## 1. 一句话理解分工

**GPT／Kimi 负责理解指令和组织步骤；SCNet、TransKun、ACE 等音乐模型负责分析或生成；DAW 负责编辑、播放、装置处理和保存。** 当前是一位语言 Agent 调用多种工具，不是每个功能各有一个聊天 Agent。切换 GPT／Kimi 不会自动替换音乐模型。

## 2. Agent 现在能操作什么

| 类别 | 已开放操作 | 使用要点 |
|---|---|---|
| 工程和轨道 | 读取 BPM、拍号、播放头与选择；修改 BPM；新建音频／MIDI 乐器／总线轨；改轨名、颜色、音量、声像、Mute／Solo | 新建轨、全局速度需要 Whole project；选中单个音符不能授权整轨修改 |
| 片段编辑 | 新建 MIDI clip；复制、移动、跨已授权轨道移动、缩短裁剪、删除已有 clip | 裁剪只在原范围内缩短；含控制器事件的 MIDI clip 当前不支持这条裁剪动作 |
| MIDI 音符 | 读取音符，添加／删除、移位、移调、改时值、改力度、量化起点 | 必须有明确授权目标；每个目标片段最多完整读取 2,000 音符；量化网格支持到 1/16384 |
| 原生效果器 | 新增、读取、修改 EQ Eight、Compressor、Stereo Delay、Reverb、Auto Filter 的已开放参数；支持逐参数修改 | 轨道和主轨可用；主轨操作需要 Whole project。未修改参数保持原值 |
| Sampler／Drum Rack | 读取已加载采样的状态；修改垫音量、静音、Attack、Release、One-shot；Sampler 根音和采样起止 | **仅 Whole project，每个方案只能一个采样器／鼓组动作；不支持让 Agent 创建这些装置或指定路径加载新采样**。先由用户加载采样 |
| 基础混音 | 批量读取轨道音量、声像、已有原生效果器及路由／发送／自动化摘要，提出有限的音量／声像／原生效果器调整方案 | 路由、发送和自动化目前在这里是**读取信息**，不是可写动作。没有全曲听音、LUFS、参考曲匹配或自动母带能力 |
| 音源分离 | 选择适用本地／云端模型，分析所选音频，查看候选，提出分轨导入方案 | SCNet 为四声部；HTDemucs-6s 为六声部；结果一次接受后形成普通音轨 |
| 音频转 MIDI | 调用 TransKun、MuScriptor 或 Basic Pitch，查看音符等真实输出，导入新 MIDI 轨 | MIDI 要挂乐器才发声；不能恢复原商业插件音色 |
| 和弦 | 调用 ChordMini／本地算法，查看候选并建立和弦轨；读取、修改已有和弦区域 | 标签是待检查的分析结果，不是正确率保证 |
| 节拍与 Warp | 调用 Beat This!，检查 BPM／拍号／首拍；保持工程速度并拉伸对齐音频，或让工程采用音频速度；读取和设置音频 Warp | Warp 需授权完整 clip；仅固定比例保音高拉伸。采用音频速度影响全工程，需要 Whole project；当前自动拍号应用支持 3/4、4/4 |
| 综合分析 | 调用 SheetSage2，按实际结果读取音符、和弦、拍点、结构并提出导入 | 不是完整五线谱编辑／排版功能 |
| 音乐生成 | 调用 ACE-Step 或 YuE2，用音乐描述／歌词生成，试听候选，提出新音轨导入方案 | 默认读取工程 BPM／拍号／播放头，未指定时长通常为 20 秒；每次 Agent 请求一次生成，双模型比较分两次请求 |
| 过程管理 | 显示任务进度、取消模型任务、审阅方案、Apply changes 后回读、Undo this change | 只有远端确认后才能认定云任务已取消；已接受资产保存到本地工程，未接受候选不保证跨会话恢复 |

**统一操作方式：**选择目标 → 设置 Scope → 输入要求 → 检查方案／试听 → **Apply changes** → 回放确认，必要时 **Undo this change**。每份普通编辑方案最多 16 个动作；大工程需要分批处理。

当前 Agent 还不能直接开始人声／MIDI 录音、选择声卡／ASIO、操作任意第三方插件 GUI 或预设、自动配置复杂路由与发送、任意写自动化曲线、替代 File 菜单完成通用文件管理。这些要区分“DAW 手动已有能力”和“Agent 已开放接口”。分析、生成、参数修改不能据此扩展成任意电脑操作。

## 3. 指令语言模型

| 服务 | 当前项目状态 | 负责什么 |
|---|---|---|
| OpenAI | 适配器已实现；本机当前选中 **gpt-5-mini / high** | 理解指令、读取授权工程上下文、选工具、提出编辑或模型任务方案 |
| Kimi | 适配器已实现；本机保存的模型偏好为 **kimi-k2.6** | 同类指令与工具调用，可在已配置服务间切换 |
| Anthropic、Google Gemini、本地兼容服务 | 只有预留服务入口，适配器未实现 | 当前不能据此发起请求 |

Kimi 代码选项另含 `kimi-k3.1-pro`，但本机没有选用、本次也未验证它，不把菜单项当作已测试模型。`high` 是 GPT 的推理强度，不代表换成更大的模型。当前语言模型接口不接收原始音频，所以不能宣称 GPT 已听过工程；云端 MIR 仅接收授权的音频范围。

## 4. 云端七个音乐模型

部署根目录沿用克隆数据的 `/root/autodl-tmp/emusician`。通过 DAW 的 Cloud 路线、SSH 隧道和统一任务服务访问；重任务由服务串行调度。下表时长是**当前 DAW 服务的任务上限**，不是开源模型全部能力的上限。

| 模型／接口 ID | 功能 | 当前应用范围与边界 |
|---|---|---|
| **ACE-Step 1.5 XL Turbo + 1.7B LM** · `ace-step-1.5-xl-turbo` | 音乐描述／歌词生成音频 | 界面通常显示 ACE-Step 1.5 XL；最多 120 秒任务；BPM 和时长是条件，不保证精确对齐 |
| **YuE2** · `yue2` | 音乐描述／歌词生成音频，可与 ACE 比较创意版本 | 最多 120 秒预算；实际时长、自然结束与截断须检查 |
| **SCNet XL IHF** · `scnet` | 人声、鼓、贝斯、其他四声部分离 | 最长 600 秒输入；不是主唱／和声或主音／节奏吉他的细分分离 |
| **TransKun V2** · `transkun` | 钢琴音频转 MIDI | 最长 600 秒；保留模型实际返回的音符和 CC／踏板，不恢复原音色 |
| **MuScriptor medium** · `muscriptor` | 多乐器音频转 MIDI，含实际返回的鼓事件 | 最长 600 秒；按实际输出形成乐器轨，力度为导出默认值，不是预测的演奏力度 |
| **ChordMini BTC** · `chordmini` | 和弦识别并导入和弦轨 | 最长 600 秒；固定 170 标签词表，不承诺任意爵士扩展和弦 |
| **SheetSage2** · `sheetsage2` | 综合音符／和弦／拍点／结构分析 | 最长 600 秒；缺少的分项如实为空，不等于完整多声部总谱或五线谱排版 |

历史 0.13.1 记录包含这七个模型的短段真实整链测试；本轮新主机没有因此自动获得新的推理／听感验收。服务连通、清单显示 available、实际推理成功、结果好听／准确，是四项不同结果。

## 5. 本地五条分析路线

本地根目录 `E:/MusicAgent&DAW/analysis`。注册表当前保留以下五条路线；这里的 CPU／CUDA 是保存的配置，不是本轮重新测出的硬件状态。

| 模型／算法 | 运行配置 | 功能及边界 |
|---|---|---|
| **HTDemucs** · `htdemucs` | 本地 CUDA | 人声／鼓／贝斯／其他四声部分离；受本机显存和内存限制 |
| **HTDemucs-6s** · `htdemucs_6s` | 本地 CUDA | 鼓／贝斯／其他／人声／吉他／钢琴六分轨；钢琴与吉他串音仍需试听 |
| **Basic Pitch 0.4.0 ONNX** · `basic-pitch` | 本地 CPU | 有音高乐器转 MIDI；不是鼓分类模型，也不是 TransKun 的同模型本地版 |
| **Chroma-HMM** · `chroma-hmm` | 本地 CPU | 本项目色度／和弦模板／时序算法；支持大小三和弦及可选扩展词表，未训练成爵士和声模型 |
| **Beat This! final0** · `beat-this-final0` | 本地 CUDA | 拍点、小节首拍，进一步得到 BPM／拍号候选；复杂变速与特殊拍号要复核 |

五条本地路线当前单任务最大输入均登记为 600 秒，资源检查仍可能拒绝过重任务。六分轨作为本地Demucs的`stems=6`选项开放，不是在Agent模型列表中必须出现的第五个独立Provider。当前DAW读取到`separation_six_stems=true`。Chroma-HMM 的扩展词表包含常见七和弦、减／增和弦与 sus 等；不能把“词表中存在”解释成“已证明识别准确”。

**切换位置不等于切换同一个模型：**Local 四分轨通常是 HTDemucs，Cloud 四分轨是 SCNet；Local 转录是 Basic Pitch，Cloud 可以是 TransKun 或 MuScriptor。明确要求时保留所选模型与位置，不应失败后静默换模型。当前本地没有接入 ACE 或 YuE2 生成；已有生成结果接受并保存后，可以离线继续播放编辑。

Warp、Drum Rack、Sampler、EQ、Compressor、Delay、Reverb、Auto Filter 都是 DAW 本地音频功能／DSP，不需要租卡，也不属于这十二条音乐模型／算法路线。语言 Agent 本身仍需对应模型服务可用。

## 6. 便于人工测试的指令

开始前确认选区。以下只给最短可用例子，复杂任务先分开测试。

| 前置选择／Scope | 可输入的指令 |
|---|---|
| 选中整条轨／Current selection | `把选中轨道音量降低2 dB，其他保持不变。` |
| 在编曲区选中完整 MIDI clip／Current selection | `把这段MIDI量化到1/16，只改起点，不改音高和力度。` |
| 选已有 Compressor 的整轨／Current selection | `把这个轨道的原生Compressor阈值设为-18 dB、压缩比3:1，其他设置保持不变。` |
| Whole project；Sampler 已加载 | `只把Sampler Keys轨上已加载采样的Release设为250毫秒。` |
| Whole project | `给工程做一版保守的基础混音建议，保留片段、音符、乐器和路由，先给我可审阅方案。` |
| 选完整音频 clip／Current selection | `用云端SCNet分成四轨，保留原音频，先给我导入方案。` |
| 选钢琴音频／Current selection | `用云端TransKun把选中的钢琴转为MIDI，先检查结果再导入。` |
| 选音频／Current selection | `用云端ChordMini识别这段的和弦，再提出和弦轨导入方案。` |
| 选完整音频 clip／Current selection | `用本地Beat This分析速度和首拍，保持工程BPM不变，提出保音高对齐方案。` |
| 任意有效生成范围；默认位置可沿用 | `用YuE2按工程当前速度生成约20秒温暖的爵士钢琴纯音乐，先让我试听。` |
| 与上条分开发送 | `用ACE-Step 1.5 XL按相同描述和时长再生成一个版本，先让我试听。` |

换了选择、编辑了工程或手动修正检测值后，不继续应用已过期方案；让 Agent 按新状态重提。生成和分析等待只显示进度，候选出来后再接受，不需要持续追问“完成了吗”。

## 核对依据

- `scripts/music_agent/plans.py`：25 类常规方案动作、16 动作／2,000 音符边界及原生参数。
- `native_catalog.py`、`selection.py`、`mixing.py`：采样器／鼓组的 project-only 单动作、范围约束、混音只读上下文与能力边界。
- `analysis.py`、`tempo.py`、`generation.py`、`runtime.py`：分析候选、和弦编辑、节拍／Warp、单次生成与确认流程。
- `providers.py` 及本机 `agent/settings.json` 的模型偏好字段：已实现服务和当前所选模型；没有读取或保存 API 密钥内容。
- 本地 `analysis/registry.json`、云接入 `compute-registry.json`，`scripts/cloud/compute/protocol.py` 与 `catalog.py`：登记身份、任务时长与功能。
- [上一轮模型清单](../2026-11-08-plugin-agent-stability/MODEL-MAP.md)、[七模型人工步骤](../2026-11-08-cloud-reconnect-ui/MODEL-TESTS.md)、[四分钟演示脚本](../../demo/2026-11-12-four-minute-demo.md)。
