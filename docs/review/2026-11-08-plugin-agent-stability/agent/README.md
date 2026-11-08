# Agent 混音诊断与本轮交付（2026-11-08）

状态：代码实现、自动回归、两个真实 GPT API 合成工程任务通过；真实歌曲混音听感和用户工程手动验收待做。没有新增整曲响度测量或自动听混音。

## 核查结论

1. 本机实际设置是 `OpenAI / gpt-5-mini / high`，地址为官方 `https://api.openai.com/v1`。不是 API key 自动对应 ChatGPT 网页里的模型，也没有自动换模型或降低 high。两项真实评测返回 `gpt-5-mini-2025-08-07`。
2. 此前最后两项任务均在约 45.9 秒后出现 `ProviderError`，没有 `provider_returned`。旧日志只记异常类，因此只能说与 45 秒 HTTP 超时边界相符，不能断言网络、额度、token 上限中的哪一项就是该历史请求的确切原因。历史前一项任务返回了六轮结果、没有 `plan_ready`；旧日志也没有记录工具名，不能从历史记录推断它读了哪些设备。
3. 原生快照已有峰值、主轨、路由和自动化摘要，Python `public_snapshot` 却删掉了这些字段。旧 Agent 主要知道 gain/pan 和设备名称，不能据此判断实际音频响度。
4. OpenAI 设置 `parallel_tool_calls=false`，每轮最多一个函数调用；runtime 最多六轮。逐个读取多轨设备很容易耗尽轮次。此前未提供批量混音读取工具。
5. 单份方案最多 16 个动作、每片段最多 2000 个音符、本轮上下文内容最多 65000 字符，都是本应用的有界实现限制，不是 GPT 自身完整能力上限。范围仍由 Selection / Entire clip / Whole project 决定，不能用“自动混音”绕过范围。
6. 4096 `max_output_tokens` 包括推理和可见输出，high 推理有可能在给出完整方案前耗尽。此前统一报 incomplete，现已单独报 `output_limit`。本轮保持预算，没有静默增加费用上限或自动重试。

## 实施内容与边界

- `mixing.py` 增加 `read_mix_context`：一次模型工具轮读取范围内最多 16 轨和 16 个已有原生效果器，包含完整有效参数。超限明确返回 truncation；每个设备依然走真实 ID、归属、参数校验和版本检查。主轨只在 Whole project 范围读取。
- `bridge.py` 保留白名单内路由、发送和自动化摘要、主轨增益与瞬时峰值。没有加入音频、文件路径、automation 点数组或插件私有标识。
- 峰值明确标记 `instantaneous_peak_snapshot`、`freshness_verified=false`、`whole_song_loudness_available=false`。停止后的衰减/旧值不能用于计算目标响度，不把所有乐器拉成相同峰值。
- 基础混音的提示和能力入口明确：读取设置 → 提出有理由、有限、保守的初始方案 → 用户试听、Apply。保留片段、音符、乐器、路由和 mute/solo，不为凑方案乱加效果器，不假称已听过音频或完成母带。
- OpenAI 推理模型默认等待时间从 45 秒改为 120 秒，显式调用方 timeout 仍可覆盖。模型、high、4096 输出预算保持；不自动重发收费请求。
- 等待中可见模型轮次、等待秒数与 timeout。错误展示诊断码；日志分别记录 `provider_requested`、`provider_returned`、`provider_failed`、`tools_requested`、回答但无编辑的终态。区分 `timeout`、`output_limit`、`authentication`、`rate_limit`、`refusal`、`tool_round_limit`，不再只留下 ProviderError。
- 诊断只保存模型、scope、工具名、轮次、耗时、token 计数、错误码等元数据；不持久化用户 prompt、轨名、音符、key、provider 原始响应或隐式推理。
- 修正初始界面仍写“分析仅本地”的过时说明，实际取决于所选本地/云端 MIR 模型；缺少 provider 列表时不再把 OpenAI 错标为 Kimi。

## 验证记录

所有执行通过 `scripts/dev_stability.py command` 记录。没有操作用户工程或真实音频设备。

| 证据 | 结果 | 记录 |
| --- | --- | --- |
| 初次定向 mix 测试 | 9/9 | `61089a9cd7` |
| 全 `test_music_agent*.py` | 371/371，48.824 秒 | `b9c850ad3d` |
| 真实 GPT high 合成工程评测 | 2/2，合计只有 3 次 API 调用 | `af7989d67c` |
| 等待/预算错误真实网页组件 | 2/2，340px 宽，截图检查 | 最终 `2e034e6a40`；初次 `bfffd0039a` |

三轨（Drums/Bass/Pad）各有一个原生 Compressor 的合成工程：第一轮 `read_mix_context` 读取三装置，第二轮 `propose_plan` 生成 4 项增益/声像建议，36.576 秒。普通“Bass 改名 Sub Bass 并降低 2dB”一轮、16.113 秒，得到精确 2 项方案。两项都是 `ready`，工程完全未改，必须用户 Apply。真实输入 tokens 合计 22344，输出 tokens 合计 2636。单次最大实际输出 1442，没有触及 4096，不能据此保证所有复杂 high 任务都不会耗尽预算。

完整合成输入、有效命令、API 用量和限制见 [LIVE-EVAL.json](LIVE-EVAL.json)。它不含真实用户工程或用户 prompt。GUI 证据位于 `build/agent-mix-web/results.json`、`waiting.png` 和 `output_limit.png`；原始日志在 `build-logs/`，构建摘要在 `docs/builds/`。

这证明工具编排、范围保护和方案有效性，不证明自动混音优于人工、整曲响度准确、插件听感改善或真实音频回放通过。

## 人工验收与提示词

1. 打开包含三条轨道的测试工程，打开 Agent；顶部确认 OpenAI、gpt-5-mini，模型设置保留 high。全工程混音先把 Scope 改为 **Whole project**。
2. 展开 **What the assistant can do → Basic mix**，点击示例填入输入框，再按 Send。也可直接输入：`Give this project a conservative starting mix. Keep the arrangement and routing intact. Prepare the changes for review; I will audition them.`
3. 等待区应出现 `Waiting for model · round …` 和秒数；不会无期限只显示“生成中”。提出方案后先检查轨名、前后参数、理由。此时声音和工程均不应自行变化。
4. 点 Apply 后试听；点 Undo 应一次还原该批。完整工程上的 Apply/试听属于人工验收，两个真实 API 合成评测没有执行它。
5. 普通编辑对照：`Lower the selected track by 2 dB. Keep everything else unchanged.` 先选中整条轨道，Scope 用 **Current selection**。应只针对选中轨产生方案。
6. 多轨参数对照：`Read the native effects on the selected tracks and propose a gentle compressor adjustment. Keep EQ, routing and instruments unchanged.` 应批量读取，不应让用户逐个给出设备参数。结果需检查具体轨、设备和修改依据，再试听。
7. 范围检查：只选一轨，用 Current selection 请求改变整个工程，助手应说明需要 Whole project 或仅为当前范围提出方案，不能悄悄操作所有轨。
8. 若出错，记录方括号中的 code。`timeout` 是本轮等待截止；`output_limit` 是输出/推理预算耗尽，可拆分任务或自行降低 effort；`tool_round_limit` 是本应用六轮限制，可分轨/分阶段；`authentication`/`rate_limit` 分别检查账号权限/额度。不要把这些都当作“模型笨”，也不要无意识连续重试产生费用。

目前没有“播放整首→逐轨RMS/LUFS/频谱→参考曲对比→迭代回听”链路。需要它时应新增有窗口、有效采样数、路由位置和响度标准的测量协议，独立做实时性能及听感验收；本轮不冒充已有。

## 一段话架构说明

DAW 保持工程和音频引擎的唯一权威状态，侧栏只是操作入口；Python worker 读取受限工程快照，把明确的轨道范围和可用工具发给选定语言模型，模型通过一次批量读取取得混音设置与原生装置参数，再返回结构化方案，本地校验 ID、参数、范围和工程版本，展示给用户确认，点 Apply 后才通过统一命令一次提交并回读检查、支持整批 Undo。音频回调不联网、不运行模型；LLM 不接收音频，也没有听完整首的能力，MIR/生成任务仍走独立的本地或云端音乐模型管线。

## 官方文档依据

本轮使用 OpenAI Docs skill，先核对本地实现，再查询官方文档。不迁移用户已选模型。

- 函数定义和默认值应明确，能由代码知道的参数由代码提供，并减少不必要的工具调用；本轮据此增加批量只读工具。[Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- `max_output_tokens` 包括推理预算；`incomplete_details.reason=max_output_tokens` 可能在出现可见回答前发生。[Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
- 所选模型提供工具调用；模型 API 成功不表示音频输入或完整混音评测能力已经接入本应用。[GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
