# 工程文件 Logo 与打开入口

2026-11-14，0.13.3 本轮子任务。范围：Windows `.emproj` 文件图标、默认打开入口，以及正常启动/单实例转交的工程打开路径。保留原始 Logo、旧程序和所有用户工程；不改变音频或模型管线。

## 已读到的原始状态

- `HKCU\Software\Classes\.emproj` 默认值为 `emproj_auto_file`。
- `HKCU\Software\Classes\emproj_auto_file\shell\open\command` 指向旧路径：`"E:\E-musician\build\bin\Release\E-musician.exe" "%1"`。
- 该旧 ProgID 没有 DefaultIcon。读取时 `.emproj` 的 Windows UserChoice 不存在。
- 当前 CMake 已以批准的 `assets/brand/yi-yue-shi-logo.png` 生成 EXE 图标；Main.cpp 的 Window 已调用 `setIcon(brand::logo())`，无需重绘或替换 Logo。
- 当前 Main.cpp 的普通启动和 `anotherInstanceStarted` 未处理工程文件名。旧文件关联既可能启动旧版本，也不能保证当前程序真正打开目标工程；只加 DefaultIcon 不足以完成用户要求。

## 实施与归属

1. `ProjectLaunch.h` 解析一个 `.emproj` 文件，支持显式 `--open-project` 和旧的单个位置参数；保留 `--agent`，拒绝缺失、多个文件和未知开关。
2. Main.cpp 在普通启动及单实例转交时走同一分派，延后到消息线程安全回调。
3. 新的 `MainComponent::openProjectFile` 复用已有 `withUnsavedGuard`、录音/进行中保存限制、统一 `open_project` 命令以及波形失效/快照反馈，不越过保存确认。
4. 注册脚本只写当前用户的专属 ProgID、`.emproj` 注册值与已确认属于 E-musician 的应用注册命令/图标；先保存逐值备份，保留其他文件类型、旧 ProgID、外来 handler 和受 Windows 保护的 UserChoice/UserChoiceLatest。没有删除图标缓存、重启 Explorer 或修改受保护默认应用标识/hash。
5. 父任务统一构建和记录测试，注册须等最终 EXE 存在；此子任务不自行运行构建、不申请 UI 自动操作。

## 验证计划

- Workspace smoke：路径解析、带空格/`&` 的引用、正常启动语义、读取专用合成项目、缺失文件不更改当前项目及源文件不重写。
- Python：内存注册表覆盖备份、恢复、冲突拒绝、保留 UserChoice/外来默认值、二进制值与部分写失败回滚；实际 Windows 后端只写 UUID 隔离测试目录，不向真正的 Classes/FileExts 注册测试类型。
- 最终注册后由父任务读取有效 shell command/icon 与 EXE 图标资源数量；实际 Explorer 缩略图、双击、打开已有未保存工程时 Save/Discard/Cancel 的鼠标操作由用户核查。

实施中发现：初查普通 UserChoice 缺失，但 Windows 新布局 UserChoiceLatest 指向 `Applications\E-musician.exe`，覆盖单独更新的扩展名默认 ProgID。已按上述有界应用注册方案修正并保留原受保护选择；实际通过记录和失败保留见 [RESULTS](RESULTS.md)。

## 官方依据

Windows 支持在当前用户的 Software\Classes 中注册文件类型，默认图标可以引用 EXE 内的图标资源。更新后通知 Shell 刷新关联，无需清空整个缓存。[文件类型注册](https://learn.microsoft.com/en-us/windows/win32/shell/fa-file-types)、[文件类型图标](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-assign-a-custom-icon-to-a-file-type)。有效关联通过系统查询接口读取，而非只检查自己刚写入的键值。[AssocQueryStringW](https://learn.microsoft.com/en-us/windows/win32/api/shlwapi/nf-shlwapi-assocquerystringw)。
