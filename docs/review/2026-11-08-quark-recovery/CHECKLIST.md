# 夸克保存后：从备份到重新调用模型

当前状态：用户报告备份已在夸克；尚未读取夸克副本。2026-11-08本机旧SSH目录记录为failed，63块已校验、总接收约34.44GB，没有全量验证收据。它与夸克副本是两份独立状态。

## 现在完成：保全与验收

- [ ] **确认夸克任务完成。** 在“我的文件”中能找到私有目录 full-20261107T080330Z，上传队列无未完成/失败任务。目录名、文件数量或总容量本身不能替代校验。
- [ ] **下载到E盘独立验收目录。** 建议 `E:/MusicAgent&DAW/cloud-inference/backups/quark-full-20261107T080330Z`。不要与旧SSH下载目录同时混写。若下载的是外层ZIP，先在E盘解开外层ZIP，得到原始tarpart和清单；不要单独解压tarpart，也不要在Windows恢复Linux环境。保留ZIP和解出分块同时存在时，按约200GB可用空间预算；不是压缩比承诺。
- [ ] **核对实际文件结构。** 最终验收目录直接包含 part-000000.tarpart～part-000159.tarpart、receipt.json、manifest.jsonl、inventory.json、system.json、links.json；各part-*.json也保留。160块归档本体合计应为85,416,949,760字节（十进制85.42GB，约79.55GiB）；外层ZIP大小可以不同。若文件多套了一层同名目录，验收路径指向实际存放上述文件的内层。
- [ ] **执行本地离线全量校验。** 使用修正后的 scripts/cloud/pull_full_backup.py verify --destination <实际目录>。它流式检查分块/成员SHA、清单和链接，不需要租GPU，也不解包Linux运行环境。记录命令、日志、退出码和源码版本。通过条件：本次退出码0，新写入verification.json的phase=verified、parts=160、archive_bytes=85416949760、member_count=311031。restore_tested=false仍表示未做异机恢复。不能只看某个旧verification.json。
- [ ] **失败时只补具体缺失/损坏文件。** 保留原副本，按日志从夸克或原实例补取，不改清单来让校验通过。校验器的权限格式修复不代表整份备份已通过。
- [ ] **归档配套资料。** E盘完整校验后，将verification.json、校验脚本及其源码版本、RESTORE.md、本清单存进配套资料，并在夸克保留一份。核对AutoDL已有系统镜像状态为完成，记录名称、ID、日期；系统镜像不包含数据盘。现有私密SSH/API/HF配置单独保管，不放公开共享链接。该服务端包不包含完整本地DAW工程资产；本地工程、录音、DAW安装程序、Git代码和未提交修改另行保留。

现有“查看备份进度”窗口仍跟踪旧SSH目录，不能显示夸克客户端的下载进度。夸克下载看客户端；全量验收看本次校验记录。验收后才统一目录和入口，保留已经通过的文件，避免无意义重下。

下载完成后，在PowerShell运行下面命令（若多套一层目录，修改最后路径）：

```powershell
& 'C:\Python314\python.exe' 'E:\MusicAgent&DAW\worktrees\audio-analysis\scripts\cloud\pull_full_backup.py' verify --destination 'E:\MusicAgent&DAW\cloud-inference\backups\quark-full-20261107T080330Z'
$LASTEXITCODE
```

这会顺序读取整份归档，耗时取决于E盘读取与小文件清单处理速度，不会发起云端下载。使用2026-11-08修复后的脚本；其SHA256为`cbb01c0b7051d5dc291e546a21d0458cd2363d4245201f20701ce265c3960459`。若原本只有`receipt.remote.json`而没有`receipt.json`，先确认拿到的是原始云端导出目录；不要盲目重命名下载器缓存或修改清单。

## 下次需要模型时：恢复与接通

- [ ] **准备兼容实例和空间。** 优先采用已保存的系统镜像与此前验证过的Linux x86_64/NVIDIA组合；换GPU或驱动另验兼容性。若同盘保留原tarparts和恢复内容，建议按至少200～250GB可用空间规划；外层ZIP也保留时按约280～300GB规划。分别检查系统盘、数据盘与实际解包体积，不能把这些预算当保证。
- [ ] **夸克到新实例传输并再验。** 先把文件放恢复暂存目录，完成传输/外层解压与同等完整性校验。暂停待恢复目标的服务；不要覆盖正在运行的Python。
- [ ] **按原路径恢复。** tar成员带 `root/autodl-tmp/emusician/...` 和 `root/miniconda3/...` 前缀，需核对解包根与前缀映射，不能直接解到data根导致重复目录。保留软/硬链接和Linux权限，预建data根0700；如果系统镜像已有正确miniconda，不盲目覆盖它。系统盘需容纳运行时。
- [ ] **恢复数据库和运行配置。** 使用备份中的两个SQLite一致快照，避免混入旧镜像遗留WAL/SHM、PID和锁。检查数据库integrity_check、模型锁/SHA、九环境Python/import、ffmpeg及GPU可见性；必要的凭据在私密配置中恢复。
- [ ] **启动统一模型服务。** 确认protocol2、七模型能力列表及任务队列正常；检查服务重启后仍能启动。这里不包括自动租机/自动迁移等尚未实现能力。
- [ ] **七模型依次短测。** ACE-Step、YuE2各一次短生成；SCNet分离；TransKun与MuScriptor转MIDI；ChordMini和弦；SheetSage2综合分析。采用短素材、串行执行，保留输出/耗时/错误；真实音乐质量仍需试听和人工核查。
- [ ] **接回DAW和Agent。** 更新本机SSH地址/端口/密钥与 `E:/MusicAgent&DAW/cloud-inference/compute-registry.json`，确认Cloud可用。手动和Agent各做一次任务，检查候选预览→明确接受→Undo/Redo→保存重开；断云后已保存资产仍可播放。参考0.13人工验收清单。

## 收尾与长期复用

- [ ] 保留夸克副本＋E盘已校验副本。新模型/环境/服务变更另建带日期版本，不覆盖唯一已验证版本。
- [ ] 先完成独立备份核验，再按需要关机节省运行费；删除/释放旧实例最好等异机恢复与关键推理通过后单独决定。普通实例有连续关机15天释放规则，实际期限以控制台为准，关机不是永久保管。
- [ ] 更新模型清单、镜像信息、代码版本、连接配置和恢复演练记录。如果新实例有可用的夸克下载方式，可以直接传到云端；否则经E盘上传。目前未验证夸克直传链路，也没有自动直连恢复功能。E盘保留独立备份。

依据：[原恢复手册](../2026-11-07-full-cloud-backup/RESTORE.md)、[0.13人工验收](../2026-11-07-hybrid-pipeline/MANUAL-CHECK.md)、[AutoDL镜像](https://www.autodl.com/docs/image/)、[数据保留](https://www.autodl.com/docs/instance_data/)。
