"""Beat/warp proposals: explicit scope, one native commit and numeric readback."""
from __future__ import annotations
from copy import deepcopy
import math
from .analysis import _tool, identifier, number, authorize_result
from .selection import ScopeError, assert_scope_unchanged

_BPM={"type":"number","minimum":20,"maximum":300}
_SECONDS={"type":"number","minimum":0,"maximum":172800}
_IDS={"type":"array","minItems":1,"maxItems":32,"uniqueItems":True,"items":{"type":"string"}}
TEMPO_TOOLS=[
    _tool("read_audio_warp","读取已授权真实音频片段的Warp、原始源BPM、当前播放速度比和时间位置。关闭时默认120不是识别结果，不能猜源速度。",{"clip_ids":_IDS},["clip_ids"]),
    _tool("propose_audio_warp","单独提出一份音频Warp设置方案，确认后一次提交/撤销。开启必须指定已知原始源source_bpm；当前听到BPM除以warp_speed_ratio才是原始源BPM。target_bpm默认工程速度；follow_tempo=true跟随以后工程变速。first_beat_seconds为操作前当前片段相对秒，与工程绝对align_start_seconds必须同时提供。只支持固定比例保音高拉伸。",{
        "clip_ids":_IDS,"enabled":{"type":"boolean"},"source_bpm":_BPM,"target_bpm":_BPM,"follow_tempo":{"type":"boolean"},
        "first_beat_seconds":_SECONDS,"align_start_seconds":_SECONDS,"summary":{"type":"string","maxLength":500}},["clip_ids","enabled","summary"]),
    _tool("propose_beat_application","单独提出采用真实节拍候选的方案。audio_to_project=保留工程BPM、拉伸并对齐源片段；project_to_audio=整个工程采用音频BPM和3/4或4/4拍号、保留该音频速度，必须project范围。bpm可人工纠正或选择半倍/双倍；首拍默认候选first_downbeat，缺失则明确提供first_beat_seconds(分析范围相对秒)。target_start_seconds=首拍对齐到的工程绝对秒；省略时对齐到能保留前奏的下一个工程小节。不会创建音轨，需用户确认。",{
        "result_id":{"type":"string"},"mode":{"type":"string","enum":["audio_to_project","project_to_audio"]},"bpm":_BPM,
        "numerator":{"type":"integer","enum":[3,4]},"denominator":{"type":"integer","enum":[4]},
        "first_beat_seconds":_SECONDS,"target_start_seconds":_SECONDS,"follow_tempo":{"type":"boolean"},
        "summary":{"type":"string","maxLength":500}},["result_id","mode","summary"]),
]


def safe_tempo(raw):
    if not isinstance(raw,dict):raise ValueError("节拍候选摘要无效。")
    result={}
    for key,high in (("bpm",300),("first_beat_seconds",600),("first_downbeat_seconds",600)):
        value=raw.get(key)
        result[key]=None if value is None else number(value,20 if key=="bpm" else 0,high)
    n=raw.get("meter_numerator");d=raw.get("meter_denominator")
    if type(n) is not int or n not in (0,3,4) or type(d) is not int or d!=4:raise ValueError("节拍候选拍号无效。")
    if type(raw.get("meter_supported")) is not bool or raw["meter_supported"]!=(n in (3,4)) or type(raw.get("variable_tempo")) is not bool:
        raise ValueError("节拍候选状态无效。")
    values=raw.get("tempo_candidates",[])
    if not isinstance(values,list) or len(values)>3:raise ValueError("节拍速度候选超出预算。")
    result.update(meter_numerator=n,meter_denominator=d,meter_supported=raw["meter_supported"],variable_tempo=raw["variable_tempo"],
        tempo_candidates=[number(v,20,300) for v in values],confidence_kind="uncalibrated_beat_consistency")
    return result


def authorize_clips(context,frozen,clip_ids):
    assert_scope_unchanged(frozen,context)
    if not isinstance(clip_ids,list) or not 1<=len(clip_ids)<=32:raise ValueError("请选择1至32个音频片段。")
    ids=[identifier(cid) for cid in clip_ids]
    if len(set(ids))!=len(ids):raise ValueError("音频片段ID重复。")
    clips={c["id"]:(t,c) for t in context.get("tracks",[]) for c in t.get("clips",[])}
    selection=frozen.get("selection",{})
    selected={selection.get("active_clip_id")} if frozen["mode"]=="clip" else set(selection.get("clip_ids",[]))
    tracks=set(selection.get("track_ids",[]))
    if not tracks and selection.get("focus")=="track":tracks.add(selection.get("active_track_id"))
    for cid in ids:
        if cid not in clips or clips[cid][1].get("kind")!="audio":raise ScopeError("Warp只接受已经读取的真实音频片段。")
        owner,clip=clips[cid]
        if frozen["mode"]!="project":
            if selection.get("focus")=="piano_roll" or (cid not in selected and (selected or owner["id"] not in tracks)):
                raise ScopeError("音频片段不在本次允许范围内。")
            timed=selection.get("time_range",{})
            if frozen["mode"]!="clip" and timed.get("active") and not (timed["start_seconds"]<=clip["start_seconds"] and clip["start_seconds"]+clip["duration_seconds"]<=timed["end_seconds"]):
                raise ScopeError("Warp会改变整个片段；请使用整段范围或包含整段的时间选区。")
    return [deepcopy(clips[cid][1]) for cid in ids]


def safe_warp(raw,ids):
    if not isinstance(raw,dict) or not isinstance(raw.get("items"),list) or len(raw["items"])!=len(ids):raise ValueError("Warp回读数量无效。")
    items=[]
    for item in raw["items"]:
        if not isinstance(item,dict):raise ValueError("Warp对象无效。")
        value={"clip_id":identifier(item.get("clip_id"))}
        for key in ("enabled","follow_tempo"):
            if type(item.get(key)) is not bool:raise ValueError("Warp开关无效。")
            value[key]=item[key]
        if item.get("mode")!="preserve_pitch":raise ValueError("不支持这种Warp模式。")
        value["mode"]="preserve_pitch"
        for key in ("source_bpm","target_bpm"):value[key]=number(item.get(key),20,300)
        value["warp_speed_ratio"]=number(item.get("warp_speed_ratio"),1/15,15)
        for key in ("source_offset_seconds","playback_source_offset_seconds","timeline_start_seconds","duration_seconds","source_duration_seconds","playback_duration_seconds"):
            value[key]=number(item.get(key),0,172800)
        items.append(value)
    if len({item["clip_id"] for item in items})!=len(ids) or {i["clip_id"] for i in items}!=set(ids):raise ValueError("Warp回读身份不匹配。")
    return items


def _summary(args):
    text=args.get("summary")
    if not isinstance(text,str) or not text.strip() or len(text)>500:raise ValueError("请提供简短修改说明。")
    return text.strip()


def _plan(context,frozen,args,command,checks,changes,before,analysis=None):
    from .localization import L
    plan={"project_id":context["project_id"],"revision":context["revision"],"scope":deepcopy(frozen),"summary":_summary(args),
        "execution_kind":"beat_apply" if analysis else "audio_warp","commands":[command],"checks":[],"note_clip_ids":[],
        "warp_before":deepcopy(before),"warp_checks":checks,"changes":changes,
        "steps":[{"index":1,"label":L("检查片段与版本", "Check the clip and project revision")},{"index":2,"label":L("后台处理后一次提交并回读", "Prepare in the background, then apply once and verify")}]}
    if analysis:plan["analysis"]=deepcopy(analysis)
    return plan


def compile_warp(args,context,frozen,states):
    allowed={"clip_ids","enabled","source_bpm","target_bpm","follow_tempo","first_beat_seconds","align_start_seconds","summary"}
    if not isinstance(args,dict) or set(args)-allowed or type(args.get("enabled")) is not bool:raise ValueError("Warp方案参数无效。")
    clips=authorize_clips(context,frozen,args.get("clip_ids"));by_id={i["clip_id"]:i for i in states}
    if set(by_id)!={c["id"] for c in clips}:raise ValueError("需先完整读取Warp状态。")
    enabled=args["enabled"];native={"clip_ids":args["clip_ids"],"enabled":enabled,"mode":"preserve_pitch"}
    if enabled:
        native["source_bpm"]=number(args.get("source_bpm"),20,300)
        native["target_bpm"]=number(args.get("target_bpm",context["bpm"]),20,300)
        follow=args.get("follow_tempo",True)
        if type(follow) is not bool:raise ValueError("跟随速度必须是开关。")
        if follow and abs(native["target_bpm"]-context["bpm"])>1e-7:raise ValueError("跟随工程时目标速度必须等于当前工程速度。")
        native["follow_tempo"]=follow
    elif set(args)&{"source_bpm","target_bpm","follow_tempo"}:raise ValueError("关闭Warp时不要同时修改速度参数。")
    aligned="first_beat_seconds" in args or "align_start_seconds" in args
    if aligned:
        native["first_beat_seconds"]=number(args.get("first_beat_seconds"),0,min(c["duration_seconds"] for c in clips))
        native["align_start_seconds"]=number(args.get("align_start_seconds"),0,172800)
    expected=[]
    for clip in clips:
        previous=by_id[clip["id"]];ratio=native["target_bpm"]/native["source_bpm"] if enabled else 1.
        factor=previous["warp_speed_ratio"]/ratio;duration=clip["duration_seconds"]*factor
        start=native["align_start_seconds"]-native["first_beat_seconds"]*factor if aligned else clip["start_seconds"]
        number(start,0,172800);number(start+duration,0,172800)
        expected.append({"clip_id":clip["id"],"enabled":enabled,"follow_tempo":native.get("follow_tempo",False),"warp_speed_ratio":ratio,
            "timeline_start_seconds":start,"duration_seconds":duration,**({"source_bpm":native["source_bpm"],"target_bpm":native["target_bpm"]} if enabled else {})})
    from .localization import L
    changes=[L(f"修改 {len(clips)} 个音频片段的 Warp；一次确认、一次撤销。", f"Change Warp on {len(clips)} audio clips in one undoable edit."),
        L(f"源速度 {native['source_bpm']:g} → 目标 {native['target_bpm']:g} BPM；保留音高。", f"Source {native['source_bpm']:g} → target {native['target_bpm']:g} BPM, preserving pitch.") if enabled else L("关闭 Warp，恢复原始音频速度。", "Disable Warp and restore the original audio speed.")]
    if aligned:changes.append(L(f"当前片段内 {native['first_beat_seconds']:.3f} 秒对齐工程 {native['align_start_seconds']:.3f} 秒。", f"Align {native['first_beat_seconds']:.3f} s within the current clip to {native['align_start_seconds']:.3f} s in the project."))
    return _plan(context,frozen,args,{"command":"set_audio_warp","args":native},expected,changes,states)


def compile_beats(args,result,context,frozen,states):
    allowed={"result_id","mode","bpm","numerator","denominator","first_beat_seconds","target_start_seconds","follow_tempo","summary"}
    if not isinstance(args,dict) or set(args)-allowed or args.get("mode") not in ("audio_to_project","project_to_audio"):raise ValueError("节拍应用方案参数无效。")
    if result.get("kind")!="beats" or identifier(args.get("result_id"))!=result.get("result_id"):raise ValueError("需要真实节拍候选。")
    if result.get("stale") or result.get("applied"):raise ValueError("节拍候选已失效或已应用，请重新分析。")
    authorize_result(context,frozen,result)
    cid=result["source"]["clip_id"];clip=authorize_clips(context,frozen,[cid])[0]
    if len(states)!=1 or states[0]["clip_id"]!=cid:raise ValueError("需要读取源片段Warp状态。")
    state=states[0];tempo=result["tempo"];mode=args["mode"]
    if mode=="project_to_audio" and frozen["mode"]!="project":raise ScopeError("采用音频速度会改变整个工程；请明确切换到工程范围。")
    bpm=number(args.get("bpm",tempo.get("bpm")),20,300)
    n=args.get("numerator",tempo.get("meter_numerator"));d=args.get("denominator",4)
    known_meter=type(n) is int and n in (3,4) and type(d) is int and d==4
    if not known_meter and (mode=="project_to_audio" or "numerator" in args or "denominator" in args):raise ValueError("拍号不明确，请手动指定3/4或4/4。")
    first=number(args.get("first_beat_seconds",tempo.get("first_downbeat_seconds")),0,result["source"]["duration_seconds"])
    follow=args.get("follow_tempo",True)
    if type(follow) is not bool:raise ValueError("跟随速度必须是开关。")
    old_ratio=state["warp_speed_ratio"]
    source_bpm=number(bpm/old_ratio,20,300) if mode=="audio_to_project" else state["source_bpm"]
    ratio=context["bpm"]/source_bpm if mode=="audio_to_project" else old_ratio
    factor=old_ratio/ratio;clip_first=result["source"]["range_start_seconds"]+first
    bar_seconds=(n*60/bpm) if mode=="project_to_audio" else context["numerator"]*4/context["denominator"]*60/context["bpm"]
    default_target=math.ceil((clip["start_seconds"]+clip_first*factor)/bar_seconds-1e-9)*bar_seconds
    target=number(args.get("target_start_seconds",default_target),0,172800)
    native={"result_id":result["result_id"],"mode":mode,"bpm":bpm,
        "first_beat_seconds":first,"target_start_seconds":target,"follow_tempo":follow}
    if known_meter:native.update(numerator=n,denominator=d)
    start=target-clip_first*factor;duration=clip["duration_seconds"]*factor
    number(start,0,172800);number(start+duration,0,172800)
    expected={"clip_id":cid,"warp_speed_ratio":ratio,"timeline_start_seconds":start,"duration_seconds":duration,
        "follow_tempo":follow if mode=="audio_to_project" else False}
    if mode=="audio_to_project":expected.update(enabled=True,source_bpm=bpm/old_ratio,target_bpm=context["bpm"])
    from .localization import L
    changes=[L(f"候选速度 {bpm:g} BPM；首拍 {first:.3f} 秒（分析范围内）。", f"Candidate tempo: {bpm:g} BPM. First downbeat: {first:.3f} s within the analyzed range."),
        L(f"将首拍对齐工程 {target:.3f} 秒；不创建音轨。", f"Align the first downbeat to {target:.3f} s in the project. No track is created."),
        L("保持工程速度，只对源片段保音高拉伸。", "Keep project tempo and stretch only the source clip, preserving pitch.") if mode=="audio_to_project" else L("整个工程采用音频速度与拍号；源片段保持速度，其他跟随工程的音频也会更新。", "Adopt the audio tempo and meter for the whole project. The source keeps its speed; other tempo-following audio also updates.")]
    if tempo.get("variable_tempo"):changes.append(L("候选存在节奏波动；本次只应用固定比例，不会逐拍矫直。", "Tempo varies. This edit uses a fixed ratio and does not straighten individual beats."))
    plan=_plan(context,frozen,args,{"command":"apply_beat_analysis","args":native},[expected],changes,states,result)
    plan["tempo_check"]={"bpm":bpm,"numerator":n,"denominator":d} if mode=="project_to_audio" else {"bpm":context["bpm"]}
    return plan


def verify_tempo_plan(plan,after,states):
    errors=[];by_id={item["clip_id"]:item for item in states}
    for expected in plan["warp_checks"]:
        actual=by_id.get(expected["clip_id"],{})
        for key,value in expected.items():
            found=actual.get(key)
            valid=type(found) in (int,float) and abs(found-value)<.003 if type(value) in (int,float) else found==value
            if not valid:errors.append("Warp回读不匹配："+key)
    for key,value in plan.get("tempo_check",{}).items():
        if type(after.get(key)) not in (int,float) or abs(after[key]-value)>1e-6:errors.append("工程速度或拍号回读不匹配")
    return errors
