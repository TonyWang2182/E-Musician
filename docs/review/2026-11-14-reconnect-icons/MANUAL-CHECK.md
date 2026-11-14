# 0.13.3：你来做的人工检查

本轮只连接克隆主机并修复工程入口/按钮；没有重新运行音乐模型或实际声卡录音。模型和Agent操作清单见[CAPABILITIES](CAPABILITIES.md)。

## 打开位置

- 新版入口：`E:/MusicAgent&DAW/Start E-musician 0.13.3.cmd`。
- 实际程序：`E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe`。
- 本地开发工作区：`E:/MusicAgent&DAW/E-musician-0.13.3.code-workspace`。
- 云端VS Code窗口：标题含`emusician [SSH: emusician-autodl]`，目录`/root/autodl-tmp/emusician`。为保留现有本地工程和未保存编辑，打开独立远程窗口；本地工作区仍在E盘。
- 日后连接云端可双击`E:/MusicAgent&DAW/cloud-inference/Connect AutoDL Music.cmd`，别名已改为本次主机/端口。

## 先检查这两个改动

1. 在资源管理器打开你的测试工程目录，必要时按F5刷新。.emproj图标应为树乐师Logo；双击工程后窗口标题版本应为0.13.3，里面确实是所选工程。
2. 新建音频/MIDI轨或打开已有工程，轨头应明确显示M、S、R；分别点选再取消，核对静音、独奏、录音准备状态。再缩窄窗口、展开Agent与下栏，文字仍应可辨认。
3. 保留一个未保存小改动，再双击另一个测试工程：应出现保存确认；Cancel应留在当前工程。Save成功后才切换，Discard仅在你明确选择时放弃当前修改。测试使用副本。
4. 如果图标仍旧，先刷新文件夹或重新打开该文件夹，不删除系统图标缓存。若Windows仍使用其他已选默认应用，可在“打开方式”中选择本轮EXE；不要用旧的E:/E-musician/build/bin入口判断新版。

## 再测Agent与模型

1. 打开Agent，先选一条轨，Scope=Current selection，输入“把选中轨道音量降低2 dB，其他不变”。审阅→Apply changes→Undo this change，确认普通指令通路。
2. Whole project下分别请求ACE-Step和YuE2生成约12–20秒（分两次请求），用当前工程BPM/拍号。Preview有声后再接受，另存测试工程。
3. 选8–20秒音频，依次测试云端SCNet四轨、ChordMini和弦；钢琴片段测试TransKun，混合乐器测试MuScriptor；SheetSage2查看实际返回的音符/和弦/拍点/结构。先检查短段，再用长曲。
4. 本地路线分别是HTDemucs四轨、HTDemucs-6s六轨、Basic Pitch转MIDI、Chroma-HMM和弦、Beat This!节拍。Local与Cloud不是必然调用同一个模型。
5. 测试Wave/MP3播放、真实MIDI与人声录音由你完成；本轮连通检查不代替这些验收。

任务完成后先看候选，再明确接受；MIDI需给新轨挂乐器才有声音。遇到问题记录任务类型、选中片段、错误文案与大致时间即可，避免连续重复提交同一生成任务。
