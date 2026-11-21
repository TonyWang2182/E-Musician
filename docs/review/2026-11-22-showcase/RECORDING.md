# 实时录音波形（2026-11-22）

状态：代码已实现，统一 Release 构建成功，新增录音生产管线离线测试复测通过；未做实体麦克风与听感验收。

## 目标与范围

基于 0.13.6 的实际录音管线，在录音轨显示随真实捕获数据延伸的波形。用户自行拍摄 Demo 4，不安装虚拟音频线，不使用预制波形模拟录音。保留线性录音、逐轨 Arm/Monitor、预备拍、Undo 和工程存储语义。

## 已核查的依据

- 固定 Tracktion 的 `UIBehaviour::shouldGenerateLiveWaveformsWhenRecording()` 默认开启，当前 `NativePluginUI` 未覆盖该开关。
- `WaveInputRecordingThread::run()` 在后台写 PCM 后更新 `RecordingThumbnailManager`，不是在实时音频回调绘图或重新读录音文件。
- 宿主当前仅在 `recordingFinished` 后登记正式 clip，Arrangement 只绘制正式 clip，因此缺少录音进行中的显示层。
- 引擎缩略图为 1024 样本一级的峰值数据；它的长度有量化，不能作为最终样本数。显示范围使用录音音频时钟，停止后使用正式 clip 时间。

## 实施设计

1. RecordingController 在消息线程拥有每次录音的缩略图句柄，公开瞬态只读 DTO 和按 ID 绘制入口；UI 不持有跨引擎生命周期的 Tracktion 对象。
2. Arrangement 复用已有 30 Hz 更新，只绘制可见录音轨；预备拍不画提前写入的波形，单/双声道按真实捕获显示。
3. 峰值来自引擎已经延迟校正过的写盘数据，不再次补偿延迟。停止后保留缩略图，正式 clip 峰值准备好才交接。
4. 预览不写工程、不增加修订号、不制造 Undo；取消、失败、换工程、Undo 和新录音必须清理失效预览。

## 验证计划

扩展已有 fake audio device 生产管线测试，核对录音中的真实峰值/增长、独立声道、Monitor Off、停止后交接、预备拍取消及过期身份；这些结果不代表实体声卡听感通过。统一构建和实际运行结果由主代理归档，后续补记于本文件。

## 本次代码与测试范围

- `EngineSessionRecording.inc` 维护每次 take 的消息线程缩略图引用，沿用引擎后台写入后的峰数据；公开接口只返回身份和显示范围。错误输入、Undo、新工程及下一次录音清理相应引用。
- `EngineSession.h`、`EngineSessionPublic.inc`、`EngineSessionProduction.h` 增加只读预览/绘制/完成交接释放 API。工程身份不符和过期 take 拒绝绘制；不写 JSON、不新建音乐状态、不改变录音路由。
- `ArrangementView.cpp` 在已有 30 Hz 刷新中仅绘制可见轨矩形和真实声道波形；正式 clip 出现后继续使用同一缩略图，普通峰缓存就绪才释放。
- `EngineSessionAudioInputSmoke.inc` 扩展六种真实录音回调路径：稀疏 In 2、完整通道数组、空输入静音、In 1、In 2、立体声；同时检查实际绘图像素、峰值来源、重复 take 身份与增长、准确正式长度、Monitor Off、修订号不变、预备拍取消、非零录音起点、Undo/Redo 和过期身份。
- 未添加音频回调工作。原生峰缓存内部有自身同步，不能据此宣称整条显示链“完全无锁”。没有实机性能采样，刷新流畅度仍需用户声卡与实际工程验收。

## 首轮离线反馈与修订

统一 Release 构建成功，但首轮 CTest 的 `engine.integration_smoke` 在新增绘图断言失败（其余 10 项通过）；原始日志 `build-logs/20261121T163740.245968Z-edb5d9b574.log`。因此此时不能宣称录音波形验证通过。已将绘制入口收紧为只调用 `getApproximateMinMax` 读取内存峰值，按可见像素与真实声道绘制，避免通用 AudioThumbnail 绘图可能选择源读取器的分支，并保证恒定电平/静音具有最小可见线宽。具体触发首轮失败的 PCM case 尚待新增诊断图确认，不把推测当作已证实根因。

新增每个 callback case 的 `fixture-audio-input-live-preview-N.png` 与有符号幅度像素断言；图片仅用于离线回归，不能作为真实麦克风录制素材。待主代理统一增量构建与复测。

## 增量构建后复测

`engine.integration_smoke` 1/1 通过，87.31 秒；日志 `build-logs/20261121T164548.843388Z-e95679d452.log`，产物 `E:/emusician-analysis-source/build/smoke/Release/012e283e7907`。六种物理 callback 路径、实时图像/幅度、增长、停止交接、count-in取消、非零起点/延迟声明及 Undo/Redo 等新增断言均随生产测试通过。已人工查看该产物中 case 5 的双声道正负电平线及 case 2 的静音中心线；这只证明确定性离线 PCM 到录音峰绘图的连通，不是实际声卡与音乐录制听感验收。其余 CTest 项与构建明细由主代理统一汇总。

## 最终只读复核

该产物 `production-smoke.json` 记录生产检查 **1180 项通过**，输入是生成的 hosted buffers、48 kHz、256 样本块，不是实体输入。绘图入口检查有限时间与缩放、有效区域和项目身份；峰幅度检查有限值。预览对象只在控制/消息线程持有，写线程沿用引擎既有缩略图发布。停止前刷新，按文件与目标轨关联正式 clip，正常峰缓存就绪才释放；失败无 clip 的预览在 `poll()` 清除，取消、换工程与 Undo 也清理。预备拍使用真实音频时钟且处理尚未提交的播放起点；显示不重复补偿延迟，也不将 1024 样本峰单元当最终长度。

未发现需要阻断当前构建的新增生命周期问题。保留局限：现有线性录音边界不变；未做长时间、多输入硬件压力、DPI 与实际听感测试，峰缓存有内部锁，不能宣称完全无锁或量化性能已达标。

只读复核原 0.13.6 EXE SHA-256 为 `81020b783de6540746de5a81215ea8a62cc133f4d8202a30d40add3b98940699`，原创 `test drive.emproj` 为 `e13df1fcbea22af69abbbdcaf0b5dae7ae51f9e464ff1de3b59260dae2162d4d`，均与 `build-logs/showcase-v1-baseline.json` 相同。

交付入口复核：`E:/MusicAgent&DAW/Start E-musician Recording.cmd` 指向存在的 `E:/emusician-analysis-build/bin-0.13.6-recording/Release/E-musician.exe`，展示版入口指向独立 `bin-showcase-v1/Release/E-musician.exe`。本次复核只读脚本和文件，不据此声称又完成了一次界面启动或实体录音。

调用点复核：新增预览更新仅来自 Arrangement 消息线程刷新与录音停止控制流程；新增绘图仅来自 UI。固定依赖 `playback/devices/tracktion_WaveInputDevice.cpp` 的写线程在写入块后调用原有 thumbnail `addBlock`，本改动没有在音频回调加入读写文件、网络、JSON 或推理工作。`recordingFinished` 已有的文件存在性核查位于控制线程收尾，不是新增音频回调 I/O。引擎内部原有的同步与队列并未在本次被改成无锁实现。
