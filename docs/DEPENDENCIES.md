# 依赖版本与来源记录

更新日期：2026-10-29。机器可读基线为 [cmake/dependencies.json](../cmake/dependencies.json)。Tracktion/JUCE按完整提交固定；VST2接口按固定提交中的三个blob固定；ASIO按官方SDK包及逐文件SHA-256固定。依赖工作区位于被忽略的`_deps/`，不进入本项目版本管理。实现与本轮验证进度分别见 [ARCHITECTURE](ARCHITECTURE.md) 与 [CONTEXT](CONTEXT.md)。

## 固定组合

| 依赖 | 版本标识 | 固定提交与来源 | 本地位置 |
|---|---|---|---|
| Tracktion Engine | `VERSION.md`为3.2.0 | [`b0c7dd090a56b27fe01bb394617891906eb34daf`](https://github.com/Tracktion/tracktion_engine/tree/b0c7dd090a56b27fe01bb394617891906eb34daf) | `_deps/tracktion_engine/` |
| JUCE | 8.0.6 | [`19edd538429c93d277bf95b55aaa7e3eb545f951`](https://github.com/juce-framework/JUCE/tree/19edd538429c93d277bf95b55aaa7e3eb545f951) | `_deps/tracktion_engine/modules/juce/` |
| VST2接口头文件 | 文件头标为VST SDK 2.4，仅三个接口文件 | JUCE历史提交[`a54535bc317b5c005a8cda5c22a9c8d4c6e0c67e`](https://github.com/juce-framework/JUCE/tree/a54535bc317b5c005a8cda5c22a9c8d4c6e0c67e/modules/juce_audio_processors/format_types/VST3_SDK/pluginterfaces/vst2.x) | `_deps/vst2_sdk/pluginterfaces/vst2.x/` |
| ASIO接口头文件 | ASIO SDK 2.3.4，官方2025-10-15归档 | [Steinberg官方ZIP](https://download.steinberg.net/sdk_downloads/ASIO-SDK_2.3.4_2025-10-15.zip)，仅取三个common接口头与原LICENSE | `_deps/asio_sdk/common/` |

JUCE使用此Tracktion提交固定的子模块，不独立追踪最新分支。Tracktion部分模块头仍写3.1.0，因此复现与问题定位以完整Git SHA为准。VST2的三个历史头文件只补充当前JUCE构建所需接口，不把JUCE 8.0.6替换成历史版本。

Tracktion上游`.gitmodules`使用SSH URL；本项目`bootstrap`只在本地checkout中将JUCE子模块地址配置为HTTPS，不修改全局Git配置。已有非空的错误版本checkout会被拒绝，不自动覆盖。[bootstrap_vst2.py](../scripts/bootstrap_vst2.py)核验下列Git blob SHA-1，同时将来源、SHA-256写入本地[SOURCE.json](../_deps/vst2_sdk/SOURCE.json)：

| 文件 | 固定Git blob SHA-1 |
|---|---|
| `aeffect.h` | `f59acd8cdf205dc36ceaff2d4c1054fa3e8e863d` |
| `aeffectx.h` | `44bd2e274fbd1b01d5ee8a65e3ae30d9fccbdc79` |
| `vstfxstore.h` | `ad7c91ee1211fa03d43d58317d7f95f6e30f925c` |

这组来源记录解决构建可复现性，不等同于发行授权。安装的第三方插件及音色库不是本仓库依赖，不随bootstrap下载或随工程复制。

### ASIO固定包与校验

固定JUCE 8.0.6开启`JUCE_ASIO=1`需要外部`iasiodrv.h`；不能将后续JUCE主分支内置接口的说明套用到本checkout。[bootstrap_asio.py](../scripts/bootstrap_asio.py)从上述Steinberg官方URL下载并在内存中核验整个8910208字节ZIP，再核验允许清单中的成员；不会执行归档内容、安装驱动或修改注册表。只安装下列文件，保留原许可；将来源写入忽略目录的`_deps/asio_sdk/source.json`。

| 核验对象 | SHA-256 |
|---|---|
| 整个ZIP | `d5ebf0c20dd2c5f43771fd0c1418f4b361bf52434ee670097cfa6b3a335e2eca` |
| `common/iasiodrv.h` | `86ad4788452c74823653cf57d4bd557c48bb6542d7e6eb7fff80102c705a066d` |
| `common/asio.h` | `93d2f80d49b4ac9c963514e7c1307ab5111d8104246192233745beb058534ea1` |
| `common/asiosys.h` | `f44a1ed0fd7c056ff047aeebc4c05a8c185f0585a24d8debc55c70107777dbef` |
| `LICENSE.txt`及`common/LICENSE.txt` | `61e56814f24b32216884b2db0b4dcc317111a5ab354d54d19dd9fc13d71b1c7a` |

`scripts/dev.py bootstrap`已包含ASIO准备步骤，CMake用`--verify-only`检查已安装文件，此检查不联网、不写文件。独立脚本的`--archive <path>`可使用已下载的同一官方ZIP，仍执行全部哈希核验。运行这些依赖操作同样经过Recorder；缺失或不匹配时应核查来源，不能仅改成当前文件的新hash来绕过固定版本。

## 已读取的许可文本

以下是固定checkout中的文本记录，不表示本项目已选定发行许可或取得商业授权。

| 项目 | 固定版本中的声明 | 文本入口 |
|---|---|---|
| Tracktion Engine | GPL 3或更新版本 / 商业许可双授权；含另有许可的第三方代码 | [本地LICENSE.md](../_deps/tracktion_engine/LICENSE.md) · [固定提交文本](https://github.com/Tracktion/tracktion_engine/blob/b0c7dd090a56b27fe01bb394617891906eb34daf/LICENSE.md) |
| JUCE Framework模块 | AGPLv3 / JUCE商业许可双授权；所含依赖各有许可 | [本地LICENSE.md](../_deps/tracktion_engine/modules/juce/LICENSE.md) · [固定提交文本](https://github.com/juce-framework/JUCE/blob/19edd538429c93d277bf95b55aaa7e3eb545f951/LICENSE.md) |
| 此JUCE内附VST3 SDK | 文件标示Steinberg VST3专有许可 / GPLv3，适用范围见各文件声明 | [本地SDK许可](../_deps/tracktion_engine/modules/juce/modules/juce_audio_processors/format_types/VST3_SDK/LICENSE.txt) · [固定提交文本](https://github.com/juce-framework/JUCE/blob/19edd538429c93d277bf95b55aaa7e3eb545f951/modules/juce_audio_processors/format_types/VST3_SDK/LICENSE.txt) |
| 本次补充的VST2接口 | 文件头标示2018 Steinberg保留所有权利，并写明无事先书面同意不得分发SDK的部分或全部；保留原文件声明 | [本地aeffect.h](../_deps/vst2_sdk/pluginterfaces/vst2.x/aeffect.h) · [固定提交文本](https://github.com/juce-framework/JUCE/blob/a54535bc317b5c005a8cda5c22a9c8d4c6e0c67e/modules/juce_audio_processors/format_types/VST3_SDK/pluginterfaces/vst2.x/aeffect.h) |
| ASIO SDK 2.3.4接口 | 固定归档LICENSE提供Steinberg专有条款或GPLv3的选择，并要求注意文件内的单独声明；保留原文 | [本地LICENSE](../_deps/asio_sdk/LICENSE.txt) · [官方固定归档](https://download.steinberg.net/sdk_downloads/ASIO-SDK_2.3.4_2025-10-15.zip) |

Tracktion与JUCE分别授权；上游Tracktion [README的License部分](../_deps/tracktion_engine/README.md#license)明确区分两者。此处记录固定源码附带文本，不用其他SDK版本或后续网页条款替换该版本记录。VST2头文件保留在忽略的本地依赖目录，下载脚本成功不代表上述发行事项已经处理。

ASIO的[官方专有许可FAQ](https://forums.steinberg.net/t/asio-sdk-proprietary-licensing-faq/1044024)区分内部开发测试和对外分发；本次只准备本地开发依赖，没有代用户签署协议、声明商业发行授权或分发SDK。具体发行路径仍须按实际采用的许可与依赖文本确认，bootstrap成功仅证明来源与文件完整性。

Tracktion内附第三方库清单见其[README](../_deps/tracktion_engine/README.md#license)，JUCE内附库及逐项文本见其[LICENSE.md](../_deps/tracktion_engine/modules/juce/LICENSE.md#the-juce-framework-dependencies)。例如Tracktion包含CHOC、crill、rpmalloc、libsamplerate；JUCE图形、音频格式与插件模块另含第三方实现。发行时按实际链接模块整理许可和通知清单，不把这些代码归为单一依赖许可。

## 当前构建与运行边界

原生目标链接`tracktion_engine`、`tracktion_graph`、`tracktion_core`、JUCE音频工具及提供SHA-256的`juce_cryptography`。Windows目标另链接系统`bcrypt`库；会话内容键通过CNG `BCryptHash`计算同一SHA-256，非Windows、原生调用不可用或失败时回退JUCE实现，不改变内容键算法及工程格式。哈希仍在控制/worker侧执行，不进入音频回调。当前构建开关如下：

| 能力 | 配置与边界 |
|---|---|
| VST2 / VST3宿主 | `JUCE_PLUGINHOST_VST=1`、`JUCE_PLUGINHOST_VST3=1`；Windows x64；已接入扫描、加载、编辑器、参数与状态保存，兼容验收见CONTEXT |
| MP3读取 | `JUCE_USE_MP3AUDIOFORMAT=1`；先转统一PCM再播放和画波形；不支持MP3导出 |
| ASIO | 0.5源码为`JUCE_ASIO=1`，包含固定SDK common头；保留其他Windows音频后端。编译/驱动打开/实际buffer/硬件录音分别验收，不能由开关推断通过 |
| 内嵌网页与CURL | `JUCE_WEB_BROWSER=0`、`JUCE_USE_CURL=0`；当前UI是原生JUCE |
| SoundTouch伸缩 | `TRACKTION_ENABLE_TIMESTRETCH_SOUNDTOUCH=0`；音频不随BPM自动伸缩 |

插件扫描逐模块使用独立子进程；WAV渲染也使用独立worker。正常播放中的外部插件仍在DAW进程内，尚无运行期插件崩溃隔离。格式开关不代表32位插件、多输出、侧链或所有厂商版本已兼容。插件程序与外部音色库不随工程包归档。

录音使用上述固定Tracktion的InputDeviceInstance、TransportControl与writer线程，自动化使用原生AutomationCurve，音频bus/send使用AuxReturn/AuxSend。代码复盘发现原生录音queue包含锁及耗尽时的动态分配，停止录音还会等待writer收尾；没有为这些路径编造零分配/无锁或固定最坏耗时保证。合成Hosted输入回归和真实M-Audio ASIO/SL GRAND测试必须分别记录。读取到驱动注册项或用户确认型号不等同于驱动已经成功打开。

0.4.0将音频片段的重采样选择设为`ResamplingQuality::sincMedium`。默认Lagrange在44.1→48kHz复制片段测试中出现持续的块相关相位调制；改用sinc后，trim测试进一步暴露首次源定位舍入造成的固定亚样本偏移。应用侧质量选择不足以修复后者，因此固定Tracktion基线之上增加下述可核验源码补丁。应用补丁后的Debug与Release回归均4/4通过；当前44.1→48kHz夹具的trim、复制后对应源区间及256/512帧块渲染最大样本差均为0，原`2e-5`阈值未放宽。见[Debug音频报告](../build/smoke/Debug/ab9fcfa12259/daw-report.json)、[Release音频报告](../build/smoke/Release/ae529f5d8934/daw-report.json)及[ADR中的失败证据与验证边界](decisions/0005-daw-baseline-and-control.md#重采样源定位补充2026-10-27)。正反向全部采样率与medium/best矩阵尚未覆盖，实际设备长跑仍待测。

## MP3与测试素材

0.2.0加入MP3读取。本项目[AudioSource](../apps/desktop/AudioSource.cpp)扫描完整MPEG Layer III帧数，再调用固定JUCE `MP3AudioFormat`顺序解码为24-bit PCM WAV；Tracktion和波形随后使用同一PCM。此前发现固定解码器对无Xing索引VBR按首帧码率估长，[失败记录](builds/20261026T105710.115448Z-e0ea78b31d.json)和[0.2.0修复报告](verification/2026-10-26-m2/RESULTS.md)均保留，不能当作0.4.0验证。解码器声明见[固定版本实现](../_deps/tracktion_engine/modules/juce/modules/juce_audio_formats/codecs/juce_MP3AudioFormat.cpp)。

PCM缓存按原MP3内容哈希放在`%APPDATA%\E-musician\cache\audio-v1`，原MP3另行归档。0.4.0导入在后台worker完成扫描、解码和准备，支持进度、取消及主线程最终提交；不在实时音频回调中解码或访问文件。缓存没有自动清理，也未实现编码器padding裁除。运行无需FFmpeg、LAME或Python编码器。

MP3回归样本来自本项目公式合成，包含CBR双声道和VBR单声道；文件及PCM哈希、编码参数、生成环境见[manifest](../tests/fixtures/audio/manifest.json)。生成工具固定为`lameenc 1.8.1`、Python 3.12.6、Windows x64 wheel，安装于忽略目录`.cache/fixture-encoder`。它只用于重建测试样本，不是编译或运行依赖，不进入应用包。精确wheel哈希、生成步骤和LGPLv3工具许可见[素材说明](../tests/fixtures/README.md)；合成录音本身采用CC0-1.0。

## 本地补充与升级流程

上游基线仍为 `b0c7dd090a56b27fe01bb394617891906eb34daf`。[补丁清单](../cmake/patches/tracktion/manifest.json)采用 schema 2，分别记录下述四个源文件及各自的统一差异、应用前后 SHA-256；哈希按 UTF-8/LF 标准化计算，应用时保留 checkout 原有换行格式。

[apply_engine_patches.py](../scripts/apply_engine_patches.py)的`apply`/`verify`核对 HEAD、全部清单项、差异上下文与输出哈希；0.6.0逐项原子替换清单列出的九个源文件，不改写其他上游文件。未应用补丁、错误提交、未知修改、哈希不符或路径越界都会拒绝，已经应用的确切结果可重复核验。`scripts/dev.py bootstrap`负责应用，CMake 配置阶段只核验。脚本回归使用独立临时夹具，不依赖真实 checkout 当前是否已打补丁。

### HQ sinc 源定位补丁

此项差异作用于 `modules/tracktion_engine/playback/graph/tracktion_WaveNode.cpp` 的 HQ reader，[统一差异](../cmake/patches/tracktion/hq-sinc-seek-phase.patch)进入项目版本管理。

| 核验对象 | 标准化LF SHA-256 |
|---|---|
| 上游源文件 | `93a8eb18a677992e36cdc9912e98a0b93ab9e33de38c067e161a17df62b08700` |
| 补丁后源文件 | `f812ffbe31dcdde2eeae1973b0192495bfc9b666cee349394a8230bf1a65f9d3` |
| `.patch`文件 | `93244d7afb47b90fddf4c48ffc13f7ba3df3a99aafd574390a1e9808eb368156` |

补丁在seek时使用已有缓冲生成固定256帧丢弃前缀，通过临时采样率比把SRC内部位置推进到准确源相位，再立即恢复真实比率。前缀包含sinc历史，不修改工程片段偏移；默认medium与best均纳入设计。具体算法、失败依据和待验收项见[ADR 0005](decisions/0005-daw-baseline-and-control.md#重采样源定位补充2026-10-27)。修改上游版本或SRC内核时必须重新审查该补丁，不能仅更新HEAD或重新计算哈希。

### 外部插件自动化回传补丁

此项差异作用于 `modules/tracktion_engine/plugins/external/tracktion_ExternalAutomatableParameter.h`，见[统一差异](../cmake/patches/tracktion/external-parameter-automation-echo.patch)。宿主写入自动化值后，原生参数 listener 可能回传相同当前值。补丁在该 listener 中忽略此类相同值回传，避免将自动化瞬时值误存为用户手动设置的基础值；实际参数变化仍进入正常更新。`valueChangedByPlugin()` 本身保持原行为，初始化和 program refresh 仍可同步基础值。

| 核验对象 | 标准化 LF SHA-256 |
|---|---|
| 上游源文件 | `4c2cbd1eb527da5ce5870a69e49b27f86ebb14ec35169d135b546ad904465b51` |
| 补丁后源文件 | `7636b9652a9e927dce3d5915941968a2c8a4c95bcaef721e357c16722f84d65d` |
| `.patch` 文件 | `fd2f5cd47516d2827b6cb9128255f62cdd494109057fa9e572c4841d0bb6fe0c` |

本机 Serum VST3 1.3.6.8 的[记录 20261026T185830.754109Z-ce021a9d95](builds/20261026T185830.754109Z-ce021a9d95.json)通过 20 项断言：2,397 个参数的两轮相同值通知不增加 revision/dirty，实际参数变化立即可见并标脏，强制自动化回传不覆盖基础值，保存重开保留基础值、自动化 lane 和稳定点 ID。此测试未打开原生编辑器、未开始播放，不能替代真实编辑器交互、播放或其他插件版本的兼容验证。

### 0.5.1 VST3闲置通道缓冲兼容候选

新增两项作用于固定JUCE子模块的juce_VST3Common.h和juce_VST3PluginFormat.cpp，见[存储补丁](../cmake/patches/tracktion/vst3-inactive-buffer-storage.patch)和[宿主补丁](../cmake/patches/tracktion/vst3-inactive-buffer-host.patch)。源/补丁/结果完整哈希均在同一manifest，四文件精确白名单由契约测试核验；CMake继续核验Tracktion与JUCE精确HEAD，不升级依赖。inactive通道预分配隔离缓冲、宿主传入最大块长、拒绝超长块；不改变bus激活和混音路由。VST3允许inactive实际样本地址为null，该变更属于兼容候选，不是宣称旧JUCE违反规格。详情与人工复测状态见[本轮记录](verification/2026-10-27-v051/RESULTS.md)。

### 项目构建规则与后续升级

2026-10-29，0.6.0新增五个录音/节拍器补丁：Edit.h增加四小节预备枚举并保留旧数值；Edit.cpp统一分母拍与四分音符坐标换算并支持低click音量；ClickNode按拍号分母调度点击和小节重音；TransportControl统一预备范围单位；MidiInputDevice处理录音边界持续音符和独立controller状态。源文件、补丁和结果哈希以[manifest](../cmake/patches/tracktion/manifest.json)为准。Bank、Program、RPN/NRPN及Data Entry等有顺序语义的操作不合成追赶；边界内的真实事件保留。具体契约见[ADR 0007](decisions/0007-daily-workflow-and-recording-clock.md)，结果见最新CONTEXT；没有升级Tracktion/JUCE版本。

0.3.0在项目`CMakeLists.txt`为Windows生成的`EMusician_resources.rc`补上`Info.txt`依赖。固定JUCE 8.0.6的生成规则遗漏该依赖，曾导致增量构建后程序内为0.3.0而Explorer属性仍为0.1.0。修正在本项目，不修改上游依赖；升级JUCE时检查是否仍需补充。

升级时先明确新的Tracktion/JUCE组合与VST2接口来源，在`dependencies.json`及对应bootstrap中更新精确提交/哈希并记录原因。重新下载核对后，通过日志入口完成Debug/Release和受影响的音频、设备、插件验证，再更新本文件和开发日志中的版本、许可文本差异及兼容结果。上游DemoRunner是可选构建目标，默认应用构建不会替项目执行全部上游示例或测试。

## 可选Kimi助手（2026-10-29）

产品使用Python标准库，验证解释器Python3.14.0（建议3.10+），无OpenAI/Moonshot SDK运行依赖。Kimi模型为官方接口实际返回的kimi-k2.6；网络模型不在本地锁定权重，官方参数依据见ADR0009。凭证使用Windows DPAPI系统API。

合成UI测试使用Codex bundled runtime 26.1020.11618中的Playwright1.62.1和本机headless Microsoft Edge156.0.4314.50；这些仅为测试工具，不是产品运行依赖。源码测试脚本通过PLAYWRIGHT_MODULE定位已有包，未自动下载依赖。真实DAW复用0.6.1已记录哈希的原生EXE。
