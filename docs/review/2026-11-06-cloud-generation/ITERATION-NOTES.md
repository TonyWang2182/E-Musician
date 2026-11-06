## 2026-11-06：0.12 云端生成接入启动记录更正

此前追加 DEVLOG 的中文经 Windows PowerShell 管道传入 Python 时被替换为问号；该历史条目按 append-only 约定保留，本条更正其内容。后续追加中文从 UTF-8 文件读取，不通过默认编码的命令管道传递。

用户授权按计划配置生成模型并接通手动/Agent。新分支 `feature/cloud-generation-v0120`，基线 `0219f9ad`，保留既有0.11程序、SSH规划记录及用户启动记录。云端核验 RTX5090、32607MiB、驱动580.76.05、250GB数据盘。批次计划及归属见 `docs/review/2026-11-06-cloud-generation/PLAN.md`。

首轮传输8项和既有Agent300项通过，属于模拟协议/既有回归；新增Agent后318项及三份侧栏网页夹具通过。首次原生构建失败于 `GenerationPanel` 的空 `juce::var` 赋值歧义和不存在的 `StringArray::getLast`；失败记录 `20261106T072254.905531Z-e3bb9f7129` 保留，修正后重建。此时真实云端推理、最终应用验收和ASIO听感尚未完成。
