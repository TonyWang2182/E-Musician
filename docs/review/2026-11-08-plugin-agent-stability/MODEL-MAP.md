# 模型分工：实际配置与Agent操作

核对时间2026-11-08。依据本机非密钥Agent设置、analysis/registry.json、compute-registry及0.13.1七模型真实验收；这里只列模型与能力，不公开API密钥、SSH凭据或私有会话。

## 指令Agent

当前激活：OpenAI **gpt-5-mini**，reasoning_effort **high**，官方API接口。High是推理强度，不会变成另一个更大的模型。Kimi **kimi-k2.6**适配器和凭据已配置，可在侧栏切换；这不代表本轮已重新验证Kimi网络或账户余额。Anthropic、Gemini和本地兼容服务目前只是预留入口，未实现，不能调用。

这里是一个语言Agent执行工具循环，并不是每一种DAW操作都有一个独立Agent。切换语言模型会影响理解、规划和工具选择，不会把SCNet或TransKun换成GPT。

| Agent想做什么 | 实际执行者 | 结果进入工程的方式 |
|---|---|---|
| 改轨名/颜色/音量/声像、编辑或量化MIDI、剪辑 | 当前语言模型提出参数；DAW统一命令执行 | 方案审阅→Apply→回读；可Undo |
| 调Sampler/Drum Rack和原生EQ/压缩器/Delay/Reverb/Auto Filter | 当前语言模型读取开放参数并提方案；原生DSP发声 | 只允许已开放的动作与范围，不保证第三方插件任意GUI/音色均可控 |
| 基础混音调整 | 当前语言模型＋轨道/路由/已开放装置参数 | 仍是可审阅的调参方案；没有独立自动混音/母带模型 |
| 分离/转录/和弦/节拍/综合分析 | 下面的专用算法或音乐模型 | 返回候选，明确接受后入轨/应用，原件保留 |
| 文字/歌词生成音乐 | ACE或YuE2 | 本地候选→试听→Add track；不会直接改写既有素材 |

语言模型本身在当前接口里没有听音频。瞬时峰值读数也不是全曲响度或频谱，不能据此声称完成了自动听辨、参考曲匹配或专业母带。

## 云端七个模型

| 任务 | 已部署模型 | 当前能力边界 |
|---|---|---|
| 四声部分离 | SCNet XL IHF | vocals/drums/bass/other，不是八乐器细分 |
| 钢琴转MIDI | TransKun V2 | 音符及模型实际返回的踏板等控制事件 |
| 多乐器转MIDI | MuScriptor medium | 按实际输出分乐器/鼓事件；力度为导出默认值 |
| 和弦 | ChordMini BTC | 固定170标签词表，不承诺任意爵士扩展和弦 |
| 综合符号分析 | SheetSage2 | 音符、和弦、实际输出的拍点/结构；不是完整五线谱排版 |
| 音乐生成 | ACE-Step 1.5 XL Turbo＋1.7B LM | 当前任务时长上限120s，条件不等于精确音乐属性保证 |
| 音乐生成 | YuE2 | 当前最大120s预算，实际时长/截断须检查 |

部署在新克隆实例/root/autodl-tmp/emusician，各有独立环境，由protocol 2服务串行调度重任务。0.13.1本轮已在新主机实测七项短段整链；历史证据见[七模型结果](../2026-11-08-cloud-reconnect-ui/RESULTS.md)，不是永久在线或当前余额保证。

## 本地已登记的五条分析路线

| 任务 | 本地方案 | 备注 |
|---|---|---|
| 四声部分离 | HTDemucs | 本机GPU/内存受限，不等同云端SCNet |
| 六声部分离 | HTDemucs-6s | drums/bass/other/vocals/guitar/piano |
| 音频转MIDI | Basic Pitch 0.4.0 ONNX | 有音高乐器转录；不是鼓分类器 |
| 和弦 | Chroma-HMM本地算法 | 本项目实现的基线算法，并非另一个语言大模型 |
| 节拍/小节拍 | Beat This! final0 | BPM/拍号/首拍需要复核，复杂变速不保证正确 |

本地目录E:/MusicAgent&DAW/analysis；生成目前只接云端。Auto依任务能力选路，明确指定Cloud/Local和模型可以固定测试对象；失败时不能把静默换模型当原模型成功。Warp是本地音频处理，原生效果器是DSP，不需要调用语言模型才能运行。
