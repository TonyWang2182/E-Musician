# 独立拍摄版的本地候选回放管线

状态：已实现，六场景真实原生联测 25 项通过；GUI/实际输出试听及影片验收由主任务另行记录。本文件不把已有模型结果回放称为新模型推理；原始 0.13.6 二进制和日常配置保持独立。

## 边界

`EMUSICIAN_SHOWCASE=ON` 是独立编译开关，工程文件或 Agent 输入不能开启。固定包根由 `EMUSICIAN_SHOWCASE_ROOT` 编译配置提供；当前为 `E:/MusicAgent&DAW/demo-video/showcase-v1/workspace`。普通构建保持既有生产路径。

窗口标题为 `E-musician - Audio Workspace`。应用实例标识独立，避免把启动请求转交给日常版本。启动项目来自 manifest 第一项实际 ID，不硬编码场景身份。包内只有三个初始工程：New ideas、New Light、Tea for Two；它们不会在每次启动时被脚本重置。

`ReplayMode.h` 提供 manifest、工程列表、任务目录及独立 runtime 目录。Engine/session、界面配置、插件目录、缓存、Agent session/WebView、候选输出隔离由本轮对应模块共同实现，不能仅凭标题不同认定隔离通过。

## 指令到工程

1. 本地 `ReplayProvider` 只匹配当前工程 manifest 的完整英文提示词，允许大小写、空白及末尾标点差异。页面能力清单只呈现该工程的这些指令。未知指令、错工程或没有正确音频选择时拒绝，不拿其他素材顶替。
2. 仍进入正常 `AgentRuntime` 和 `DawBridge`：冻结真实选择/工程版本，调用现有 `start_generation` 或 `start_analysis`。本地 planner 不读取生产 API 配置与密钥，不构建网络 Provider；独立 Python helper 加 socket 审计守卫，只允许 loopback。
3. native 任务的子进程改为 `scripts/showcase/replay_worker.py`。它验证任务、模型和工程身份，原始结果 JSON 的 SHA-256、媒体 SHA-256、当前准备音频的 SHA-256、范围、采样率、Warp 比例与固定参数；生成额外匹配原始音乐描述、歌词、种子、BPM、时长条件和拍号。错音频会在等待前失败。
4. 验证后等待可配置的展示时长，显示 `Preparing...`；复制真正的已有媒体或符号数据，只重绑定当前任务/工程/片段身份，写新候选。未修改音符、和弦、节拍或音频内容。
5. 宿主照常进行格式、时长、音符/控制器、哈希及来源校验。生成使用现有真实 Preview/Stop 和 Apply；分离/转录经原方案确认后导入；和弦只返回候选，用户在 Analysis 面板手动添加和弦轨；Beats 使用原生 `apply_beat_analysis` 真实执行保音高 Warp 并映射关联和弦时间。
6. 应用走原命令/事务、回读和 Undo。回放逻辑不直接写界面波形或伪造轨道，不替换存储与音频引擎。

原有 route 枚举中的 `cloud/local` 表示模型原后端，保留它们是为了复用既有类型校验，实际 worker 在此编译版本完全本地执行。界面不声称正在连接云端。原结果中的耗时是**原推理记录**，不是本次等待计时。

## Manifest v1

根字段：`schema_version: 1`、`projects`（恰好三项）、`scenarios`。

工程字段：`id`、`title`、`path`、`template`、`bpm`。`path` 是包根内相对路径。项目 asset 目录仍遵守宿主原存储约定。

场景字段：`id`、`project_id`、`kind`、`model_id`、`prompts`、`wait_seconds`、`result_path`、`result_sha256`、`parameters`、`application`。分析另外提供 `source.sha256/offset_seconds/duration_seconds/sample_rate/warp_speed_ratio`。`application` 为 `import/manual/warp`。

| 场景 | 真实已有模型来源 | 默认等待 | 应用 |
|---|---|---:|---|
| yue | YuE2 | 20 秒 | Preview → Apply |
| ace | ACE-Step 1.5 XL Turbo | 15 秒 | Preview → Apply |
| separate | SCNet 四轨 | 12 秒 | Apply 四轨 |
| chords | ChordMini | 8 秒 | Analysis 手动加和弦轨 |
| beats | Beat This final0 | 6 秒 | Apply 原生 Warp |
| transcribe | TransKun | 10 秒 | Apply MIDI，132 个已有音符 |

等待范围允许 0–180 秒，测试可使用临时 fixture 和可控 clock；正式 manifest 的等待不是测速结果。原始结果文件保持原字节；每个运行候选与 `replay-receipt.json` 保存 `mode: retained_result_replay`、原 result hash/job ID、等待秒数和 `inference_performed: false`。生成及导入分析的工程 provenance 同步保留这一来源。符号参数的公开 schema 不混入额外 provenance 字段。

## 复核入口

- `tests/test_showcase_replay.py`：目录边界、哈希/源/范围/参数拒绝、取消、等待、固定指令、手动和弦、不伪造失败结果、不读取密钥与非 loopback 连接拒绝；使用明确的合成 fixture，不声称模型质量验证。
- `tests/ShowcaseReplayIntegration.py --exe <showcase exe> --root <workspace>`：真实独立 native output-probe 进程与 replay planner，六场景走候选/Preview/Apply/Undo/Redo/保存重开；错误 YuE2 源不能套用 ACE 分离结果；Warp 后检查和弦时间映射；钢琴导入检查 132 音符。
- 联测需 showcase 专用 `showcase_select_clip` 命令，通过正常宿主选择方法更新选择，不能仅篡改 Agent 快照。
- 阶段工程保存至 `showcase-v1/captures/projects`；初始三个工程在测试 sandbox 中复制后打开，结束前校验它们未改变。联测报告存 `showcase-v1/tests/<run-id>/report.json`。

所有测试由父任务统一用 Recorder 执行，避免开发日志并发写入。编译通过、单测通过、native 联测通过、实际 GUI 拍摄、物理声卡与听感分别记录。固定提示词匹配并不能证明自由自然语言 Agent 能力，本地等待也不代表线上响应速度。

补充：showcase_select_clip 仅在展示编译开关下存在；校验当前工程与 clip 身份、拒绝录音中选择，不写工程修订，也不加入 Agent 的工具 schema。用于自动化联测时从真实选择方法取上下文。

## 六场景真实联测结果

最终命令：`python scripts/dev_showcase.py showcase command python tests/ShowcaseReplayIntegration.py --exe E:/emusician-analysis-build/bin-showcase-v1/Release/E-musician.exe --root E:/MusicAgent&DAW/demo-video/showcase-v1/workspace`（含空格路径在 shell 中引用）。Recorder 为 `20261121T170858.606654Z-e144f68a98`；完整报告位于 `showcase-v1/tests/3e61ba0012654773831d7b8d2089c0ce/report.json`。

- 被测 EXE SHA-256：`a6ba0e3b1e15937f50d004e0d4f9448256323d4c0b061d7e9c3b7ee486c1eeee`；manifest SHA-256：`4d23b724ef164707ff0f2fa03b277c857930eadb8a968764bc78c45ac51049b7`。
- 25 项通过：六条完整英文指令、真实候选、Apply/单次 Undo/Redo、拒绝重复应用、保存重开与完整音乐状态回读；10 个阶段工程已保存。初始三工程及资产哈希未变。
- 错把 YuE2 当作 ACE 分离源时，范围校验在创建任务前拒绝，未产生新候选、未编辑工程；此案例没有走到 worker 哈希校验，后者由独立单测覆盖。
- 和弦候选保持未应用，必须通过 Analysis 对应原生命令接受；Warp 的保音高/跟随工程速度真实开启，和弦标签不变、边界按同一时间变换映射，Undo/Redo 与保存重开均保持完整和弦区域。
- 132 个 TransKun 音符全部进入可编辑 MIDI；音高、力度、通道完全一致，秒→拍→秒最大误差 `1.7763568394002505e-15` 秒，低于 1µs 容差。
- `Preview` 路由调用及 Stop 均无工程编辑，但两次在无物理输出的 output-probe 环境均返回 `unavailable`。本报告没有把它当作试听声音通过；GUI/真实输出验收必须单列。
- 测试显式禁止生产 API 配置、密钥和网络 Provider 的构建；记录模型 API 调用为 0。没有 SSH、模型推理或物理录音。

失败和修订保留：首轮 `542061f4e5244e2c92890c58589c3f22` 暴露无 GUI 环境下选择仅更新 clip id、未发布统一 selection context，主任务修复仅 showcase 编译的 helper；第二轮 Recorder `6740266850` / report `b7c74e018d0b44718b2274a15d9e98a1` 已走完六场景，在最终测试的独立六位小数舍入比较上失败。经逐音核对，数据无差异，仅极小浮点误差跨过舍入边界；测试改为精确比较离散值并使用明确时间误差容差后重新全程通过，未修改模型音符或放宽音高/力度检查。

D2 最终 Warp 声音已用原始 0.13.6 实际导出；记录见 [AUDIO.md](AUDIO.md)。本联测不代表自由自然语言、模型质量、实体声卡或人工听感验收。
