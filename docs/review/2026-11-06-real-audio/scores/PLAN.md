# New Light — SheetSage2 全曲分析

状态：已按 root 分配的独占 GPU 槽执行一次，全曲处理与原始导出检查通过；准确率/听感未验收。共享评测计划由上一级 PLAN 管理，实际结果见 [RESULTS](RESULTS.md)。

- 输入 `/root/autodl-tmp/emusician/workspace/evaluations/real_audio_20261106/inputs/newlight.mp3`，原始文件 SHA256 `885891e2076ca629d3e60685a68df3be07e20da00f0ee45038b5da547519826b`，8,734,346 字节，44.1kHz 双声道，9,627,241 帧 / 218.30478458 秒。
- 模型 `m-a-p/SheetSage2@b83c3d79a6d98bcffaf8f9ed112c90aa887887bc`，MERT2 `d8ba1c745e733b3908ce6ad16ebeb17ac7600a42`；重用既有隔离环境、私有 FFmpeg、离线模型缓存。
- 原始 MP3 由上游默认读取路径完整解码和重采样。`preset=default`、BF16、全任务 prompts、300 秒窗口；不设置 `max_seconds`，不截短、不改成 melody-only。该输入不足 300 秒，原生单窗口覆盖整首。
- 保留原生 ABC / MIDI / LAB / events / tokens / result 文件；窗口实际覆盖、事件最晚位置、token 上限、ABC 导出错误和 warnings 独立记录。完整读入音频不代表识别完全正确，也不代表每种乐器都有单独谱。
- GPU 仅在 root 分配的独占槽运行。ACE 空队列且至少 12GiB 空闲准入，PyTorch 分配上限 10GiB；过程中 ACE 活跃、余量不足 1GiB 或 600 秒期限均停止本脚本拥有的子进程组。原 ACE 服务保持。
- 输出 `results/evaluations/real_audio_20261106/sheetsage2-<UTC>-<id>/transcription/`；`result-receipt.json` 记录完整输入、结果和文件 SHA，`guard-receipt.json` 记录命令进程终态、资源、时间。任何失败保留原始日志与文件；无隐式 CPU/GPU 重跑。
- 仅小证据回本地版本管理；原始谱/音频与模型留云端，不接 DAW。无参考真值时不能报告准确率，谱/和弦/旋律需人工审阅。

执行前由另一代理只读审查；针对准入拒绝、监测异常、错误结果 JSON 和 cleanup 竞争做纯 CPU 测试，不额外运行模型。
