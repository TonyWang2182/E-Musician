# 用户真实音频：整曲 MIR 评测

状态：SCNet、ChordMini、TransKun 三项整曲推理及结果文件检查通过；各一次实际模型调用，质量待试听/真值核对。故障和资源证据见 [RESULTS](RESULTS.md)。原部署 wrapper 的120秒上限保持不变；本轮新入口拒绝超过1200秒的文件，不裁切任何获准文件。

- 输入 `newlight.mp3`：云端 `workspace/evaluations/real_audio_20261106/inputs/`；SHA256 `885891e2076ca629d3e60685a68df3be07e20da00f0ee45038b5da547519826b`。父代理已上传并核对，218.30478458秒、44.1kHz双声道、9,627,241帧、8,734,346字节。
- 顺序：同一完整 MP3 先 SCNet XL IHF 四轨分离，再 ChordMini BTC 和弦识别。用户已明确另一素材为 `Keyboard.mp3`，云端 `piano.mp3`，SHA256 `5b425c8fe09cf82f99a530ae529fe7607c0b792e93d0f91455cc338fd95b632f`，279.030975秒；第三项 TransKun V2 已完成。
- 固定原部署源码、模型和独立环境，不改 ACE、基线 wrapper、系统 Python 或 DAW。评测结果单独放 `results/evaluations/real_audio_20261106/<model>-<timestamp>/data/`；metadata/log 放父目录。

## 原实现依据与资源边界

固定版本源码已只读检查，Recorder `20261106T124527.024327Z-b0039708a1`：SCNet `utils/model_utils.py:54–149` 使用整曲 CPU result/counter/estimated 缓冲，只有每个11秒窗口传到GPU；batch=1、overlap=4、AMP保持已验配置。TransKun `ModelTransformer.py:729–848` 使用完整波形和默认 segment/hop 滚动推理，保留合并和CC，不额外裁切事件。ChordMini 保留整曲CPU CQT及GPU batch1分类，核对所有feature帧均预测，原生标签覆盖末尾的差值单独记录；不凭空延长末标签，不把最多一个hop的尾差等同裁切输入。

共享文件锁、ACE队列为空、GPU空闲至少8GiB、云盘至少50GB才准入。完整输入的保守CPU预算为 `max(8GiB, 2GiB + 20×48kHz双声道float32 PCM字节 + 3×输入文件字节)`；它是准入余量而非已测峰值。有效主机余量取 `/proc/meminfo` 与 cgroup 限额减当前占用的较小值，防止把宿主机空闲当作实例配额。每个worker的PyTorch allocator上限8GiB；运行中监测ACE新任务、GPU空闲1GiB、有效主机余量2GiB、worker采样RSS12GiB和30分钟截止，触发时仅终止本次owned进程组。不会OOM后CPU重跑，也不会调整模型来重抽结果。

输入帧数、SHA、重采样后帧数、模型版本、完整处理参数、阶段耗时、CUDA/RSS采样值与文件大小/SHA进入结果。SCNet输出FLOAT WAV且不削波/归一化，逐块重读验证；ChordMini输出LAB+JSON；TransKun输出原始MIDI并检查合法音符/CC，任何超出源时长的事件明确记录。没有人工标注真值，不从结构检查推断准确率。

脚本：`scripts/cloud/evaluations/real_audio_20261106/mir/`。执行使用Recorder；新权重/音频不下载到E，本地仅小脚本和元数据。
