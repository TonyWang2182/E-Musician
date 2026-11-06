# MIR 升级模型云端部署

本轮用户授权仅在现有云端数据盘部署所需模型；不下载权重、音频或备份到 E 盘，不改 DAW，不改既有 ACE 和基础 MIR 环境。小型来源/版本/安装日志允许本地留档。

范围：SCNet XL IHF 四轨分离、TransKun V2 No Pedal Ext 钢琴转录、ChordMini BTC 和弦识别。精确来源取自 `hybrid-ai/CAPACITY-20261106.json`。仅选定各一份权重，云端直接下载并验证官方 release SHA-256 或精确 Git blob，然后记录 SHA-256。

各模型独立 `models/<id>`、`envs/<id>`、固定版本源码与依赖锁；只共享不可变下载缓存。先检查文件、依赖和 CPU 加载，之后由主代理分配独占 GPU 测试时段。安装/加载/GPU 推理/听感与准确率分别记录。中央登记由主代理统一汇总，本代理只写 `manifests/model-library/<id>/deployment.json`。

SCNet 是四轨，不能称六轨升级；TransKun 是钢琴模型，踏板事件以源码/实际输出为准；ChordMini 使用固定和弦词表，不承诺任意爵士和弦。实际限制与兼容修正进入 RESULTS.md；每次命令由 Recorder 保存原始日志和追加开发日志。

状态：三模型的文件、依赖、CPU 加载和独占时段内各一次 8 秒真实 GPU 推理已验证，输出重新读取/哈希检查通过，GPU 槽已释放。仅回传小型清单/锁/日志，未将权重、音频、MIDI 或 LAB 下载到 E。准确率、听感和长音频性能未验证；详见 [RESULTS](RESULTS.md)。
