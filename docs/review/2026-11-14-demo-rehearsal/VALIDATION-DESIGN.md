# 演示提示词验证设计（只读审查）

2026-11-14。本文件只记录现有测试与可复用路径；本子任务没有调用语言 API、音乐模型、启动 DAW、读取密钥或操作用户桌面。不能把下述脚本存在视作本次演示已经通过。

## 结论

最小有效验证应把**原样英文提示词 → 真实配置的 GPT → 真实隔离 DAW → 指定音乐模型 → 候选 → 明确 Apply → 状态回读／Undo**接在一起。现有 `MusicAgentGenerationIntegration.py --live` 最接近，但其请求被硬编码包装为 `instrumental`，没有显式模型参数；不能直接拿它证明有人声的精确演示提示词已通过。建议新建很小的演示验证器，复用生产 `DawBridge`、`AgentRuntime` 和现有断言，不复制完整服务管线。

## 已有入口及证据层级

| 入口 | 参数 | 真正运行什么 | 不能证明什么 |
|---|---|---|---|
| `tests/MusicAgentGenerationIntegration.py` | `--exe PATH --live --duration 16 --prompt TEXT --timeout 1800` | `--live` 时真实配置语言模型、一个真实音乐生成任务、隔离原生宿主、候选／Preview状态／Apply／Undo／保存重开；无 `--live` 则语言调用固定模拟 | 原样有人声提示词、每个所选模型路由、真实设备试听；包装文本固定称 instrumental |
| `tests/HybridComputeEndToEnd.py` | `--exe PATH --models ID... --out NEW_DIR --newlight PATH --keyboard PATH --timeout 1800` | 七个可选择的真实云端模型；MIR 8秒、生成12秒；生产授权及导入编译器；真实候选、Apply、撤销、保存、禁云后重开／渲染 | 没有真实 GPT，不能证明它理解英文指令；默认生成是170 BPM UK jungle，不是这次 neo-soul |
| `tests/MusicAgentTempoIntegration.py` | `--exe PATH --source WAV --timeout 300` | 真实本地 Beat This! 和原生 Warp；确定性语言 Provider；实际 Apply、首拍／速度映射、Undo/Redo、保存重开 | 不是 GPT 自行选择工具；不是 New Light 准确率或物理播放验收；脚本还包含第二次拍号修正分析，非最少调用 |
| `tests/MusicAgentAnalysisIntegration.py` | `--exe PATH --timeout 180 [--six-stems]` | 真实本地 Chroma/HMM，按选项真实六分轨；确定性语言 Provider；原生确认／回读／Undo | 默认输入为合成三和弦，不能代替云端 ChordMini/TransKun 或本次音乐质量 |
| `tests/EnglishAgentLiveProbe.py` | `--live --out NEW_DIR` | 真实语言 API 两次，验证英文界面下回答；项目是内存合成只读对象 | 不创建真实工程、不调用音乐模型、没有 Apply |
| `tests/AgentMixLiveEval.py` | 无通用参数，输出目录固定旧档案 | 真实语言 API，三轨合成工程；最多每任务3轮；只检验基础混音/改名方案 | 没有真实原生工程应用、不听音频；不宜原样重跑覆盖旧记录 |
| `tests/MusicAgentNativeEffectsIntegration.py` | `--exe PATH --timeout 90` | 隔离宿主真实 Sampler 参数和效果器更改，固定语言 Provider | 不验证 GPT 提示词，不验证手动采样加载、第三方插件 GUI 或录音 |

以上脚本应经 `scripts/dev_reconnect_icons.py command ...` 或新的等价 Recorder 入口执行，记录启动/结束、错误和本次实际 EXE SHA；命令路径含 `&` 必须完整引用。

## 建议最小实测组合

1. **D1 YuE2 与 ACE**：工程90 BPM、4/4、播放头0；各一次32秒有人声 neo-soul（与成片脚本一致），明确英文歌词。各自独立测试工程，不能混成并发任务或只验证默认模型。
2. **D1 SCNet**：使用上一步实际生成且已接受的音频，分析32秒或实际更短长度；断言真实四轨标签及对齐、源轨保留，候选阶段工程不变。
3. **D2 ChordMini → Beat This!/Warp**：同一新工程中使用 New Light 的同一个15–25秒摘段。先导入实际和弦，再进行节拍与 Warp，核对工程BPM/拍号保持、源clip时间映射变化且和弦关联随之变化；不能用独立的两个合成测试替代组合验收。
4. **D3 TransKun**：使用 Tea for Two 已分离的真实钢琴资产12–20秒，不能默认 Keyboard.mp3。实际返回的notes/CC数量和来源身份需记录，MIDI需乐器才有可听回放。
5. **D4 原生装置/插件/MIDI和人声录音**：没有可替代真实输入设备和用户连续录制镜头的自动探针。先检查现有参数接口和历史测试，再给用户明确手动预检与通过条件；不为“全绿表”伪造录音或插件发声。

若只做更小的12秒生成/8秒分析探针，必须把结果标为“短样本管线通过”，不能标为32秒拍摄任务/完整歌曲已验证。64小节、90 BPM、4/4约170.67秒，当前生成工具限制10–120秒，因此该整曲请求不能放在“已验证可一键执行”的列表中。

## 新验证器可直接复用的函数

- `agent_client.Client(exe, show=False, offline_test=True)`：拥有独立 stdio 进程和离线音频设备；不要连接或关闭用户正在运行的 GUI。
- `DawBridge(client=client)`，`AgentRuntime(bridge, provider=None, audit=Audit(独立路径))`：读取现有模型偏好并调用真实 Provider；不改配置，不输出密钥。
- `runtime.plan_request(prompt, scope='project', language='en')`：传入原样演示提示词，不额外强制 instrumental，不拼接改变音乐意图的包装句。
- `BoundedBridge.start_generation`（来自生成集成脚本的做法）：每任务最多一次生成、限制秒数；相同方式给 `start_analysis` 加指定路由与单次预算，拒绝意外多次推理。
- `AgentMixLiveEval.BoundedProvider` 的思路：只记录模型、调用数、工具名、耗时和usage；最多4轮。若达到上限如实失败，不自动重跑收费请求。
- `runtime.plan` 的真实 `execution_kind` 和 `analysis/generation` 元信息、`bridge.snapshot()`、`bridge.analysis_result/generation_result()`：检查模型ID、cloud/local路线、候选ID/哈希、起点及长度。
- `runtime.apply(plan['id'])` / `runtime.undo()`：明确由测试用例代表在一次性测试工程中确认；检查状态完成且revision、轨数、clip与候选一致；从 ready 不能直接宣称已经应用。
- `music_agent.tempo.verify_tempo_plan` / `bridge.audio_warp()`：验证Warp比例、首拍位置、原BPM/拍号与跟随状态。
- `HybridComputeEndToEnd.Acceptance.musical_state()/pages()/wait()`：完整分页读回、候选不修改工程、job状态和内容一致性。最终保存后可禁用云配置重开，确认本地资产独立。

## 必须保留的验收边界

- **stdio测试没有真实GUI选择。** 现有分析集成明确使用 Whole project，并从快照得到真实clip ID。可在只有一个明确命名源轨的隔离工程测试提示词，但不能伪造 `selection_context` 再宣称 Current selection 的鼠标步骤通过。文档把“自动工程范围实测”和“用户Current selection操作”分开列出。
- 真实语言 API 成功、音乐模型成功、候选/工程读回成功、用户试听/录屏有声是不同结果。新报告应分别写 `real_llm`、`real_music_model`、`physical_audio`、`listening_quality_verified`。
- 常规 runtime 最多6轮；探针可临时收紧到4轮，不改实际用户设置。等待长任务时分段输出阶段进度，而不是反复向模型发送“完成了吗”。
- 失败后保留原始结果和错误，不盲目重试；若子任务仍在运行，走原取消协议并核对远端确认。不要杀掉用户的DAW/SSH进程。
- 现有保护哈希会包括用户设置/工程；用户同时进行编辑可能产生预期外差异，不能直接把它归为测试破坏。测试只在新目录中持有输出，工程源文件保持只读。

## 源码定位

`tests/MusicAgentGenerationIntegration.py` 的 `BoundedBridge` / `main`；`tests/HybridComputeEndToEnd.py` 的 `Acceptance` / `main`；`tests/MusicAgentTempoIntegration.py` 的 `StartBeats` / `verify_tempo_plan`调用；`tests/MusicAgentAnalysisIntegration.py` 的 stdio selection 边界注释；`scripts/music_agent/runtime.py` 的 `plan_request`、候选导入分派与 `MAX_MODEL_ROUNDS`；`scripts/music_agent/generation.py` 的工具schema（prompt 2,000字、lyrics 4,096字、时长10–120秒）。

## 本轮实现的专用入口

已新增 `tests/DemoPromptLiveCheck.py`，由父任务审查并运行，子任务仅做AST解析。参数：`--exe`、`--cases`、`--case`、`--output-root`、可选`--timeout`。cases读取顶层list或`cases`对象；每次新建独立E盘目录、冻结EXE、32秒生成或已裁短源音频，调用原样英文提示词。模型/位置、完整源范围、单次推理与四轮语言调用都在发起前受限；歌词字段必须实际包含两句主hook。

每份receipt保存公开提示词/公开回答、工具名、用量、真实请求与候选、Apply/Undo/Redo/保存重开结果；不保存私有推理、密钥或完整语言模型内部消息。`input_project`可将已保存的和弦工程交给下一步Warp，验证已有和弦标签及时间映射；`accepted_audio_paths`提供保存后的本地音频，供后续SCNet和用户试听。原件保护只核对指定输入与少量设置，避免遍历所有用户音频。生成和分析通过与否以父任务实际运行的`report.json`为准，本文不是执行收据。
