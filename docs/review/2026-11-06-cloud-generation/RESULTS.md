# 0.12 云端生成接入结果

2026-11-06。**真实模型、原生DAW和Agent整链通过；完整E盘备份进行中，人工试听待验。** 本批仅ACE文字/歌词到音频，保留0.11；YuE2、远程MIR替换、参考音频/续写/生成式补轨不属于已实现内容。

## 已交付的行为

顶部 `add... → Generate music` 打开生成下栏；填写描述、可选歌词、10–120秒目标时长和seed。没有源片段也能生成，进度来自后台任务。先显示可试听候选，再由用户明确加入一条音频轨；支持一次Undo/Redo。Agent使用同一组命令，先提交生成、等待真实结果，再提出导入确认，不能用口头回复冒充已生成。

生成请求通过SSH连接已租实例的loopback网关，单GPU队列、模型驻留，重复请求幂等。取消区分本地停止与云端确认；云端推理可能要等安全检查点。网络/模型/下载校验不进入实时音频回调。

结果在E盘校验SHA和真实WAV后发布；接受时复核工程/速度/拍号及候选哈希。生成音频随工程存入本地 `.assets`，含来源的工程使用schema7；云端离线后仍能重开和渲染。未接受候选的文件保留，但列表不跨DAW重启恢复。没有增加工程自动保存。

## 运行入口与固定版本

- 新程序：`E:/MusicAgent&DAW/Start E-musician 0.12.0 Generate.cmd`。
- VS Code：`E:/MusicAgent&DAW/E-musician-Generate.code-workspace`，构建/测试通过 `scripts/dev_generation.py` 留日志。
- EXE：`E:/emusician-analysis-build/bin-0.12.0/Release/E-musician.exe`，SHA256 `017ced8ef2309da0bc2d4228466369cab4b35b5b41e6df55ad270cd9601b3641`。
- 旧0.11 EXE SHA `a69f82ecaf144a7021aa1313ad23de681b407f39c93b99b06b1069d6b0503807`，复核保持不变。
- 253个源输入 SHA `ebdfea33db3961af998df283ab6599d56e5736315039901561ff63def288c789`；与最终325项Agent回归完全一致，所有原生输入与最后应用构建逐文件一致。精确清单见 [VERIFICATION.json](VERIFICATION.json)。
- JUCE8.0.6 / Tracktion3.2.0；ACE固定源码commit `ca1e85fe9430179831e6bc6be790c332190a3866`，完整权重锁见 [CLOUD-MODEL-LOCK.json](CLOUD-MODEL-LOCK.json)。

## 实测证据

| 验证 | 实际结果 |
|---|---|
| 原生构建/回归 | 首次编译失败已修正；完整CTest11/11通过，后续仅GenerationPanel修正后再通过workspace与engine.integration_smoke。最后构建 `074838…7579521bbc`，两次相关复测 `074946…8ebf87af06` / `075404…639d5a4b99`。 |
| 原生生成契约 | 合成PCM夹具37项，覆盖候选/校验/接受/撤销/保存等，不当作真实推理。 |
| Agent | 最终325/325，记录 `080413.231293Z-8f2678c9da`，运行期间整个源码指纹未变；实际侧栏三份双语/尺寸夹具通过。 |
| Windows传输 | 11/11：哈希/大小/路径/格式/静音/取消/幂等/磁盘失败/Unicode来源边界。 |
| 网关控制 | fake worker隔离回归9/9；实际120秒任务幂等与冲突、下载SHA、运行及排队取消另外通过。 |
| 原生＋真实ACE | 12秒候选到达17.31s；确认导入、重复接受不增轨、一次Undo/Redo、schema7保存、新进程禁用云端后重开/非静音渲染均通过。四组结果见 [NATIVE-END-TO-END.json](NATIVE-END-TO-END.json)。 |
| Agent＋真实ACE | 确定性语言Provider的12秒候选审阅6.47s；七组真实操作通过。 |
| GPT-5-mini＋真实ACE | 两次语言模型调用，12秒候选审阅40.64s；七组通过。输入17922／输出2590 tokens；用户工程、设置与密钥文件未改。见 [Agent结果](AGENT-RESULTS.md)。 |
| 备份校验器 | 14项通过，旧小备份的整包与逐文件SHA实际通过；大模型备份待本轮完成后单独登记。 |

原生/Agent自动宿主为隔离的离线设备，**不等于硬件试听通过**。试听如实返回无音频输出，导入确认仍可用。主代理及子代理已查看组件PNG和网页截图；没有使用computer-use操作用户桌面。

云端机器为RTX5090/32607MiB、90GiB内存限制、16vCPU；Torch2.10.0+cu128，BF16/SDPA、batch1、8步、无量化/offload。12秒纯音乐冷加载加生成34.87s，人声热生成2.22s；120秒单例冷启动网关全程42.63s，推理13.84s，推理阶段峰值allocated15.38GiB。两分钟单例没有OOM，不推断任意歌曲或并发负载表现。方法与完整记录见 [CLOUD-RESULTS.md](CLOUD-RESULTS.md)。

## 数据与备份

云端模型位于 `/root/autodl-tmp/emusician/models/ace/checkpoints`，32文件合计25,253,694,578字节；size/SHA完整验证，依赖锁、freeze、硬件和推理记录保留。环境在独立 `envs/ace`，原base未替换。

本地候选在 `E:/MusicAgent&DAW/cloud-inference/jobs`；已接受且尚未保存的音频在 `assets`；探针样本在 `results`，实验工程和报告在 `experiments`，源码/环境档案在 `manifests`。完整云端数据备份目标 `backups/20261106T080515Z-7fa9b891`，记录 `20261106T080514.137904Z-97ce676029`，当前仍在打包/下载，尚不声明完整E盘归档通过。

备份在所有真实任务终态后开始；先对SQLite做online backup，再归档模型、代码、任务及清单。envs/cache不进数据包，依靠固定锁重建。整包和逐文件SHA通过也不等于换实例部署已验证；跨实例恢复仍待另一次演练。

## 审查、失败和剩余验收

[REVIEW.md](REVIEW.md) 与各层结果记录保留编译失败、网络下载中断、安装脚本末行错误、默认20不可见、试听异步错误丢失、中文来源长度误判、真实Agent试听缺少工程版本信封等问题及修正。DEVLOG保持append-only；原始日志在忽略的build-logs和E盘cloud-inference/logs，摘要在docs/builds。

按 [MANUAL-CHECK.md](MANUAL-CHECK.md) 做真实鼠标/中文输入/试听/ASIO播放共存验收。BPM/拍号/目标时长是生成条件，不能保证音乐严格对齐；需要时使用现有节拍/Warp功能。云端实例仍保持开机，任务取消或关闭DAW不会替代实例关机。
