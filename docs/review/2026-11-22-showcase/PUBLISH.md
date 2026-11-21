# 交付与发布状态

日期：2026-11-22。**源码已提交并推送到功能分支，未合并 main。** 实现提交 `80e795e738b2631289e532a83e2a65203f9085eb`，分支 `feature/showcase-recording-v1`，基线 `0c41caaee976aa5cf4018e6c83697c7cf282ae4b`；仓库 remote 为 `https://github.com/TonyWang2182/E-Musician.git`。实际 push 退出码 0，建立了远端跟踪分支。此页后续只记录交付事实，不改变已验证的原生构建。交付包 `RELEASE.json` 记录最后文档提交及远端核对；没有创建 tag、GitHub Release 或修改工程文件关联。

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

## 实际提交范围

实现提交包含本轮 C++/Python/网页源码、专用测试、决策、审查文档、脚本和 Recorder 摘要，共 149 个文件。已核对 staged 列表、`git diff --cached --check` 与新文件密钥格式扫描。DEVLOG 从原 HEAD 历史后仅追加本轮内容；既有 DEVLOG 修改及 36 个旧未跟踪构建摘要保持在工作树，未纳入本轮提交。审计清单保存在忽略目录 `build-logs/showcase-owned-stage.json`。

大媒体、用户原工程、插件状态、模型结果原文件及 runtime 缓存保留在 E 盘交付目录，不能仅因用于视频便自动上传公开仓库。公开源码可包含生成/验证脚本与非秘密哈希；不要提交密钥、SSH凭据、Agent 会话或个人路径下的私有配置。第三方录音/采样的发布范围需由素材使用者核对，本轮未取得新的素材传播许可。

## 构建与配置风险

当前共用 CMake 构建目录，构建录音/拍摄版之前必须先用 `scripts/dev_showcase.py recording configure` 或 `showcase configure` 明确 `EMUSICIAN_SHOWCASE=OFF/ON` 及独立输出目录，再构建。不要并行配置同一目录。

只读复核发现旧 `dev_audio_input.py configure` 未显式关闭拍摄模式，存在将来继承共用 cache 的风险。主任务已修复：其 configure 明确 `EMUSICIAN_SHOWCASE=OFF`，build 同时核对输出目录与 OFF；`dev_showcase.py` 的 build/test 同时核对目标模式与独立输出目录。已复核这些代码存在，语法/守卫检查由主任务记录；没有为此重新构建或覆盖原 0.13.6。其他历史构建脚本未作全面审查，今后切换版本仍需使用正确入口和明确模式，不能假定任意旧脚本都会重置共用 cache。

拍摄根/Python/源脚本路径是本机固定配置，Keyscape/BM 等依赖本机安装与授权。只发 EXE 不能复现完整工作流；给其他机器分发前还需路径可移植性、依赖与素材范围审查。录音版完整 CTest 首轮 10/11、修复后仅复测 engine 1/1；拍摄版普通 CTest 9/11 的两项模式冲突仍如实记录，不能写成完整 11/11。[RESULTS.md](RESULTS.md) 记录独立六场景 25 项通过及其局限。

## 最终交付事实

- 实现提交 `80e795e` 已推送；只读复核和后续发布文档不触发原生重编译。
- GUI Preview/Apply 回执见 [GUI.md](GUI.md)。两版影片均 240 秒、1080p30、7200 帧，完整解码、同画面码流、试听非静音及无满幅削波检查通过；路径和精确 SHA-256 见 [DELIVERY.md](DELIVERY.md)。
- C01/W03 按每帧实际采集时间和宿主读数恢复画面时间，音乐保持原速；最终抽帧中点误差约 40 / 60 毫秒，不声明采样级同步。原始帧、读数和时间映射保留在交付包。
- 用户真实录音 take、真人 sax 视频和整片听感仍待用户验收。03:01–03:10 的抽象替换画面不替代这些证据。
- [人工验收入口](MANUAL-CHECK.md)。固定回放、后期镜头或预置等待不作为实时模型推理和性能测量。大媒体与用户原音频未上传 GitHub。
