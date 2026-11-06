# 云端命令行入口

仅在已登录实例的终端执行；本轮不新增 DAW 入口。不同时运行多个 GPU 模型，也不与 ACE 的生成任务重叠。现有测试输出已在云端，不需要重复运行来确认部署状态。

目录根为 `/root/autodl-tmp/emusician`。将下面 `<id>` 替换为 `scnet`、`transkun` 或 `chordmini`，输入需为数据盘内单/双声道音频，8–96 kHz、最长 120 秒；输出必须为 `results/` 内新的目录。**120 秒是工具上限，本次仅验证 8 秒。**

```bash
/root/autodl-tmp/emusician/envs/<id>/bin/python \
  /root/autodl-tmp/emusician/tools/models/mir_upgrades/infer.py <id> \
  --input /root/autodl-tmp/emusician/results/model-library/fixtures/ace-piano-trio-first8s.wav \
  --output /root/autodl-tmp/emusician/results/model-library/<id>/new-evaluation \
  --device cuda
```

SCNet 输出四个 WAV，TransKun 输出保留控制事件的 piano.mid，ChordMini 输出 chords.lab/chords.json；每次还有 result.json，记录模型/来源/输入 SHA、输出 SHA、时长与显存。现有目录不会覆盖，CUDA 失败不会偷偷改用 CPU。

上面是直接 CLI，必须先协调 GPU；受控短测试脚本 `guarded_probe.py <id>` 使用共享 `state/model-library-gpu-probe.lock`，只读检查 ACE 队列并监控显存，且只允许固定 8 秒输入/180 秒上限。它不具备生产队列或 DAW 请求路由；实际共享调度还未实施。

只检查环境/权重加载，不推理：

```bash
CUDA_VISIBLE_DEVICES= /root/autodl-tmp/emusician/envs/<id>/bin/python \
  /root/autodl-tmp/emusician/tools/models/mir_upgrades/runtime.py <id> --check
```

重建资料：固定源码及模型版本在 deployment.json；requirements.lock.txt 为哈希锁，environment-freeze.txt 为安装结果。锁中的 NVIDIA wheel 指向本实例已验证的 `cache/wheels`；新实例先按 SHA 恢复相同制品或取得原官方制品，不能直接改锁指向任意新版本。源码按提交和 Git blob 保留；不是完整训练仓库或环境镜像。用户本轮要求模型只留云端，未制作新离线备份。
