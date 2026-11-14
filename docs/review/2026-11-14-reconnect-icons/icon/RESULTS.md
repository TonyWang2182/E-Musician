# 工程文件图标：实现与验收边界

2026-11-14。当前子任务状态：最终 Release、原生 workspace 定向复测及 12 项注册检查通过；系统实际查询的 `.emproj` 打开命令、EXE 与图标均已指向 0.13.3。资源管理器显示与鼠标双击/未保存交接仍待用户人工验收，不从注册成功推断声音或界面使用已验收。

## 已实现

- `apps/desktop/ProjectLaunch.h` 与 Main.cpp：普通启动及单实例转交都接受 `--agent --open-project "绝对路径.emproj"`；旧的 `"路径.emproj"` 仍可用。文件通过消息线程 SafePointer 回调打开，工作进程/测试模式仍先走各自分派。
- `MainComponent::openProjectFile`：缺失/不适用文件先报错，实际切换复用现有未保存/录音保护与统一工程命令。不会默认丢弃当前改动。
- `scripts/register_project_file.py`：`status / apply / restore`；目标 ProgID 为 `E-musician.Project`，图标引用最终 EXE 的第 0 组资源，open 命令正确引用 EXE 与 `%1`。保留旧注册数据的备份；恢复发现用户后续更改时整体拒绝覆盖。
- 原 `.emproj` 入口指向 `E:/E-musician/build/bin/Release/E-musician.exe`；本次还发现 Windows 通过 UserChoiceLatest 选中了旧的 `Applications\E-musician.exe` 注册，最终已更新该应用自己的路径及图标。旧 EXE 本体保留；没有据此断言所有省略号问题只来自旧程序。
- 不改变 Logo 原字节、不新建图案，不改第三方插件图标。

## 父任务执行命令

工作目录 `E:/MusicAgent&DAW/worktrees/audio-analysis`，通过本轮构建记录器运行：

```powershell
C:/Python314/python.exe -X utf8 tests/ProjectFileAssociationTests.py
```

原生检查并入既有 `--workspace-smoke <全新绝对目录> --offline` 测试，由 CTest 统一运行。Python 最终 12 项全部通过（`8afb78256b`），其中真实注册表测试仅在 `HKCU\Software\E-musician\AssociationTests\<uuid>` 下往返，不注册真实文件类型。

最终 EXE 完成后，先读状态，再注册（备份路径须尚不存在）：

```powershell
C:/Python314/python.exe -X utf8 scripts/register_project_file.py status --exe E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe
C:/Python314/python.exe -X utf8 scripts/register_project_file.py apply --exe E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe --backup 'E:/MusicAgent&DAW/integration-backups/2026-11-14-emproj-application-association.json'
```

恢复本次关联的命令：

```powershell
C:/Python314/python.exe -X utf8 scripts/register_project_file.py restore --backup 'E:/MusicAgent&DAW/integration-backups/2026-11-14-emproj-application-association.json'
```

上述 apply 是已执行命令的记录；备份已存在，不应直接重跑。若需完全回到本轮前，先恢复上述第二份备份，再恢复同目录 `2026-11-14-emproj-association.json` 第一份备份；恢复会在出现后续用户修改时整体拒绝覆盖。脚本保留其他应用默认值、UserChoice 与 UserChoiceLatest，不修改其 hash；应同时检查注册写入结果与 `effective_executable`。初查只确认普通 UserChoice 不存在，后来读取发现 UserChoiceLatest，以下记录保留这次诊断过程。

## 人工检查

1. 资源管理器刷新工程目录，应显示树乐师 Logo；无需修改工程内容。
2. 关闭 DAW 后双击一个测试 `.emproj`，应显示 0.13.3，并打开相应工程而非空白新工程。
3. DAW 已开且当前工程无改动时，双击另一测试工程，应在同一应用窗口打开。
4. 当前工程有未保存改动时，再双击另一测试工程，应出现已有 Save/Discard/Cancel 流程；Cancel 保留原工程。

本子任务没有操作用户鼠标、打开用户工程或验证物理声卡。冷启动、单实例交接与未保存弹窗的实际桌面验收，由父任务实际证据及用户手动检查分别记录。

## 首轮真实注册表检查发现与修正

父任务先运行9项内存检查通过；随后新增第10项真实HKCU隔离目录检查，记录`673c79e3a1`失败。实际CPython `QueryValueEx` 将空REG_NONE读为None，而写入计划使用b''，导致往返断言及保守恢复比较不一致；并非真实文件类型关联写失败，本轮尚未执行正式注册。

已在WindowsRegistry.get中把空REG_NONE统一为b''，使序列化、比较和恢复使用同一语义。原生代码不变。失败残留仅为本次UUID隔离夹具，清理脚本`build/reconnect-icons/cleanup_association_fixture.py`锁定该准确路径及原计划允许的值，不递归删除、不碰真实Classes/FileExts；仍交由父任务记录执行。10项复验与清理结果待父任务回报，失败记录保留。

父任务回报：清理`0811b9cb27`已移除准确夹具，最终10项注册检查`7af994fa19`全部通过。

## 原生首轮与异步测试修正

Release构建`e3a71b29ba`成功；完整CTest `bbc82c6f3e`为10/11，workspace在新加入的“external file open reaches normal project command”断言失败。实际`open_project`走现有后台读取、消息线程提交的任务管线；新夹具在提交后立刻读取快照，错误地按同步打开判断。已把夹具改为10秒有界等待真实任务完成，记录任务status/error，再检查目标文件、内容、clean状态与源文件保持；没有改成绕过统一命令的同步调用，也没有删掉原断言。生产打开代码不变，修正后原生验证等待父任务执行。

最终结果：第二次 Release `7b242e79f9` 成功；`workspace.brand_colour` 定向复测 `277453f89c` 通过。两次构建之间仅 workspace 测试夹具增加有界异步等待，生产 C++ 代码没有改变；不把首轮完整 CTest 的失败抹成一次全绿记录。

## 系统有效关联与最终修正

首次正式注册 `f38443ec6f` 成功写入专属 ProgID 与扩展名，但有效命令/EXE/图标仍指向旧程序；独立查询 `724dc77c8a` 确认。进一步只读检查找到 `FileExts\.emproj\UserChoiceLatest\ProgId` 选择了 `Applications\E-musician.exe`，该应用注册的打开命令仍为旧路径。普通 UserChoice 为空并不等于系统没有受保护的默认应用选择。

修正仅补充 `HKCU\Software\Classes\Applications\E-musician.exe` 的 DefaultIcon 与 shell/open/command，且先核对原命令确为 E-musician 的旧/规范入口；外来程序命令保持。UserChoiceLatest 的标识与 hash 均不写入，前后摘要核对相同。新增两项测试覆盖这一实际 Windows 路径及外来 handler 保留，最终 12 项检查 `8afb78256b` 全通过。

第二次正式注册 `b074de8ef0` 成功，系统 `effective_command` 为带引号的 0.13.3 EXE + `--agent --open-project "%1"`，`effective_executable` 为 `E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe`，`effective_icon` 为该 EXE 的第 0 组图标，`user_choice_unchanged=true`。本次新备份保留第一轮已注册状态；第一轮备份仍保留最初状态。父任务另报告一次未引用带 `&` 路径的 PowerShell 解析错误，该次没有进入 Python、未修改注册表；随后正确引用的记录命令成功。

最终源码复核：启动参数处理只进入交互分支；worker/测试分派仍先处理。文件打开复用录音/保存/未保存保护、消息线程安全指针和统一命令。注册恢复仅逐值处理允许的键，删除限于本次创建的空键，不递归删除，不改受保护选择。未发现需再次更改原生代码的问题。

## 图标资源审查

最终 EXE 可枚举到两组图标。首次提取审查 `902c2277de` 因脚本错误要求返回数等于 1 而失败：同时提取大/小尺寸可能返回 2 个图标。已修正为正数及有效句柄并记录实际返回数；此审查不修改 EXE、注册表或用户工程。

修正后提取 `0b6717435a` 成功，第 0 组大图标为 32×32，返回数 2（大/小尺寸）。已用文件图像查看器对照 `build/reconnect-icons/exe-icon-index-0.png` 与批准的 `assets/brand/yi-yue-shi-logo.png`，确认同为树冠、眼镜、胡须与指挥棒的树乐师图案；未改动 Logo 原资源。此结果证明关联所引用的第 0 组确实是产品 Logo；实际 Explorer 刷新显示仍由用户人工确认。
