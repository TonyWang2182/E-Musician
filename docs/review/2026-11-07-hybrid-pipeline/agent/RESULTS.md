# Agent 混合管线实施与证据

2026-11-07，阶段：Agent 代码、契约与窄屏页面已验证；主任务已完成冻结 native + 七模型真实 GPU 集成，本子任务独立复核 v3 与 YuE2 修后 v4 证据。下列 Python/浏览器单测没有调用付费语言模型或音乐模型；真实模型证据及验收范围见文末。

## 架构一段话

侧栏先把当前工程、选择范围和宿主真正可用的模型清单交给语言模型；语言模型选择已开放的任务工具，把要做什么、用哪个模型、在本地还是云端运行表达为结构化请求。Agent 校验范围、工程版本、模型可用性和参数后，只调用 DAW 统一命令；DAW 把耗时工作交给独立后台任务，本地或云端模型返回保存在本机的候选。侧栏只展示必要的数量、乐器、模型和试听信息，用户确认后再通过同一个工程命令一次性加入轨道，并读取真实结果核对；Undo/Redo、保存和离线重开由 DAW 工程层负责，语言模型不直接写工程或操作实时音频线程。

## 变更

- 新增 `music_agent.compute`：从 capabilities 验证 `execution=local/cloud/auto` 和 `model_id`，显式模型不可用时拒绝，不偷偷替换。未指定则让宿主决定可用默认值。
- 分析工具支持 `score` 与 notes/chords/beats/structure 分页，支持 TransKun/MuScriptor 多轨元信息及 CC 数量。音符只保留一套分页内容，Agent 不再假定转录永远一轨。
- 参数、轨数/事件数、文本和数值有边界；路径、凭据和嵌套任意内容不进入语言模型。和弦原标签保留至 128 字，未知置信度保持未知。
- 云端模型首版只允许已验证的固定参数；不混用本地 Demucs/Basic Pitch 参数。生成支持 ACE/YuE2，沿用工程默认速度，不重复追问 BPM。
- 导入确认和回读按真实轨数、音符与 CC 总数核对。综合分析只保存分析标记，不自动改工程速度。取消区分本地停止与远端确认。
- 侧栏沿用现有配色、层级和输入布局，只补模型/位置、小型数量摘要及生成预算提示；同步中英文，不另造界面系统。
- 增加 `HybridComputeEndToEnd.py` 真实云端验收入口，仅编写/语法检查；是否真实执行及结果以主任务的单独记录为准。

## 已执行证据

| 检查 | 真实结果 | 记录 |
|---|---|---|
| 首轮 Agent 单测 | 346 项中 345 通过；原有能力卡断言为 10，新增 score 后应为 11。已修正断言，失败记录保留 | `docs/builds/20261106T172906.740614Z-8b8f81b21a.json` |
| Agent 回归 | 346/346，49.453 秒 | `docs/builds/20261106T173133.522944Z-b091135a21.json` |
| 侧栏窄屏浏览器 | 4/4；340 px 多轨转录、340/400 px 综合分析、中英文、生成截断提示。无横向溢出/JS 错误；已逐张查看截图 | `docs/builds/20261106T173224.853305Z-63dfdcd7ff.json` |
| 候选安全字段与说明修订后的 Agent 回归 | 346/346，49.082 秒 | `docs/builds/20261106T174116.889288Z-f41ee78b3d.json` |
| 新真实 GPU 验收脚本初次语法检查 | 通过；未执行推理 | `docs/builds/20261106T174208.087841Z-877b085a1b.json` |
| 验收脚本辅助测试 | 4/4；少样本不报百分位、20 样本统计、明确模型 ID、音乐数据比较不丢 CC/通道/未知分数 | `docs/builds/20261106T174440.154898Z-f0c1af3ec2.json` |
| 验收脚本补充耗时记录后的语法检查 | 通过；未执行推理 | `docs/builds/20261106T174442.045470Z-4ced9287a4.json` |
| 与真实原生 CC/program 契约对齐后 Agent 回归 | 349/349，49.968 秒；按事件类型区分 CC 与 program，保留未知生成截断状态 | `docs/builds/20261106T175059.239584Z-9bfbdc1741.json` |
| YuE2 新 completion 形状页面检查 | 4/4；重新查看生成页截图，预算截断提示正常显示 | `docs/builds/20261106T175151.234790Z-0dd1aa4be4.json` |
| 真实 E2E 按 program/通道核验后的语法检查 | 通过；未执行推理 | `docs/builds/20261106T175202.087035Z-827f7c6466.json` |
| 新协议生成 helper 契约 | 5/5，0.685 秒；模拟传输、真实 PCM16 文件、真实 hash/下载/音频检查/发布。实际时长与请求预算分开，warnings/limitations/completion 保留，非默认 compute_root 调度和显式旧 registry 兼容，错模型/错 hash 不发布 | `docs/builds/20261106T175456.678496Z-f45d4bb2a4.json` |

原始日志在忽略目录 `build-logs/`；页面截图/结果在 `build/hybrid-agent-web/`。页面数据为明确标记的合成测试夹具。测试期间其他子任务继续修改同一源码树，因此这些是模块中间证据，不能替代最终冻结版本的完整回归或真机验收。

## 单测证据边界

- 上述单测本身不能证明真实七模型云端推理、公共命令全链路、最终 EXE 行为和用户听感。真实集成已由下方 v3 与 v4 补充，听感仍待人工验收。
- 物理 ASIO/MIDI 设备、长期待机、GUI 帧率、实时音频回调和整曲识别质量。
- 每个模型的商业授权、标注准确率或还原原插件音色；本次只保留模型回传的真实语义和限制。

人工测试问句见 [MANUAL-CHECK.md](MANUAL-CHECK.md)。

## 只读整合审查与修订

原生首轮构建前审查发现四个明确接口不一致，已向对应负责人反馈并对齐：schema8 工程重复覆盖保存仍有旧上限；已接受和弦的未知分数需从内部 -1 映射回公共 null；capabilities 的执行位置字段统一为 execution_modes；导入 MIDI 自动加入的 program-change 事件不能计作模型预测 CC。原生负责人修前三项和 program_change_count 摘要，Agent 分别核总事件数与按 type=0..127/4097 分页得到的 CC/program 数；E2E 额外核验 program 的 14-bit 编码和每轨通道。以上原生实际行为仍需主任务的最终构建验证。

生成服务原输出为 truncated/warnings，侧栏原消费 completion/limitations；主任务补统一形状，Agent 保留 truncated=true/false/null、reason 与 timing_is_exact，UI 按真实预算截断状态提示。未因缺失字段推断“自然结束”。

Auto 路由携带本地参数的边界已记录：GUI 根据真实选中 provider 清理本地控件参数；Agent 未指定模型却传本地参数时，宿主若选中云端会明确拒绝，而非上传错误参数或静默丢弃用户要求。后续若要改善此类请求的自动纠正，应以用户参数语义决定路由，不能为减少一次调用偷偷更换模型。

## 真实 v3 独立验收审查（2026-11-07 02:24 后）

主任务执行的 `hybrid-final-20261107-v3/report.json` 报告七模型完整命令链通过，记录 `docs/builds/20261106T181920.081847Z-0bf7c34997.json`；冻结核验记录 `docs/builds/20261106T182345.994688Z-e9e4aa7d0b.json`。该 EXE SHA 为 `d5579acbc8128ae9ffcd1c76cbf9ae68eb9d9ce897ab24fbb7e93e7f06de283f`，报告 SHA 为 `df0beebb586a640bdc6631d6ec372d83b46a6c8f2dfd25b1ee05e9fafeafc630`。本子任务只读复核了报告、七份工程、已接受音乐状态和渲染文件；七份工程/渲染 SHA 均与报告相符，没有重跑模型。

真实候选与保存内容对应如下：

| 模型 | 实际短段结果 |
|---|---|
| SCNet | 4 个音频声部 |
| TransKun | 62 音符，14 个模型 CC，另有 1 个宿主 program 事件 |
| ChordMini | 6 个和弦区间；未知置信度保持 null |
| MuScriptor | 61 音符，0 个模型 CC，另有 1 个宿主 program 事件；本样本只产生一条钢琴轨 |
| SheetSage2 | 16 音符，5 和弦，17 拍点，2 结构区间；MIDI 通道 2，1 个 program 事件 |
| ACE | 实际 12 秒音频；没有截断证据，completion 保持未知 |
| YuE2 | 实际 11.998667 秒音频；发现下面的状态适配遗漏，不能按本轮报告宣称截断提示验收通过 |

七项 proposal 均使用统一 accept 命令；接受前无工程编辑、一次接受、重复接受不产生第二次编辑、Undo/Redo、禁用云端 registry 后重开和本地渲染均有通过记录。五份 MIR 工程实际为 schema8（包括 SCNet：保存了空拍点/结构元数据），生成工程为 schema7；不要据早期计划写成 SCNet 此轮仍为 schema5。

**本次审查发现并推动修复的遗漏：** YuE2 上游真实 `truncated` 为 `{abc:false, semantic:true}`，旧适配直接转发字典而标记 `reason=unknown`。Agent 只接收 bool/null，所以丢失了明确截断提示。主任务现将任一阶段截断归一化为 true，原始阶段值保留在 `completion.stages`，非法形状拒绝发布。子任务补充 7 项生成契约回归全部通过（记录 `20261106T182643.646322Z-809a94ef2a`）；E2E 新增 canonical bool/null、Agent 方案投影、保存 `generations[].parameters_json` 中 completion/stages/实际时长保留断言，语法通过（`20261106T182647.045630Z-8b8bc26332`）。仅 YuE2 的修后真实补验由主任务另行记录；原 v3 证据保留，不覆写为已验证新形状。

本轮真实流程没有调用语言模型；使用生产 Agent 授权和方案编译器的确定性请求。多乐器真实转录质量、真实 LLM 指令理解率、物理 ASIO、界面手感和听感仍不在这份证据内。MIR 原音频保留，因此非静音渲染不能证明新 MIDI 乐器的声音已验收。

## 最终交付复核：v3 + YuE2 v4

主任务完成 `hybrid-final-20261107-v4-yue2/report.json` 的真实补验，记录 `docs/builds/20261106T182737.873455Z-b33b832482.json`。EXE 仍为上述 `d5579a…de283f`；报告 SHA 为 `6ddb19dfcb183c98ace03189b96cf5464cf485cbe06cea342cd312440a683fee`。本子任务只读检查了该报告和保存工程，独立核对工程与渲染 SHA 均相符。

这次真实 YuE2 候选的 `truncated=true`，`completion.reason=token_budget`，`completion.stages={abc:false, semantic:true}`；Agent 确认方案正确保留布尔截断标记和原因，工程 `generations[].parameters_json` 完整保留阶段详情、limitations 与实际时长 `11.998666666666667` 秒。候选产生前无工程编辑、一次接受、重复接受不重复编辑、Undo/Redo、禁用云端 registry 后重开和本地渲染五个阶段均通过；`generation_provenance_verified=true`。

因此，最终七模型功能证据采用 **v3 的其余六模型 + v4 的 YuE2**；v3 的 YuE2 保留为发现并修复真实契约遗漏的历史记录。Agent 侧统一命令、真实能力路由、候选确认及 CC/program/未知置信度/生成截断的契约交付完成。该结论覆盖短段真实推理和持久化，不扩大为整曲质量、真实 LLM 理解率或硬件听感已通过。
