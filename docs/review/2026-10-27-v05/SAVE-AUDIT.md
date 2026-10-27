# 保存与数据管线复盘

日期：2026-10-27（Asia/Shanghai）。范围：只读代码、工程清单、历史测试与官方资料；没有运行应用、重现故障或修改用户工程。审计起点是源码指纹 `7941e50dbc5b96ede13a0b5f990eadc63c2102732081f34f8d96b107e1cda760` 的0.4实现。下列区分已确认的实现问题与需要实测的因果假设。

用户补充：实际插件为Serum，点击Save后窗口仍能操作但看起来无反应。因此应优先检查任务受理/终态、重复点击的粘滞错误及dirty状态，不能把此症状直接称为主线程完全卡死。主线程原生状态捕获仍需要计时，但不是已经确定的唯一根因。所有修复应是通用宿主机制，不增加Serum专用白名单。

## 结论

现有保存虽然把文件复制放到了worker，但准备阶段仍同步读取全部插件状态，保存状态显示也没有覆盖整个生命周期。再叠加每次重新归档全部音频、插件通知导致的dirty/revision变化，确实存在“点击卡住、连续点save出现错误、文件写好了却仍像没保存”的路径。旧测试验证了文件内容与插件恢复，没有验证用户这组混合工程的持续响应、连续保存和保存后静置状态。

不要把所有插件操作直接搬进worker。当前固定JUCE的VST3宿主明确要求get/set state在消息线程调用；需要先缩小主线程工作的范围、明确保存代次、复用已经归档的媒体，并对实际插件测量状态捕获耗时。

## 用户工程只读发现

- `test-projects`现在是 **33个文件、410,250,775字节**，已不是旧18文件基线。必须新建保护基线，不能回滚到前一轮。
- 当前 `CL.emproj` 为schema3、revision159，SHA-256 `14de9062cf19669ba6b384f329b88ade63b99b866a0b4287eb227b85dc2fc38f`。清单只有 `computer love` 和 `Drum` 两条audio，没有MIDI轨或插件，因此它不能直接重现用户描述的三轨会话。
- 两份源MP3各15,775,913字节、时长394.370612秒。四个近期generation各自包含两份MP3及同一逻辑插件ID `fea7dc915ffe4bbf9771d0c3904998cc` 的约18KB状态块；最后清单指向的generation不含插件。
- 这些文件证明近期曾生成带插件的保存素材，但不能单凭孤立状态块断言对应清单已成功替换、插件具体型号或用户后来为何移除轨道。保留所有generation，不清理孤立文件。

## 当前路径

`Save点击 → capture项目DTO → capture全部原生插件状态 → 建立job → worker校验/复制全部素材/写插件块与JSON/替换清单 → 30Hz主线程检查完成 → 计算savedKey/处理dirty → UI显示结果`。

保存的前两个步骤发生在job建立前，用户看不到“准备插件状态”的任务阶段。正常播放实例仍在本进程，单个插件的原生状态函数如果长期阻塞，同进程宿主不能安全强制终止该函数；真正的故障隔离需要独立插件进程，不能用一个普通future超时就声称解决。

## 问题与优先级

| 优先级 | 已确认实现 / 待证实影响 | 代码依据 |
|---|---|---|
| P0 | 插件状态捕获在job创建前同步执行。`suspendProcessing → getStateInformation → 全参数读取 → 序列化`都在消息线程，耗时未记录且没有准备阶段进度。**确认存在阻塞路径；尚未测到用户插件耗时。** | `EngineSessionJobs.inc:342–350`；`EngineSession.cpp:213–221`；`PluginHost.cpp:649–689` |
| P0 | 保存期间Save按钮仍可点：UI的busy只含chooser/confirming/pendingAfterSave，不含运行文件job。再次点击被任务互斥拒绝，错误写进p.error；错误文字持续优先于后续completed状态。**确认可能把已完成保存显示成旧busy错误。** | `MainComponent.cpp:909`、`:958–971`、`:1556–1565`；`EngineSessionJobs.inc:299` |
| P0 | 任意插件参数通知直接置changed，未比较旧值或区分重复通知；timer先消费通知并推进revision，再提交save。保存只在revision完全相同才清pluginDirty。**确认语义脆弱；需要重现插件同值/状态读取通知是否导致持续dirty。** | `PluginHost.cpp:278–305`；`EngineSessionJobs.inc:258–278`、`:347`；`EngineSessionPublic.inc:30` |
| P1 | SaveAs记录打开文件选择器前的revision；选路径期间收到插件通知，确认后可因revision过期而拒绝。**确认存在该拒绝路径；未验证用户此次是否用了SaveAs。** | `MainComponent.cpp:1573–1587`；`EngineSessionPublic.inc:47–50` |
| P1 | 每次普通Save都创建新UUID generation并复制每份音频，插件块也全部重写；没有增量复用。用户这组两MP3每次至少写31.55MB，即使只改一个音符。**代码和文件目录均证实重复I/O。** | `ProjectStorage.cpp:533–585`、`:505–521`、`:674–676` |
| P1 | 插件参数通知每33ms最多推进一次工程revision，令结构快照和整块UI更新失效；如果插件持续通知，同值通知也会触发重绘和状态重建。**放大卡顿的机制确定，通知频率待实测。** | `EngineSessionJobs.inc:261–265`；`EngineSessionPublic.inc:8–27`；`MainComponent.cpp:883–906` |
| P2 | worker完成后的commit又在消息线程对完整state计算contentKey；MIDI多时仍扫描音符。保存状态DTO还在闭包间复制，archived结果没有供活动素材注册表复用。**小三轨未必主因，但会拖慢扩展。** | `EngineSessionJobs.inc:343–347`；`EngineSession.cpp:77–98` |

`EngineSessionPublic.inc:76–82`还保留同步保存兼容门面，但当前GUI调用的是 `execute("save_project")`，不能把同步门面误判为GUI正在使用的文件I/O路径。

## 官方资料如何约束改法

1. VST3把持久化定义为processor与controller两部分，并要求除处理例外外的插件调用由UI线程发起。固定JUCE 8.0.6的 `juce_VST3PluginFormat.cpp:3300` 同样用消息线程断言和MessageManagerLock保护状态调用。因此“把原生插件状态直接丢到worker”不符合本次实际组合。[Steinberg持久化与线程模型](https://steinbergmedia.github.io/vst3_dev_portal/pages/Technical%2BDocumentation/API%2BDocumentation/Index.html)
2. JUCE说明长时间持有callback lock会造成播放卡顿；暂停处理可避免音频线程等待，但可能输出静音。现有ScopedProcessorSuspension并不意味着保存期间声音一定连续，需单独测量。[AudioProcessor锁与暂停](https://docs.juce.com/master/classjuce_1_1AudioProcessor.html)
3. JUCE的APVTS copyState会同步参数并使用锁，线程安全不等于实时安全。这支持“捕获不可变快照后离线处理”，不支持在音频回调做保存。[APVTS copyState](https://docs.juce.com/master/classjuce_1_1AudioProcessorValueTreeState.html)
4. 当前Tracktion在线文档的保存API已经是回调式；本项目固定版本仍是旧返回值接口，不能照抄新版签名。可借鉴完成回调和临时版本概念，继续使用经过测试的自有schema存储。[Tracktion EditFileOperations](https://tracktion.github.io/tracktion_engine/classengine_1_1EditFileOperations.html)

这些文档是设计约束，不能代替本机插件、设备与三轨工程测量。没有建议未经验证升级整套引擎。

## 最小改造顺序

1. **先把保存变成可观察事务。** 接受请求时即分配save generation与job，显示“准备插件状态/归档媒体/写清单/完成”。主线程下一次调度开始捕获，至少让反馈先绘制；每个插件分别记录name/状态字节/捕获耗时。单个原生函数仍可能阻塞，报告必须保留这个边界。
2. **Save只保留一个活动请求。** GUI显示Saving并禁用重复提交，或把连续Ctrl+S合并成一个明确的“当前保存完成后保存最新修改”请求。不要因已有保存而产生粘住的错误。Agent端返回正在进行的job或明确busy码，不以泛化文字替代状态。
3. **按内容代次判断dirty。** 区分模型编辑代次与插件状态代次；先合并已存在的插件通知再捕获。捕获对应每个插件的版本，worker完成后仅确认这些版本已保存。过滤重复同值参数通知；对真实非参数状态通知保守保留dirty，不能为了清星号丢掉保存期间的新编辑。采集本身产生的回调要有明确同步边界。
4. **复用已归档的不可变媒体。** 普通Save引用已确认归档的音频和未变插件blob，只有新增或变化数据才写新文件；SaveAs/Collect处理目标bundle差异。schema3本已允许asset引用不同generation，可先兼容复用，不必急着把所有格式一起迁移。校验引用在bundle内、存在且身份匹配；取消只清本事务新文件，不删除复用资产。暂不自动GC用户旧generation。
5. **worker承担序列化、哈希与文件事务。** 主线程只产生必要DTO与插件快照，worker计算保存摘要和JSON；主线程最终提交只改小型状态。让导入/录音准备源、播放源、工程归档通过稳定asset ID关联，避免保存后必须重开才切到归档的双路径状态。
6. **让UI订阅具体变化。** 运输位置/电平、音符数据、插件参数、工程结构分别刷新；插件参数变化不应强制重建整个轨道列表。继续保留单个活动Edit，不能引入第二份随时可写工程镜像。

## 必需复现与验收

只用新建测试工作区或用户工程完整副本，不触碰原工程。先确认用户实际插件名称与版本，并在测量记录中保存EXE/source指纹。

| 场景 | 必须记录 / 断言 |
|---|---|
| 两条394秒MP3＋一条MIDI＋实际插件，停止播放后保存 | 点击受理延迟、消息线程最长停顿、各插件捕获耗时、worker耗时、实际写入字节；完成后轨道/音符/插件状态可重开 |
| 连续10次Save / Ctrl+S | 仅一个活动事务；无重复31.55MB拷贝；既有job不被误报失败；最终清单对应明确代次 |
| 保存后静置10秒 | 无用户修改时dirty保持false；同值参数回调不持续推进revision；若真实非参数状态变化则正确保留dirty并说明原因 |
| 保存过程中真实编辑音符/音量/插件参数 | 已保存快照可读；后来的编辑仍dirty，下一次保存清除；不能以无条件清标志修复 |
| SaveAs选择器期间插件通知 | 不丢掉保存意图；提交时冻结当前明确状态或显示有意义冲突，不能无声失败 |
| 取消、外部改写目标、缺失素材、磁盘写失败 | 旧清单完整，复用blob不删除，新事务可清理；错误与具体job关联 |
| 持续播放＋保存 | 真实xrun、回调耗时和静音/中断迹象；不能只凭文件正确或后台线程存在宣称流畅 |

旧 `PluginHostSmoke.py:288–302` 在save后直接做remove/Undo/open并检查参数恢复，没有检查保存响应时延、写入量、原地dirty稳定或两条长MP3组合。`AgentJobsSmoke.py`已覆盖保存期间新编辑保留dirty，但没有真实插件通知。应补这两个缺口，保留旧测试作为回归。

本审计没有声称已复现唯一根因，也没有进行代码修复。建议先按以上证据测量和修复保存，再接录音/自动化/路由，避免把实时录入的数据继续送进存在重复I/O和模糊完成状态的保存通道。

## 2026-10-27 实施附录（待统一构建验收）

工程复盘之后，root 在旧 Release 源码指纹 `7941e50dbc5b96ede13a0b5f990eadc63c2102732081f34f8d96b107e1cda760` 上建立了独立副本基线：两条 394 秒 MP3 与 Serum VST3 默认音色连续四次 API 保存均成功，dirty=false；受理 20.5–21.6 ms，完成 136–188 ms，但每次增加约 31.57 MB。记录为 `docs/builds/20261026T180038.029714Z-0d69b93efe.json`，原始结果为 `build/save-baseline/503bb4dc-eede-4f46-93fc-8547a33aba7b/report.json`。**这未复现 GUI 点 Save 无反馈，不能把基线描述成挂死复现。**

当前实现改动：

- `EngineSessionJobs.inc`：先创建可查询 job，再由消息线程每次 timer 调度捕获一个插件。worker 等待捕获完成后归档和计算保存摘要；插件指针身份与 change generation 再校验，捕获期间发生插件改变则明确 conflict，文件写入期间的新编辑保留 dirty。录音及录音收尾不受普通播放终点停止逻辑影响。
- `PluginHost`：预分配原子参数缓存，同值参数通知不产生新 change generation；非参数状态与 program 通知仍保守标脏。音频回调内不分配、不读文件、不加新的 mutex。
- `ProjectStorage`：只复用当前目标 bundle 中相同 asset ID 的合法文件；同源路径直接复用，外部源在 worker 逐块比对后复用，变化则写新 generation。Save As 会归档到新 bundle。清单写入前复核旧清单字节及复用文件 size/mtime，取消或失败只清理当前新生成文件，保留所有历史 generation。插件 blob 仍逐次写入，不宣称已实现其增量复用。
- 保存指标通过 `JobSnapshot` 暴露 `phase/detail/captureMs/maxPluginCaptureMs/bytesWritten/bytesReused/pluginsCaptured`；JSON 使用对应 snake_case 名称。`bytes_written` 统计本次媒体、插件 blob 与清单的逻辑写入字节，不等于操作系统物理磁盘写入量。
- schema4 增加 bus/output/sends、input device identity、归一化自动化点和 MIDI controller DTO；schema1/2/3 仍只读加载，在明确保存为 schema4 前保留原清单精确字节备份。arm/monitor 不写入工程；不持久化运行中的录音临时状态。
- 存储约束为每轨 32 sends、全工程 512 sends，每 owner 256 lanes、全工程 4096 lanes、100000 points、100000 MIDI controller events。反馈环包含 disabled sends；插件自动化必须引用同 owner slot，缺失插件实例允许保留稳定参数 ID 与曲线。

新增/扩展测试代码：`tests/SavePipelineSmoke.py`（两条音频加一 MIDI，可选指定原生音源模块；连续保存、指标、并发普通编辑、Save As、重开）；`tests/StorageV3Tests.inc` 保留旧测试入口和报告名，扩展 schema4、相同/改变媒体、Save As、目标被外部修改、复用文件被修改、取消、schema2/3 迁移和 graph/controller 校验。当前仅 Python AST 静态解析通过，**尚未构建或执行这些测试**，统一验收由 root 安排。

保留边界：单个插件的 getState 仍是不可抢占的消息线程原生调用，可能短时阻塞或因暂停处理造成静音；此实现让等待可观察并避免连续全链捕获，不承诺消除插件自身延迟。保存完成只更新逻辑素材归档引用，当前播放 graph 沿用已有 WAV/准备好的 PCM，重开工程后按归档源准备；当前会话外部删除原 WAV 仍可能影响播放。主线程受理阶段仍需复制工程 DTO；极大音符工程需另看实测。旧 GUI 故障、native editor、边播边存的实际 xrun/声音连续性都需要独立验收。

## 真实通知回归与后续修正（实现待重新构建）

root 的真实 Serum 通知 probe 已提供失败证据：`build/plugin-notification/7244afa9-7523-4ac6-ab9e-82c12e767f38/report.json`，构建记录 `docs/builds/20261026T184457.686637Z-0d7967d780.json`。2397 个 raw parameters 两轮共 4794 次同值通知通过；小幅真实修改的反向检查通过。强制自动化先应用值、再回报同一值时，explicit 从 .013 被改为 .036，generation 1→2、revision 5→6、dirty=true。此测试直接调用 JUCE listener 分发，**不是**提前返回的同值参数命令，也不代表已操作插件原生 GUI。

固定 TE 的正常自动化通过 `parameterChanged(value, true)` 调 raw `setValue`，本身不要求发送 host listener。风险来自原生插件回报/echo：本地 Watcher 只按上次通知值去重会落后于静默的自动化写入；TE 的异步通知又无条件调用 `setParameter`，把播放值变成手动 explicit 基准值。本次修正为：Watcher 在消息线程预建稳定参数映射，回调比较 TE 已应用的 atomic current 值；参数布局提示先使映射失效，消息线程确认身份后恢复，否则保守标记变化。程序与非参数通知仍标记变化；不以“正在播放”为理由忽略真实用户编辑。新增 `hasPendingChanges()` 供关闭/快照读 pending 标记，既不 drain，也不推进 revision。

TE 精确补丁只在 `ExternalAutomatableParameter::handleAsyncUpdate` 跳过已经应用的相同值，保留初始化及程序刷新使用的 `valueChangedByPlugin` 行为。`cmake/patches/tracktion/manifest.json` 升至 schema2，列出两个精确源文件及 before/after/patch SHA256；补丁脚本仍接受原单文件 schema1。新协议在任何源码替换前预检全部文件，并暂存全部输出；每个文件原子替换，操作系统在多个替换之间失败时可由下次 hash 验证继续，不宣称跨文件原子事务。补丁尚未由本子任务应用到 `_deps`，由 root 通过 Recorder 统一应用和验证。

保存受管自动化参数时，native opaque chunk 继续原样读取；参数回放 envelope 对已有受管曲线的参数保存归一化 explicit 基准值，不把播放瞬时值当成手动值，也不改写当前处理器。没有受管曲线的参数仍取 raw 值，避免遗漏尚未异步同步到 TE 的原生 GUI 修改。通知 probe 已扩展：强制跟随曲线后保存和重开，检查基准值、lane 与点 ID，并检查保存未改写 live raw 值。

[Steinberg Processing FAQ](https://steinbergmedia.github.io/vst3_dev_portal/pages/FAQ/Processing.html#q-can-icomponentgetstatesetstate-be-called-during-processing) 明确允许实时处理期间由 UI 线程调用 getState/setState。结合 JUCE `suspendProcessing` 会使处理输出空缓冲的行为，当前仅对 **VST3 的只读 capture** 跳过暂停处理；仍在消息线程调用 getState，保留分批捕获与代次校验。VST2 读取以及所有加载、恢复、状态写入路径继续保守暂停。此条更新替代上一附录关于所有捕获均暂停的实现描述；插件自身的锁和耗时仍可能造成问题，**在 root 完成边播边存测量前，不宣称没有声学中断或 xrun**。
