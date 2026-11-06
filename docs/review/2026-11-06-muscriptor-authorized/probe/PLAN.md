# MuScriptor medium 部署探针

状态：root 确认授权权重与官方配置校验后，真实 CPU 加载与一次8秒 GPU 探针均通过；准确率、整曲与听感未验收。凭据、授权与下载由 root 独占处理，本探针不查看认证文件、不接受条款、不联网下载。证据见 [RESULTS](RESULTS.md)。

固定源码 `8a1ef88672cc23c26619adaff37ec48d82c0b906`，模型 `MuScriptor/muscriptor-medium@f32236969308476e01fd3aae67357de5feb05a2d`。权重路径 `models/muscriptor/model.safetensors`，1,228,144,472 字节、SHA256 `ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec`。必须有同 revision 的邻接 `config.json`，`dim=1024 / num_heads=16 / num_layers=24 / card=1395`；不能依靠本地通用文件名的架构 fallback（上游会默认 large）。

## CPU

独立子进程设置 `CUDA_VISIBLE_DEVICES=-1`、HF offline、专用无凭据 probe HF_HOME、2 CPU 线程。`TranscriptionModel.load_model(weights_path=本地Path, device='cpu', dtype='float32')` 后检查全部参数在 CPU、数值有限、CUDA 未初始化，记录包版本、参数数目与时间。180秒上限；只加载，不在 CPU 推理，也不把加载当模型效果通过。

## GPU

只在 root 发放的独占槽启动。保留 ACE 驻留，至少12GiB空闲/ACE无任务才准入；PyTorch allocator上限10GiB；ACE新任务、低于1GiB余量或180秒触发 owned-child 停止。守护捕获SIGTERM/SIGHUP，finally保存终态，不结束其他服务。

输入为此前核对的云端 Keyboard 原件，SHA256 `5b425c8fe09cf82f99a530ae529fe7607c0b792e93d0f91455cc338fd95b632f`。明确截取起点0、长度8秒做部署探针，另存 `results/muscriptor-authorized/gpu-<stamp>/fixture-first-8-seconds.wav`。这不是完整279秒评测；既有全曲原件与TransKun结果均不改。

沿用原生float32权重及CUDA autocast、greedy、CFG1、batch1、prelude forcing、beam1，所有乐器均可识别，不硬编码只许钢琴。`no_eos_is_ok=False`，达到token上限不能静默通过。事件导出原始JSON，再经上游 `events_to_midi_bytes` 生成MIDI；不调用额外节拍模型，MIDI内120BPM是未估计tempo时的占位，非识别结果。MuScriptor不输出真实力度，MIDI力度默认值不能用于动态评价。

8秒原生分成两个5秒块，末块补2秒零。原始预测如落在8–10秒尾部，会保留并明确记录，不悄悄裁切；事件与MIDI以完整原生块10秒为验证边界，人工质量仍未验。输出包括 fixture、events、MIDI、result和guard收据，仅小收据回E盘。没有安装新依赖、没有渲染/乐谱PDF、没有DAW接入或完整歌曲推理。
