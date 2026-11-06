# 原始音频 MIR 评测（2026-11-06）

状态：准备中。基线 `0c21c01`，分支 `eval/real-audio-mir-20261106`。

用户指定 New Light 做分离、和弦识别、综合分析，另一份音频做钢琴转 MIDI。输入为 `E:/E-musician/test-projects/test9-newlight/New Light()/New Light.mp3`（218.305秒）；用户随后明确钢琴输入为 `E:/E-musician/test-projects/test9-newlight/Keyboard.mp3`（279.031秒）。两份原文件已上传并核验SHA，无裁切。

1. 原文件上传到云端独立评测 inputs；本地/云端 SHA256 一致后读取时长与格式。不得静默截短。
2. SCNet 四轨分离、ChordMini 和弦、SheetSage2 综合分析、TransKun 钢琴转录顺序占用 GPU。保留原始输出，不接入 DAW，不下载模型或新音频到 E 盘。
3. 重用固定模型版本及独立环境；新增评测脚本，保持旧服务/包装器不变。共享 GPU 锁、ACE 空队列准入、资源/时间监测，只终止各自创建的进程组。
4. 每次执行由 Recorder 留原始日志和版本化摘要；区别模型执行成功、文件有效、音乐质量人工验收。缺少真实标签时不声称准确率。
5. 交付原始 WAV/MIDI/LAB/JSON/ABC 路径、处理时间与限制；附长度预算和 MuScriptor 官方访问说明。

文件归属：root 管理输入、协调、汇总文档；cloud_ace 管理 `real_audio_20261106/mir/` 与评测文档 `mir/`；agent_generation 管理相应 `scores/`；native_generation 只读核查长度预算。GPU 串行由 root 分配。
