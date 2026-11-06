# SheetSage2 / MuScriptor 云端部署记录

状态：SheetSage2 / MERT2 文件、环境、CPU 加载及一次真实 GPU 推理已验证；MuScriptor 公共源码和环境已验证，权重访问受阻。范围仅云端模型库；未连接 DAW，未下载权重、音频或备份到 E 盘。这里只保存脚本、来源锁和小型日志。

## 来源与部署边界

- SheetSage2：`m-a-p/SheetSage2@b83c3d79a6d98bcffaf8f9ed112c90aa887887bc`，MERT2：`m-a-p/MERT-v2-FullSong@d8ba1c745e733b3908ce6ad16ebeb17ac7600a42`。42 个文件的字节数和散列已在云端核验。两份主权重分别为 228,738,564 和 2,529,812,848 字节。
- MuScriptor：公共源码 `muscriptor/muscriptor@8a1ef88672cc23c26619adaff37ec48d82c0b906`；medium 权重版本 `f32236969308476e01fd3aae67357de5feb05a2d`。一次匿名 HEAD 返回 401。没有接受模型条款、搜寻令牌或绕过访问限制，也没有下载 medium/large 权重。
- 路径统一位于 `/root/autodl-tmp/emusician`。独立环境为 `envs/sheetsage2` 和 `envs/muscriptor`；源码/缓存/工具位于各自 `workspace/models/<id>`；验收清单位于 `manifests/model-library/<id>`。
- 模型权重的 CC-BY-NC-4.0、MuScriptor 访问条款，以及转谱质量限制保留。MuScriptor 不预测真实力度，MIDI 默认力度为 100；鼓转录为起音事件。SheetSage2 的符号播放力度也不能当作演奏力度测量。

## 已完成

- SheetSage2 / MERT2 文件校验通过：Recorder `20261106T101423.945774Z-a7f71bada4`。
- MuScriptor 公共源码校验、隔离环境安装、`uv pip check`、公共模型类导入及 `muscriptor transcribe --help` 通过；CUDA 没有初始化。Recorder `20261106T102148.377615Z-0b00e4c08f`、`20261106T102204.079970Z-6da6792514`。这不是模型加载或推理通过；权重仍受阻。
- SheetSage2 默认文件解码需要 FFmpeg。已在专属目录部署 imageio-ffmpeg 0.6.0 发布的 FFmpeg 7.0.2 静态二进制，官方 PyPI wheel SHA256 `c7e46fcec401dd990405049d2e2f475e2b397779df2519b544b8aab515195282`；二进制 SHA256 `e7e7fb30477f717e6f55f9180a70386c62677ef8a4d4d1a5d948f4098aa3eb99`。仅包装命令增加私有 PATH，不改变系统 PATH 或 ACE。Recorder `20261106T103156.676054Z-ccfc6f0875`。paper preset 所需 torchaudio FFmpeg 共享库后端未验收。

## 失败、纠正及保留证据

1. 初次 uv Python 安装建立了 `/root/.local/bin/python3.11` 便利链接。检查其指向本任务目录后只移除了该新链接，保留隔离解释器；脚本改成 `--no-bin`。纠正记录 `20261106T101628.910088Z-faf5b2877d`。
2. 初次安装脚本运行中被更新，bash 读取偏移改变，MuScriptor 依赖同步后误把 lock 路径当命令执行，退出 126。原失败记录 `20261106T101529.671490Z-a16dcc434c`。随后使用新文件名的不可变恢复脚本，从原哈希锁完成安装；没有重新访问权重。之后所有远程脚本均以独立版本文件名上传，不修改运行中的文件。
3. SheetSage 初次 CUDA index 的 torch 2.8.0+cu128 cp311 wheel 完整下载过慢，安静 resolver 被明确停止，诊断重跑确认瓶颈为 848 MiB wheel 传输。记录 `20261106T101529.603942Z-6b62fb9c50`、`20261106T102418.112479Z-f010f914f8`；停止仅针对已核对 cmdline 的本任务 PID。后续 Range 下载也因慢速停止，`20261106T102640.883372Z-137af7d73c`。
4. 改用官方 PyPI 的精确 `torch==2.8.0` / `torchaudio==2.8.0` 经镜像安装，未替换为现有 2.10。这属于不同发布包，SHA 分别为 `c12fa219f51a933d5f80eeb3a7a5d0cbe9168c0a14bbb4055f1979431660879b` 和 `776c0b4ba84b9e3ddf6304b9c47cd63549d7896a6f3d5184ece074cc3d76ed6b`，没有冒充原 +cu128 包。官方 METADATA 确认 CUDA 12.8、NCCL 2.27.3、Triton 3.4.0。镜像生成哈希锁成功：`20261106T103034.026795Z-4fd73bb6d8`。
5. FFmpeg 官方 CDN 整包及 Range 传输过慢，前两次主动停止、一次 180 秒超时；记录 `20261106T102030.021065Z-2bb73da871`、`20261106T102336.327466Z-50208e36de`、`20261106T102817.181126Z-a0433cc8f6`。最终镜像取得相同官方 SHA 的 wheel 并校验成功。

## SheetSage2 最终验收

- 51 个独立依赖安装及 `uv pip check` 通过，Python 3.11.14、PyPI distribution 2.8.0（`torch.__version__` 为 2.8.0+cu128）、CUDA 12.8、Transformers 4.45.2；未修改 ACE 或全局 Python。记录 `20261106T103102.010953Z-e2c3524c03`。
- 真实 SheetSage2 + MERT2 CPU 权重加载、CPU 放置、默认 FFmpeg WAV 解码和上游 CLI help 通过，耗时 6.155 秒、CUDA 未初始化。记录 `20261106T103731.271726Z-6205e1a7cb`。首次 Transformers 缓存迁移显示离线警告，但实际加载成功；没有为消除警告启用网络。
- 另外确认不传 `base_model_path` 的上游默认加载路径也可从私有离线缓存找到固定 MERT2，并确认包装 CLI help；记录 `20261106T103841.400536Z-28311d7404`。
- 获得串行 GPU 时段后，用云端现有 ACE 音频前 8 秒做真实推理。保持原生 300 秒窗口填充、完整默认 prompts、BF16/SDPA，无 hidden-state 导出；10 GiB 分配上限，ACE 活动/低于 1 GiB 可用显存/180 秒截止看门狗。记录 `20261106T103752.455745Z-9f79c2fab3`。

| 本次探针指标 | 实际结果 |
| --- | --- |
| 机器 | 单 RTX 5090 32 GB；ACE 已驻留、无活动任务 |
| 输入 | 云端 8 秒、48 kHz、双声道 PCM WAV；模型内部转为 24 kHz 单声道 |
| 进程含模型加载耗时 | 4.524 秒；外层监测总计 6.825 秒 |
| PyTorch 峰值 allocated / reserved | 3,534,086,144 / 3,592,421,376 字节 |
| GPU 空闲显存 | 起止 14,774 MiB，监测最低 10,736 MiB |
| 输出 | ABC、MIDI、旋律/和弦/节拍/downbeat/key/structure LAB、事件与 token JSON |
| 结构检查 | 事件值有限、时间在 0–8.1 秒；MIDI 可解析、音高和力度在 0–127、时长不超过 8.5 秒；ABC 非空且无生成错误 |

这只是一次部署和结构正确性探针，不是任意歌曲准确率、爵士和弦能力、听感、长曲速度或最低显存保证。MIDI note-on 总数涉及多个重复表达的导出文件，不能当作唯一音符数量。默认窗口仍填充 300 秒，没有用缩短窗口来改变模型行为。未部署 PDF/图片谱面渲染与合成试听的额外资产和工具；paper preset 共享库解码后端仍未验证。

云端最终清单：`manifests/model-library/sheetsage2/deployment.json` 四项检查为 true，`muscriptor` 仅环境为 true，均 `daw_connected=false`。最终守护修正清单冻结时可用云盘 166,708,670,464 字节，超过 50 GB 保留线。相关小型清单、锁、CLI help、GPU 探针元数据在本目录 `evidence/`；实际权重、音频和推理输出只保留云端。所有失败原始日志及成功记录仍在忽略目录 `build-logs/`。

## 最后审查的守护程序修正

真实 GPU 探针使用的 `gpu_probe-v1.py` 原样保留。审查发现，清理子进程、最终状态查询或读取结果 JSON 抛错可能覆盖终态；初始准入失败也没有 receipt。最终 v3 将这些路径纳入记录，处理 `killpg` 与子进程退出的竞争，只清理本次 `Popen` 创建的子进程组，并明确关闭锁。后续探针输出改为 `results/model-library/sheetsage2/`，首次 `workspace/models/sheetsage2/probes/20261106T103753Z` 证据未移动。

最终守护程序 SHA256：`aeb829ca161770d7c478126ad9a01d95535b619645de6281aea3408aaeb9ec25`。7 项纯 CPU 故障注入检查通过（初始/最终诊断失败、准入拒绝、轮询异常、结果 JSON 损坏、清理失败、子进程退出竞争），Recorder `20261106T104412.119818Z-94b839b905`；没有再次推理。之前 5 项通过时暴露的锁资源警告保留于 `f826c27363`，最终运行没有该警告。`deployment.json.guard_evidence` 分别保存真实执行版本和最终修正版哈希，不能把 v3 当作已再次进行 GPU 验证。

独立只读复核：`cloud_ace` 核对 v3 清理/终态路径及上述 7 项原始故障日志，未发现新增阻断；主代理负责汇总架构、开发上下文和最终提交。
