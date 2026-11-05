# 人工检查：钢琴卷帘与原生装置

关闭旧版，用 PowerShell 启动：

```powershell
& "C:\Users\28712\.codex\worktrees\music-agent-kimi\E-musician\build\monitor-isolation\bin\Release\E-musician.exe" --agent
```

1. 新建测试工程并新建 MIDI 轨和片段，双击片段；点钢琴卷帘标题处 `expand`，或按 Ctrl+Alt+E。确认编辑区放大；画一个音符，点 `return to arrangement` 再确认音符与原片段仍在。Ctrl+4 仍可切换该编辑器吸附。
2. 在 MIDI 轨 `devices` → 插件浏览器选择该轨 → `native...`。添加 `sampler`，`load sample...` 加载 `E:\E-musician\test-projects\test5-sampler&rack\07-piano-C4.wav`，等待 ready 和波形显示。拖波形上方左右手柄、松开后确认范围变化；尝试拖动中按 Esc 取消；写 C4/MIDI 60 并回放。
3. 另建 MIDI 轨，用同一入口添加 `drum rack / 16 pads`。确认 36 在左下、38 在底行第三格，分别载入 `01-kick.wav`、`02-snare.wav`；点击不同 pad 应显示对应样本和波形，写 MIDI 36、38 回放。pad 按钮本版选择样本，不是点击试听。
4. 选中其他 MIDI 轨并返回原轨，检查设备区不显示其他轨的旧样本。确认在设备列表里选原生装置点 open，或点右侧 inspector 的原生装置按钮，都能返回底部设备视图。
5. 使用 Save As 保存为新的测试工程，重新打开并等待样本 ready；确认波形、范围、音符及播放声音。旧版无法读取包含原生装置的新工程，不要覆盖旧工程。

若波形一直转圈或显示错误，请记录轨道、文件名和提示文字；这次没有测量你的鼠标、声卡、显示缩放或长期性能。慢盘、素材改变、故障盘和上轮待机问题的限制见 [RESULTS](RESULTS.md)。
