# ACE 单次完整提示词结果

2026-11-06 12:18:29 UTC，通过现有 loopback 网关提交一次完整 Jungle 提示词，成功生成 120 秒音频。没有改写、截断、重新抽取、修改服务/环境或接入 DAW；音频仅保留云端。本结果证明推理及文件检查通过，不代表音乐性或提示遵循已验收。

## 输入与执行

- job ID：`jungle-ace-20261106T121829Z-1a3810e6d6`。
- 完整提示词 1304 字符；原文件 SHA256 `5f080976c665d1917c3b9a56d41dcb39f6741237f3a45b57abd9230383834c52`。只去掉末尾换行后的请求 prompt SHA256 `d52750d660e226231a13f846b1ac8ceecbcfb11dc446c13456b0d853333e9678`；未超网关 2000 字符限制。网关返回的所有条件参数与提交请求逐项相等。
- 条件：120 秒、170 BPM、4/4、seed 170611、instrumental=true、lyrics 为空。MC toasting 碎片仍保留在 caption 要求中；既有适配器将纯音乐 lyrics 转为模型的 `[Instrumental]` 标记。
- 共享 GPU probe 锁获得后，确认 ACE 队列无活动任务；仅一次 `POST /jobs`。最终 `ready`，没有超时、取消或重试。完成后队列为空、共享锁释放。
- 机器：RTX 5090，报告总显存 32607 MiB。前后 NVIDIA 报告均为 used 17337 / free 14774 MiB；现有 ACE 已驻留，热启动。未修改或重启模型服务。

## 模型与数据

- ACE-Step 1.5 XL Turbo，源码 commit `ca1e85fe9430179831e6bc6be790c332190a3866`。
- 权重清单 revision `4228da3a418e1f1a04d9799e8040b62860d26b7a8c4e80ce374a17e5418cc4bf`；现有 `ace-model-lock.json` 固定具体模型文件。
- 语言模型 `acestep-5Hz-lm-1.7B`；PyTorch 2.10.0+cu128 / CUDA 12.8 / BF16，8 步，batch=1。没有切换模型或推理策略。
- 音频：`/root/autodl-tmp/emusician/jobs/generation/jungle-ace-20261106T121829Z-1a3810e6d6/audio.wav`。
- 云端评测材料：`/root/autodl-tmp/emusician/results/evaluations/jungle-20261106/jungle-ace-20261106T121829Z-1a3810e6d6/`，含完整 prompt、request、capabilities、receipt、evaluation JSON；没有重复保存音频。
- WAV 实际为 5,760,000 帧、48 kHz、双声道 PCM16，**120.000 秒**、23,040,044 字节；SHA256 `0b01f1e6a15af055ce7483bba5f4cd2f647e39d1e34059684100ae6cfa9986f4`。实际文件大小、SHA、WAV 头与结果清单已对照。

| 本次测量 | 实际数值 |
| --- | ---: |
| 驻留模型加载检查 | 0.000716 秒 |
| 模型推理 | 13.630906 秒 |
| 服务生成含后处理 | 13.859322 秒 |
| 外围评测含轮询/文件校验 | 14.759540 秒 |
| PyTorch 峰值 allocated | 16,511,014,400 字节 |
| PyTorch 峰值 reserved | 17,565,745,152 字节 |
| 导出前浮点 peak / RMS | 0.891251 / 0.145323 |

显存值来自服务内部 PyTorch 统计，包含驻留分配，不能当作此任务新增显存；不是整卡全进程峰值。峰值/RMS 是转换 PCM16 前的模型输出统计，不是响度测量。只有这一次样本，没有冷启动或重复测量结论。

## 记录与尚未验收

- 目录准备：Recorder `20261106T121818.105110Z-1974e34b28`。
- 上传小脚本和原提示词：`20261106T121819.224005Z-96f516418a`。
- 唯一真实生成：`20261106T121828.283919Z-ebaab29915`；原始 stdout 在忽略目录 `build-logs/`。执行脚本 SHA256 `e0eba0a93c837bed5ccae740203833ec79fa82c4d83a81a580d051f1858e7ec9`。
- 小型证据见 [evaluation.json](evidence/evaluation.json)、[request.json](evidence/request.json)、[receipt.json](evidence/receipt.json)。没有把模型、音频或备份下载到 E。

170 BPM 与六段结构是条件要求，尚未证明音频实际完全遵循。Amen 切分、sub、MC 碎片、无完整演唱、六段展开和混音听感均待人工试听；另一路 CPU 客观检查的结论以其记录为准。同 seed 也不保证与其他架构模型可作严格统计对比。
