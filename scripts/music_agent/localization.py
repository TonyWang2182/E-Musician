"""Authored Agent copy, separate from user music data and model responses.

TranslatedText keeps the original Chinese value for existing internal contracts.
Only its explicitly authored English alternative is projected for an English UI.
No substring replacement is applied to names, prompts, lyrics or model content.
"""
from copy import deepcopy


class TranslatedText(str):
    def __new__(cls, chinese, english):
        value = super().__new__(cls, chinese)
        value.english = english
        return value

    def __getnewargs__(self):
        return str(self), self.english


L = TranslatedText


def english(value):
    return value.english if isinstance(value, TranslatedText) else value


def normalize_language(value):
    return "zh-CN" if value == "zh-CN" else "en"


COPY = {
    "正在规划": "Preparing a plan",
    "正在检查": "Checking",
    "已暂停；工程未修改": "Paused; project unchanged",
    "继续规划；正在检查工程和选择": "Resuming planning; checking the project and selection",
    "已回答；没有修改工程": "Answered; project unchanged",
    "生成音频已下载；试听并确认后加入新轨道": "Generated audio downloaded. Preview and confirm before adding a new track",
    "速度与对齐方案已准备；确认后才修改工程": "Tempo and alignment plan ready. Review before applying",
    "和弦修改方案已准备；尚未修改工程": "Chord edit plan ready; project unchanged",
    "候选已准备；确认后才导入工程": "Candidate ready. Review before importing",
    "方案已准备；尚未修改工程": "Plan ready; project unchanged",
    "没有提出修改方案，请明确目标和操作。": "No changes were proposed. Specify the target and the operation.",
    "任务异常，已停止后续动作。请检查本地日志或重新启动助手。": "The task stopped unexpectedly. Check the local log or restart the assistant.",
    "上一项任务仍在结束，请稍候。": "The previous task is still finishing. Please wait.",
    "请输入 1–6000 字的要求。": "Enter a request between 1 and 6000 characters.",
    "请选择当前选择、整个片段或整个工程范围。": "Choose Selection, Entire clip or Whole project scope.",
    "请先等待或取消当前任务。": "Wait for the current task or cancel it first.",
    "只能暂停规划；原子提交不能中途暂停。": "Only planning can be paused. An atomic edit cannot be paused midway.",
    "将在当前模型请求返回后暂停；没有应用修改。": "Will pause after the current model request returns. No changes have been applied.",
    "已取消；在途模型请求可能仍产生费用，没有应用方案。": "Cancelled. An in-flight model request may still incur charges. The plan was not applied.",
    "检查工程、选区与录音状态": "Checking the project, selection and recording state",
    "整份方案正在一次提交；此阶段不能暂停或取消": "Applying the whole plan in one edit. This step cannot be paused or cancelled",
    "正在核对本地音频并加入新轨道；不会重复提交": "Checking local audio and adding a new track. The import will not be submitted twice",
    "正在后台准备音频并提交；不会重复发送": "Preparing and applying audio in the background. The edit will not be submitted twice",
    "正在后台核对候选文件并导入；此阶段不能重复提交": "Checking candidate files and importing in the background. Please wait for this import",
    "采样器任务已受理，等待后台准备及实际提交": "Sampler task accepted. Waiting for background preparation and application",
    "修改已提交，正在回读；不应重复应用。": "Changes submitted. Reading back the result; do not apply again.",
    "核对最终对象、位置和音符": "Checking the resulting objects, positions and notes",
    "整份方案已应用并回读通过；一次撤销可还原本次修改。": "The whole plan was applied and verified. Undo once to restore the previous state.",
    "已请求取消；等待在途请求结束，不再应用修改。": "Cancellation requested. Waiting for the in-flight request to finish; no further edits will be applied.",
    "检查本次修改仍是最近一笔可撤销操作": "Checking that this edit is still the latest undoable action",
    "撤销本次整份方案": "Undoing the whole plan",
    "撤销已提交，正在回读；不会重复撤销。": "Undo submitted. Reading back the result; it will not be submitted twice.",
    "已撤销上次 Agent 批次。": "Undid the last Agent batch.",
    "撤销已提交；工程随后又有变化。": "Undo was submitted. The project changed afterward.",
    "请先结束录音或预备拍，再让助手编辑。": "Stop recording or count-in before asking the assistant to edit.",
    "工程上下文超过首版预算，请缩小目标范围。": "The project context exceeds the request limit. Select a smaller scope.",
    "所有值已符合要求，没有需要应用的修改。": "All values already match the request. No changes are needed.",
    "DAW 连接已断开，无法确认试听状态。": "DAW disconnected. Preview status cannot be confirmed.",
    "生成已结束，已停止后续操作；没有加入工程。": "Generation finished. Further actions stopped; nothing was added to the project.",
    "本地和云端生成已取消；没有加入工程。": "Local and cloud generation cancelled. Nothing was added to the project.",
    "已停止等待；云端正在取消，尚未确认停止。没有加入工程。": "Stopped waiting. Cloud cancellation is pending. Nothing was added to the project.",
    "已停止等待；无法确认云端生成已停止，可能仍占用算力。没有加入工程。": "Stopped waiting. Cloud cancellation is unconfirmed and may still use GPU time. Nothing was added to the project.",
    "仅接受本机地址。": "Only loopback connections are accepted.",
    "拒绝跨站请求。": "Cross-site requests are not allowed.",
    "会话已失效，请使用本次助手启动入口。": "This session is no longer valid. Reopen the assistant from its current launch entry.",
    "无法读取本地状态，请稍后重试。": "Unable to read the local state. Please retry shortly.",
    "不存在该入口。": "This endpoint does not exist.",
    "需要 JSON 请求。": "A JSON request is required.",
    "请求大小超限。": "The request exceeds the size limit.",
    "请求不完整。": "The request is incomplete.",
    "重复参数。": "Duplicate parameters are not allowed.",
    "无效数字。": "Invalid numeric value.",
    "请求必须为对象。": "The request must be an object.",
    "请用侧栏关闭按钮收起助手；DAW 由原生窗口管理。": "Use the sidebar close button to hide the assistant. Close the DAW from its own window.",
    "未知操作或参数。": "Unknown operation or parameter.",
    "本地服务异常，未继续操作。": "The local service failed. No further action was taken.",
    "当前没有可继续的暂停任务。": "There is no paused task to resume.",
    "模型一次提出过多工具请求，未执行修改。": "The model requested too many tools at once. No edits were applied.",
    "生成候选导入需单独提出一份方案。": "Propose the generated audio import as a separate plan.",
    "分析候选导入需单独提出一份方案。": "Propose the analysis import as a separate plan.",
    "模型需先完成读取，再单独提交一个方案。未执行修改。": "The model must finish reading before proposing one plan. No edits were applied.",
    "模型请求了未授权工具，已停止。": "The model requested an unavailable tool. The task was stopped.",
    "每次要求只运行一次音乐生成；重新生成请发送新要求。": "Only one generation runs per request. Send a new request to generate again.",
    "生成等待超过30分钟，已请求取消；请在 DAW 查看任务状态。": "Generation exceeded the 30-minute wait limit. Cancellation was requested; check the task in the DAW.",
    "分析等待超过 30 分钟，已请求取消；请在 DAW 查看任务详情。": "Analysis exceeded the 30-minute wait limit. Cancellation was requested; check the task in the DAW.",
    "方案已失效或已经提交，请重新生成。": "The plan is stale or has already been submitted. Create a new plan.",
    "提交已开始，不能中途取消；完成后可撤销。": "Submission has started and cannot be cancelled midway. Undo is available after completion.",
    "当前没有可撤销的 Agent 修改。": "There is no Agent edit available to undo.",
    "请等待任务结束后更改模型设置。": "Wait for the task to finish before changing model settings.",
    "请先等待当前任务结束。": "Wait for the current task to finish first.",
    "工程仍未保存。请先在 DAW 保存（或手动关闭该 DAW 窗口），再关闭助手。": "The project has unsaved changes. Save it in the DAW, or close the DAW window manually, before closing the assistant.",
    "DAW 连接结果未知。请在 DAW 保存并手动关闭窗口，再关闭助手。": "DAW connection state is unknown. Save and close the DAW window manually before closing the assistant.",
    "工程已变化，请重新生成方案。": "The project changed. Create a new plan.",
    "工程已变化，旧方案未应用。请重新提出要求。": "The project changed. The old plan was not applied; send the request again.",
    "音乐选择已变化，旧方案未应用。请重新生成方案。": "The music selection changed. The old plan was not applied; create a new plan.",
    "音乐选择已变化，旧方案不会改用新的选择。请重新生成方案。": "The music selection changed. The old plan will not target the new selection; create a new plan.",
    "当前选择不可用或超出 2000 音符范围；请缩小选择，或明确切换到工程范围。": "The selection is unavailable or exceeds 2000 notes. Select fewer notes or explicitly choose Whole project scope.",
    "请先在 DAW 选择一个片段，再使用整段范围。": "Select a clip in the DAW before using Entire clip scope.",
    "主轨效果器会影响整个工程；请切换到工程范围。": "Master effects affect the whole project. Choose Whole project scope.",
    "主轨效果器只能在工程范围读取和修改，请先切换范围。": "Choose Whole project scope to read or edit master effects.",
    "采样器和鼓组参数目前只能在整个工程范围使用单独方案；请切换到工程范围。": "Sampler and Drum Rack parameters require a separate plan in Whole project scope.",
    "此操作会影响整个工程；请明确切换到工程范围后再生成方案。": "This operation affects the whole project. Choose Whole project scope before creating a plan.",
    "整轨操作需要明确选择轨道；音符、片段或时间选区不能授权整轨修改。": "Select the whole track for a track-wide edit. A note, clip or time selection does not authorize it.",
    "新建片段需要已选轨道或该轨道上的时间范围。": "Select a track or a time range on that track before creating a clip.",
    "当前范围不允许此操作。": "This operation is outside the selected scope.",
    "DAW 连接已断开；请先保存并关闭受控窗口，再重新启动助手。": "DAW disconnected. Save and close the controlled window before restarting the assistant.",
    "DAW 未能及时返回。结果未知，已停止后续命令；请在 DAW 检查工程。": "The DAW did not respond in time. The outcome is unknown; further commands stopped. Check the project in the DAW.",
    "DAW 响应顺序不匹配，已停止后续命令。": "DAW responses arrived out of sequence. Further commands stopped.",
}


def authored(value, *, error=False):
    """Translate only a known authored value, never arbitrary user/model text."""
    if isinstance(value, TranslatedText):
        return value.english
    if not isinstance(value, str):
        return value
    if value in COPY:
        return COPY[value]
    if error and any('\u4e00' <= char <= '\u9fff' for char in value):
        # Unknown diagnostics remain intact in runtime state for troubleshooting.
        # Do not run a paid translation or rewrite an embedded project name.
        return "This request could not be completed. Review the selected objects and task settings."
    return value


def _typed(value):
    if isinstance(value, TranslatedText):
        return value.english
    if isinstance(value, dict):
        return {key: _typed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_typed(item) for item in value]
    return value


def public_response(value, language):
    if normalize_language(language) == 'zh-CN' or not isinstance(value, dict):
        return value
    result = _typed(deepcopy(value))
    if result.get('error'):
        result['error'] = authored(result['error'], error=True)
    if result.get('last_result'):
        result['last_result'] = authored(result['last_result'], error=True)
    if isinstance(result.get('progress'), dict):
        result['progress']['label'] = authored(result['progress'].get('label', ''), error=True)
    for message in result.get('messages', []):
        if message.get('origin') == 'runtime':
            message['content'] = authored(message['content'], error=True)
    preview = result.get('generation_preview')
    if isinstance(preview, dict) and preview.get('detail'):
        preview['detail'] = authored(preview['detail'], error=True)
    return result


def response_instruction(language):
    name = 'Simplified Chinese' if normalize_language(language) == 'zh-CN' else 'English'
    return (f"\nThe interface language for this request is {name}. Write all assistant replies, "
            f"plan summaries and explanations in {name}, including after tool results. "
            "The language of internal tool descriptions, previous messages and project data does not override this. "
            "If the user explicitly requests a different response language, honor that request. "
            "Preserve user-provided track names, filenames, music descriptions and lyrics in their original language; "
            "do not translate or rename project data just to match the interface.\n")
