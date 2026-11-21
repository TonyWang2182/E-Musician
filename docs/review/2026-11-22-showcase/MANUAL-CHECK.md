# 录制前人工验收

本轮有两个独立入口，原 0.13.6 EXE、工程关联和原创工程保持。自动测试不能替代声卡发声、听感及录屏音轨检查。

## 0.13.6 录音增强版

入口：`E:/MusicAgent&DAW/Start E-musician Recording.cmd`。

实际程序：`E:/emusician-analysis-build/bin-0.13.6-recording/Release/E-musician.exe`。已核对启动文件指向此路径且文件存在；不要误开原 `bin-0.13.6` 或三工程展示版来验收新增波形。本版保持线性录音，开始前关闭 Loop。

1. 先关闭其他 E-musician，打开测试副本。Settings 中选择当前声卡和有效的输入通道；音轨选择 In 1 或 In 2，只有目标轨开启 R。
2. 根据监听方式选择 Monitor；若声卡直通监听，避免再开启软件监听造成双声。Monitor Off 仍允许已 Arm 的轨道录音。
3. 点全局 Record，对麦克风说话或演奏 10 秒。波形应随录入持续向右增长，较响声音应有更大的真实波形。预备拍结束前不应出现伪造录音。
4. Stop 后，临时波形应平稳转成可编辑 clip；播放、Undo、Redo、保存并重开，检查音频和长度。
5. 分别试单声道、立体声、非零播放头起点。未 Arm 的其他轨不得产生录音；不因该显示功能改变 Monitor/录音路由。
6. 换另一块声卡时重新选择实际输入。若目标设备未连接，不把空的逻辑 In 1/2 当作可录输入。
7. 用短录屏确认录屏软件确实录到了 DAW 输出，再开始正式录制。此次不安装虚拟音频驱动。

尚需实体设备确认的边界：预备拍中 Stop 不留下 clip；连续录音 3–5 分钟时缩放/滚动仍能看到增长，输入静音时画面接近中心线而非随机波形；临时切到其他窗口再回来，继续显示当前录音；停止后无长时间空白或残留红框。请记录声卡型号、实际采样率/缓冲区、同时播放的轨道与插件数量，以及有无爆音/掉音。自动测试通过不代表这些硬件性能项目已验收。

## 三工程展示版

入口：`E:/MusicAgent&DAW/Start E-musician Workspace.cmd`。File → Projects 仅列出 New ideas、New Light、Tea for Two。

实际程序：`E:/emusician-analysis-build/bin-showcase-v1/Release/E-musician.exe`；已核对启动文件指向此独立路径且文件存在。

- 输入用 `E:/MusicAgent&DAW/demo-video/showcase-v1/scripts/agent-prompts.txt` 中的完整英文。工作区专门绑定这些指令及其原有素材；不是任意提示词模型测试入口。
- New ideas：90 BPM，先 YuE2 → Preview → Stop preview → Apply changes；再 ACE → Preview → Stop preview → Apply changes。手动删 YuE2 轨，选 ACE 音频片段。
- 分离：选 ACE clip，发送 Separate 指令。Apply 后保留源轨原名，手动 Mute 源轨，按顺序开各 stem 的 Solo。不要同时播放原曲与所有分轨。
- New Light：选择源 clip，发送 Chords 指令。结果出来后打开 Analysis，手动 Add chord track。再选源 clip，发送 Beat & Warp 指令，Apply 后试听；和弦轨随音频时间映射。
- Tea for Two：选择钢琴 stem，发送 MIDI 指令，Apply。手动添加钢琴乐器到新 MIDI 轨，Mute 原钢琴音频后播放，避免把原音频误认为 MIDI 乐器声音。
- 每次 Apply 后检查 Undo；手动修改会使旧方案过期时应重做指令，不能强行套用。
- 此版本不读取生产 API 密钥，不连接 SSH，也不执行模型推理；已有结果来源、校验和等待设置在包内 provenance/manifest 中保留。等待时长用于拍摄节奏，不是模型速度测量。

## 重置拍摄起点

先保存需要保留的工作并关闭展示版，然后在项目目录执行：

```powershell
python scripts/showcase_bundle.py --reset-projects
```

该命令只重置展示包内三个起始工程，不能用于原创 test drive；结果和源素材会按哈希核对。Demo 4 始终从原创工程副本录制。

## 4 分钟视频替换素材

- 双语分镜、每镜配音、英/中字幕、无字背景和片头片尾分别独立保存。
- 首版若使用静态产品截图做运镜，不把它算作录制操作成功证据。真人萨克斯演奏与实时录音画面由用户后续拍摄后替换，不能用抽象动效冒充。
- 成片中的试听音频应对应画面的真实候选或工程；保持章节内播放连续，裁切与放大只用于强调当前操作。
