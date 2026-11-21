# 交付与发布状态草稿

日期：2026-11-22。**这是本地交付/审查草稿，不是已发布声明。** 本子任务未执行 commit、push、tag、合并或修改工程文件关联。分支 `feature/showcase-recording-v1`，当前基线 `0c41caaee976aa5cf4018e6c83697c7cf282ae4b`；仓库 remote 为 `https://github.com/TonyWang2182/E-Musician.git`。最终提交与远端状态由主任务追加确认。

## 已核对的本地入口

| 入口 | 目标与用途 |
|---|---|
| `E:/MusicAgent&DAW/Start E-musician Workspace.cmd` | 直接启动 `E:/emusician-analysis-build/bin-showcase-v1/Release/E-musician.exe`，离线三工程拍摄版 |
| `E:/MusicAgent&DAW/Start E-musician Recording.cmd` | 直接启动 `E:/emusician-analysis-build/bin-0.13.6-recording/Release/E-musician.exe`，新增真实录音进行中波形 |
| `E:/MusicAgent&DAW/Start E-musician 0.13.6.cmd` | 原入口经 `dev_audio_input.py run` 启动保留的 `bin-0.13.6/Release/E-musician.exe --agent`；不等同于离线拍摄版 |

三份 EXE 的真实哈希见 [RESULTS.md](RESULTS.md)。原 0.13.6 哈希与基线一致，原入口内容未由本子任务更改；不把新的 Recording 输出当作原二进制。

拍摄版固定工作根：`E:/MusicAgent&DAW/demo-video/showcase-v1/workspace`。`CMakeLists.txt`、`dev_showcase.py`、`ReplayMode.h` 与最终 manifest 路径一致。`projects` 和 `templates` 恰好三项身份对应：

| 工程 | 工程 ID | 初始内容 |
|---|---|---|
| New ideas | `7d07b1348617538fa5831ea949efc4dd` | 90 BPM，空工程 |
| New Light | `46f41ede2e2a5726adac323517e5f574` | 120 BPM，24 秒音频源 |
| Tea for Two | `dc0c48d90fda5af0a7e48c07a8986cb4` | 120 BPM，16 秒钢琴源 |

模板不会在日常启动时自动覆盖用户已编辑的三个工程。捕获阶段工程位于包外层 `captures/projects`，不要把它们混入起始三工程入口。`workspace/runtime` 持有独立设置、插件 catalog、Agent 及任务状态。包内原始结果和输入有哈希，回放 candidate/工程 provenance 标记 `retained_result_replay` 与 `inference_performed=false`。

## 提交范围建议

提交本轮 C++/Python/网页源码、专用测试、决策、审查文档、脚本和 Recorder 摘要；按变更职责审核录音波形、隔离回放、捕获/媒体流水线。保留既有 DEVLOG append-only 历史与本轮之前的未跟踪构建摘要，不将它们当作本轮新增成果批量重写。发布前核对 `git diff --check` 和实际 staged 文件列表。

大媒体、用户原工程、插件状态、模型结果原文件及 runtime 缓存保留在 E 盘交付目录，不能仅因用于视频便自动上传公开仓库。公开源码可包含生成/验证脚本与非秘密哈希；不要提交密钥、SSH凭据、Agent 会话或个人路径下的私有配置。第三方录音/采样的发布范围需由素材使用者核对，本轮未取得新的素材传播许可。

## 构建与配置风险

当前共用 CMake 构建目录，构建录音/拍摄版之前必须先用 `scripts/dev_showcase.py recording configure` 或 `showcase configure` 明确 `EMUSICIAN_SHOWCASE=OFF/ON` 及独立输出目录，再构建。不要并行配置同一目录。

只读复核发现旧 `dev_audio_input.py configure` 未显式关闭拍摄模式，存在将来继承共用 cache 的风险。主任务已修复：其 configure 明确 `EMUSICIAN_SHOWCASE=OFF`，build 同时核对输出目录与 OFF；`dev_showcase.py` 的 build/test 同时核对目标模式与独立输出目录。已复核这些代码存在，语法/守卫检查由主任务记录；没有为此重新构建或覆盖原 0.13.6。其他历史构建脚本未作全面审查，今后切换版本仍需使用正确入口和明确模式，不能假定任意旧脚本都会重置共用 cache。

拍摄根/Python/源脚本路径是本机固定配置，Keyscape/BM 等依赖本机安装与授权。只发 EXE 不能复现完整工作流；给其他机器分发前还需路径可移植性、依赖与素材范围审查。录音版完整 CTest 首轮 10/11、修复后仅复测 engine 1/1；拍摄版普通 CTest 9/11 的两项模式冲突仍如实记录，不能写成完整 11/11。[RESULTS.md](RESULTS.md) 记录独立六场景 25 项通过及其局限。

## 待主任务填写的最终发布事实

- 最终源码提交 hash、准确 staged 范围及是否 push（未由本子任务执行）。
- GUI Preview/Apply 的捕获回执与最终影片路径、SHA-256、时长、分辨率、完整解码检查。
- 用户真实录音 take、真人 sax 视频和实际听感结果；当前抽象替换动画不替代这些证据。
- 最终交付清单与人工验收入口。不把固定回放、后期镜头或预置等待写成实时模型推理和性能测量。
