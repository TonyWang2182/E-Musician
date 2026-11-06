# 0.12.1 生成 Agent 与本地分析故障隔离

2026-11-06，状态：实现及自动验证收尾。用户在0.12.0人工测试发现生成总追问BPM、分离生成音频时Python错误弹窗及DAW白屏。先修复这两个问题；用户随后明确授权并行准备其他云端模型，安装工作独立记录在 [云端 MIR 阶段](../2026-11-06-cloud-mir-stage/PLAN.md)，不混同本轮 DAW 修复验收。

基线提交 `61c9384`，分支 `fix/generation-stability-v0121`；0.12.0 EXE及源码已保留于 `E:/MusicAgent&DAW/releases/0.12.0-20261106-cloud-generation`。完整云端模型备份已经验证，不重下模型、不重启云服务。实际工作树为 `E:/MusicAgent&DAW/worktrees/audio-analysis`。

## 已知证据与边界

- Agent快照已有BPM/拍号/播放头，但通用计划提示、必填时长和模型自行换算小节会增加追问。当前用户看到的是GPT-5-mini；不因这一现象断言模型本身无法完成任务。
- 本地HTDemucs执行分离，云端5090目前只执行ACE生成。用户本机RTX3050 Laptop 4GB、约32GB物理内存；诊断时系统剩余提交额度约2.8GB，物理可用约6GB。
- 22.4秒四轨任务有CUDA OOM；另一次CUDA OOM后同进程model.cpu()再次发生CPU内存不足，连1MiB分配也失败。
- 75秒六轨quality任务最后停在separating、无result/error，截图为python.exe空指针读取错误。尚无该次原生堆栈和对应Windows事件，因此不声称已证明该次NULL崩溃的唯一根因。
- 历史7秒六轨quality测试RSS约1.28GB、CUDA allocated约650MB，只是短样本；不能推出资源紧张时75秒任务稳定。

## 文件归属与实现顺序

1. `agent_generation`：scripts/music_agent与对应测试；从新鲜工程快照注入默认参数，小节换算由程序处理；保留明确导入确认。记录AGENT-RESULTS。
2. `cloud_ace`：scripts/audio_analysis与worker测试；重依赖加载前资源检查，去掉CUDA OOM后同进程盲目CPU回退，减少音频缓冲复制，进程局部崩溃诊断。记录WORKER-RESULTS。
3. `native_generation`：C++分析子进程生命周期、退出码与可见错误、后台线程启动失败；Windows JobObject隔离和资源保护。记录NATIVE-RESULTS。
4. 主代理：证据封存、整体计划/版本/统一构建与集成回归、开发日志/上下文/架构及最终手动验收入口。

资源准入值是保守防护策略，不是模型性能保证；本地/worker策略协调一致。不得自动改系统分页文件、结束用户其他程序，或在低内存条件下反复运行大模型制造崩溃。每次构建/测试用Recorder，失败照实保留。原始日志在build-logs，不进入Git。

## 验收

- 无BPM/时长的普通生成意图能沿用工程默认值；小节换算覆盖不同速度和拍号；明确用户要求不能被默认值覆盖，不将咨询问题当成付费推理指令。
- 缺少内存时在加载模型前拒绝；CUDA OOM可解释失败，不隐式继续CPU；故障进程不能留下等待用户点击的模态错误框。
- 子进程异常退出/取消/低资源停止均有终态，宿主仍能响应公共命令；不新增轨道、不改变原片段。
- 有意义的Agent、worker、原生契约及相关引擎回归；再决定是否能安全做短真实分离。模拟资源测试与真实模型测试分开报告。
- 最后由用户确认自然语言、真实试听及生成音频分离。自动回归不替代人工通过。

## 后续模型计划

这轮之后优先迁移远端HTDemucs并打通上传/下载/对齐，再评测SCNet四轨、TransKun钢琴和ChordMini和弦；YuE2、多乐器转录及谱面放后续。各环境独立，单卡重任务排队。完整选择与限制沿用[混合部署方案](../2026-11-06-hybrid-ai/PLAN.md)，已实现部分以最新CONTEXT为准。
