# 0.5.1 Keyscape 修复候选与人工验收

状态：2026-10-27，0.5.1 Release相关自动检查通过；用户已确认MIDI编写、播放与Keyscape使用正常。Arm/Monitor切换和实体键盘实时输入仍待分项确认；不扩大为所有插件兼容或长期稳定性通过。

## 已知证据

- 用户新建MIDI轨加载Keyscape，选择MIDI输入后切Arm/Monitor会卡顿退出。
- Windows今日4次WER记录均为0.5.0 Release、Keyscape.vst3 1.5.0.0、c0000005、模块偏移0x782693；最新转储的ASIO音频线程在Keyscape内向0x20地址写入。不是下载/构建未完成的证据。
- 原始转储位于本机CrashDumps，只读分析，未复制进版本管理；.cache/v051保存调试输出。Release旧版本没有PDB，所以不宣称全部宿主帧已符号化。
- 从最新转储恢复ProcessData：256 samples、0 audio inputs、9 output buses；堆上的完整输出数组未包含在minidump中，无法凭该转储证明具体哪个bus被误用。一次读取缺失内存的诊断命令失败已保留记录，不是应用新崩溃。
- 固定JUCE的HostBufferMapper为inactive bus保留channel数量而传null样本指针；PluginHost只启用主输出。VST3规格允许inactive的实际样本地址为空，因此这是兼容性候选，不是已证明的宿主违规。

## 用户人工对照

1. 不加载插件，新建MIDI片段、打开钢琴卷帘、双击写音符：用户确认通过。
2. 有音符的片段加载Keyscape，不选MIDI输入、不切Arm/Monitor，播放：用户报告不退出但无声。
3. Keyscape界面自己的琴键：用户报告有反应但无声。
4. 同工程导入已知有声WAV/MP3：用户确认有声，并已关闭DAW。

## 本次候选

- JUCE VST3输入/输出mapper在prepare时为inactive通道分配独立float/double存储，process只清零/复用。附加输出仍inactive，不启用、不混入主输出，不在音频回调分配内存。
- 超过setupProcessing块上限的缓冲显式拒绝，禁止scratch溢出；默认mapper调用保持既有行为，实际宿主传入明确最大块长。
- 新增实际mapper回归：active/inactive/active顺序、独立通道、float/double、模拟插件向inactive写入、隔离/清零/指针复用、变长块和超长拒绝。
- 版本0.5.1；优化Release开启PDB且显式保留OPT:REF/ICF。旧0.5程序留在.cache/v051/baseline-0.5.0.exe。
- 仅Release相关检查与用户复测；本次不重跑30分钟长跑/四插件全矩阵，不使用computer-use。

主因仍需新旧行为对照。此前只读审查还发现MIDI启用的异步更新边界；本次先不混入这一不同修复，以便判断缓冲候选是否解决用户现象。

规格依据：[Steinberg AudioBusBuffers](https://steinbergmedia.github.io/vst3_doc/vstinterfaces/structSteinberg_1_1Vst_1_1AudioBusBuffers.html)。补丁以精确源/补丁/结果哈希纳入原manifest，不直接提交_deps。

## 构建与相关自动检查

- [Release构建](../../builds/20261027T083742.671390Z-8ab8e6f706.json)成功。首次编译因新增测试缺少内部FlagCache头文件失败，补齐依赖后构建成功；原失败记录保留。
- [首次CTest](../../builds/20261027T083801.599393Z-21ba7d3201.json)4/5通过：日志、核心契约、引擎集成、控制输出隔离通过；补丁契约仍为旧两文件白名单。仅将其同步为正式清单中的四个确切文件后，[定向重跑](../../builds/20261027T084201.342150Z-3dee0ba2c4.json)1/1通过。不是单次完整5/5，也未声称本候选Debug已验证。
- 应用集成包含生产125项，新增实际JUCE mapper回归；其余工程/片段/存储/工作台/DAW报告均passed。完整性与精简报告见[candidate-summary.json](candidate-summary.json)。未在本候选重跑真实第三方插件矩阵或长跑，不沿用旧版本结果作为新测量。
- 应用构建源码指纹084b4e91；当前指纹a67e1d7f，唯一差异为Python补丁契约测试。EXE SHA-256为f7e44157b69432a02f097823a158e6e300215401c7c4cbf96289056b7754899e；匹配PDB在本地build/bin/Release，未上传。
- 一次只读复核确认四文件精确白名单、哈希和未知修改拒绝仍保留。无音频回调分配来自代码审查，不是运行时分配计数测量。

## 人工复测交接

已通知用户启动原路径build/bin/Release/E-musician.exe（0.5.1），新建测试工程，加载Keyscape钢琴音色，先点插件琴键，再选择MIDI输入、切换一次Arm/Monitor并弹键盘；分别报告声音和稳定性。不操作用户GUI，不再次启动自动音频测试。若退出，保留匹配Release/PDB分析新转储；若只无声，再区分插件主输出、监听与MIDI路由。收到结果前，不将候选标为已修复或合并为已验收交付。

## 2026-10-27 16:51 — 新增播放退出反馈，版本待确认

用户反馈写入音符后点击播放会卡顿退出。核对本机WER及CrashDumps，最新仍是16:20:41的0.5.0/Keyscape 1.5.0.0/c0000005/0x782693；0.5.1 Release生成于16:37:58。16:51检查未找到构建之后的E-musician崩溃或挂起事件，不能据此否定用户现象，也不能直接认定为0.5.1复现。已向用户确认是补充旧版现象还是重新打开新版后发生；在确认前不凭旧转储叠加新修复、不重复启动音频测试。Debug目录仍是0.5.0，当前候选路径必须指向Release。此次没有修改应用代码。

## 2026-10-27 — 修正版本辨认，尚未确认播放反馈对应构建

- 只读检查发现Main.cpp的getApplicationVersion仍硬编码0.5.0，与CMake/PE资源0.5.1不一致。改为由CMake PROJECT_VERSION传入Main.cpp专用编译定义，同时在原生窗口标题显示版本；无音频/MIDI处理修改。
- Release构建20261027T085515.875313Z-0539ec5c57成功，源码全程冻结；仅编译Main.cpp并链接。没有重新启动应用或运行音频测试。当前EXE/PDB指纹见version-identification-build.json，对应文件另存本地忽略目录.cache/v051/symbols以备后续匹配转储。
- 普通GUI没有持久化启动/崩溃日志；启动catch只覆盖初始化std::exception，不覆盖之后音频线程AV。未找到新WER不能等同于用户没有遇到退出。仍等待用户确认是否在新版重新打开后发生，不推定Keyscape已修复。

## 2026-10-27 — 用户确认MIDI编写、播放和插件恢复可用

用户原话：“没事了，现在是可以的写入midi和播放的，插件也没问题”。按用户人工反馈，将当前测试工程中的MIDI写入、播放与Keyscape使用标为通过；先前“播放退出”不再作为已确认的当前版本复现。没有进一步声称所有插件、所有音色或长期稳定性已验证，也未凭此证明崩溃唯一根因。

Arm/Monitor切换与实体键盘实时输入尚未得到分项确认，已给出一次简短复测：Arm打开、Monitor On弹键、Off再On；若已测可直接反馈。本次只更新验收档案，不改应用、不重建、不启动自动音频测试。
