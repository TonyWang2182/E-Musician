# ACE 完整 Jungle 提示词单次测试

状态：单次真实推理、请求一致性及输出文件验证通过，音乐效果待试听。沿用现有云端 ACE-Step 1.5 XL Turbo + 1.7B LM 服务；未改服务、环境、模型或 DAW。实际结果见 [RESULTS](RESULTS.md)。

- 输入使用上级目录 `prompt.txt` 原文，仅去掉文件末尾换行。1304 字符，未超过网关 2000 字符限制；原文件 SHA256 `5f080976c665d1917c3b9a56d41dcb39f6741237f3a45b57abd9230383834c52`。
- 条件：120 秒、170 BPM、4/4、seed 170611、instrumental=true、lyrics 为空。提示中的 MC 碎片纹理要求保留；不另造歌词。
- 获取共享 GPU probe 文件锁并检查 ACE 队列空闲；唯一 ID 仅 POST 一次，不重试生成、不筛选结果。最多等待 900 秒，失败时只请求取消本次 job。
- 云端保存完整请求、提示词、能力清单、网关结果、模型版本和资源数据；验证实际 WAV 时长/格式/大小/SHA。音频留原 gateway job 目录，不下载到 E，也不复制第二份音频。
- 本地只保留小型脚本、Recorder 日志与结果元数据。结构、节奏、音色和音乐性是否满足要求，留给后续试听；参数值不等于实际音乐内容已经达标。

执行入口：`scripts/cloud/evaluations/jungle_20261106/ace_once.py`。每次执行和文件上传通过 `scripts.dev.Recorder` 记录。
