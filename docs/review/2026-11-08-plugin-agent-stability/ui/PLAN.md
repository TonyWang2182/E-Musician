# 轨头紧凑按钮文字修复

2026-11-08；父任务负责0.13.2统一构建和记录。本子任务归属：WorkspaceLookAndFeel.h、PopupStyleSmoke.h、ArrangementView.cpp中的显示回归及本目录。无音频引擎、Agent、云端或工程命令变化。

根因：0.13.1共享主题的drawButtonText固定左右各10px内边距。ArrangementView的M/S/R为24×24按钮，deviceui::ControlLook继承该方法，实际文字区仅4px，JUCE绘制省略号。按钮名称和命令没有消失，显示回归来自布局。

修复：共享绘制按宽度给紧凑按钮缩小文字内边距；普通对话框按钮保留10px。M/S/R继续直显，不以tooltip代替；保持现有菜单、Options、确认框主题。

验收：真实字体栅格回归覆盖20/24/28px、M/S/R、关闭/开启/禁用状态、设备与全局主题，文字高度与三种字形须区别于省略号；生成原生控件对照图。Arrangement现有smoke检查实际轨头的文字渲染并保存近景。构建/CTest由父任务统一记录；屏幕实测与物理DPI另由用户确认。
