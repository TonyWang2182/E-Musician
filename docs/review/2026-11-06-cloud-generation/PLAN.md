# 0.12 云端生成接入

2026-11-06，状态：实现中。用户授权按既有混合部署计划配置生成模型，接通 DAW 手动与 Agent；本批先交付 ACE 文字/歌词到音频闭环，YuE2 和 MIR 模型升级仍按后续批次。

基线 `0219f9adb26b258b7275112abc02f1e4d881458f`，工作分支 `feature/cloud-generation-v0120`，实际工作树 `E:/MusicAgent&DAW/worktrees/audio-analysis`。原有 SSH/混合部署文档、启动记录和 DEVLOG 修改保留；0.11.0 EXE 不覆盖。

## 顺序与归属

1. 云端：核验 RTX5090，锁定 ACE 上游与权重版本，独立运行环境和真实短音频推理；单 GPU 持久队列和仅 loopback 的网关。`cloud_ace` 负责 `scripts/cloud/ace*`、`gateway*` 和 CLOUD 证据。
2. 主代理：`scripts/cloud/run_generation.py`，受管 SSH 隧道、幂等提交、轮询/取消、下载校验、E 盘候选，部署登记与跨层测试。
3. `native_generation`：C++ generation 命令、候选试听、明确接受/一次 Undo/本地保存来源，简单生成界面、版本和原生测试。生成不冒充已有音源分析。
4. `agent_generation`：Python Agent 工具、能力、方案确认/回读与侧栏呈现和测试。
5. 主代理统一构建、整链验收、审查、更新上下文/架构/日志与人工检查。子代理不独立运行应用构建。

## 接口约束

原生公共命令为 get_generation_capabilities、start_generation、get_generation_job、cancel_generation_job、get_generation_result、preview_generation_result、stop_generation_preview、accept_generation_result。新任务固定工程、BPM/拍号、时间起点、prompt/lyrics、10–120秒目标时长和 seed；没有源片段也可生成。目标时长/BPM是生成条件，不保证实际音乐精确对齐。

原生文件线程启动固定 helper `scripts/cloud/run_generation.py --request <request.json>`。helper 从本地登记读取受信 SSH 别名，以独立隧道连接远程127.0.0.1:18081；模型服务、聊天 API 凭证和实时音频隔离。云端以 request_id 幂等，单重任务，有限队列；关闭连接不冒充取消计算。

云端结果经大小、SHA256、WAV格式/时长校验后原子发布到 E 盘，再成为可试听候选。接受必须复核候选、工程和版本，在本地复制独立资产并一次提交；普通保存重开与播放不依赖云端。未接受候选不自动改写工程，不新增工程自动保存。

## 验收

- 真实模型输出与模拟协议测试分别记录；固定源码、依赖、模型 revision、机器、请求、耗时及输出 hash。
- 错误参数、坏文件、hash不符、断线幂等、取消、服务不可用和重启中断。
- 原生 GUI/Agent 公共接口，试听、添加新轨、重复接受拒绝、一次 Undo/Redo、保存重开、离线音频渲染。
- 旧原生/Agent 回归；界面最小尺寸和中英文检查。真实鼠标/IME/ASIO与音乐听感最后人工验收，不由编译或离线测试推断。
- 构建尝试使用 Recorder；原始日志 build-logs 或 E 盘 cloud-inference/logs，摘要 docs/builds。保留所有失败修正记录。

不在本批宣称完成完整 H1/H2/H3 或任意模型/任意歌曲质量；不自动创建新租用实例或增加 GPU；新产物不覆盖0.11。
