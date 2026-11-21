"""Six retained scenes through the real native candidate/review/apply pipeline.

No inference, SSH, credentials or external HTTP. Synthetic playback device;
physical listening and GUI capture remain separate. Run through Recorder.
"""
from __future__ import annotations
from copy import deepcopy
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
import traceback
import uuid
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "scripts"))
from agent_client import Client
from music_agent.bridge import DawBridge
from music_agent.runtime import AgentRuntime
from music_agent.replay_provider import ReplayProvider, install_loopback_guard
from showcase.package import Package, contained, sha256, read_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe",type=Path,required=True)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--timeout",type=float,default=180)
    args=parser.parse_args()
    package=Package(args.root)
    scenes={s["id"]:s for s in package.scenes}
    required={"yue","ace","separate","chords","beats","transcribe"}
    assert required <= set(scenes),"The six prepared scenes are required."
    capture=package.root.parent/"captures/projects"
    capture.mkdir(parents=True,exist_ok=True)
    directory=package.root.parent/"tests"/uuid.uuid4().hex
    directory.mkdir(parents=True)
    frozen=directory/"E-musician.exe"
    shutil.copy2(args.exe,frozen)
    report={"passed":False,"mode":"retained_result_replay_real_native_pipeline",
        "external_llm":False,"inference_performed":False,"physical_audio":False,
        "exe_sha256":sha256(frozen),"manifest_sha256":sha256(package.root/"manifest.json"),
        "checks":[],"stages":{},"previews":[],"limits":["No new model accuracy or inference-speed claim.","Output probe is not physical-device or listening acceptance."]}
    protected={str(file):sha256(file) for file in (package.root/"projects").rglob("*") if file.is_file()}
    client=runtime=bridge=None
    stage="startup"

    def wait(phase="done"):
        runtime.worker.join(args.timeout)
        assert not runtime.busy(),"Agent task timeout."
        assert runtime.phase==phase,f"Agent {runtime.phase}: {str(runtime.error)[:500]}"

    def request(command,**values):
        return client.request({"command":command,"args":values})

    def select(cid):
        before=bridge.snapshot()["revision"]
        selected=request("showcase_select_clip",clip_id=cid)["result"]
        assert selected["active_clip_id"]==cid,f"Native selection was not published for {cid}: {selected}"
        assert bridge.snapshot()["revision"]==before,"Selecting a clip changed project revision."

    def open_start(project_id):
        project=package.projects[project_id]
        original=contained(package.root,project["path"])
        target=directory/original.name
        shutil.copy2(original,target)
        source_assets=original.with_suffix(".assets")
        if source_assets.is_dir():shutil.copytree(source_assets,target.with_suffix(".assets"),dirs_exist_ok=True)
        request("open_project",path=str(target))
        snapshot=bridge.snapshot()
        assert snapshot["project_id"]==project_id
        return snapshot

    def musical(snapshot):
        def stable(value):
            if isinstance(value,float):return round(value,9)
            if isinstance(value,list):return [stable(item) for item in value]
            if isinstance(value,dict):return {key:stable(item) for key,item in value.items()}
            return value
        notes={}
        for track in snapshot["tracks"]:
            assert not track.get("clips_truncated"),"The prepared scene exceeded snapshot limits."
            for clip in track["clips"]:
                if clip["kind"]=="midi":
                    page=client.completed(client.raw({"command":"get_clip_notes","args":{"clip_id":clip["id"],"offset":0,"limit":1000}}))
                    assert page["total"]==len(page["notes"]),"The prepared MIDI scene exceeded the complete-note page."
                    notes[clip["id"]]=page["notes"]
        return stable({"project_id":snapshot["project_id"],"bpm":snapshot["bpm"],"numerator":snapshot["numerator"],"denominator":snapshot["denominator"],
            "tracks":[{k:deepcopy(t[k]) for k in ("id","name","kind","muted","solo","gain_db","pan","clips","plugins","colour","sends","automation") if k in t} for t in snapshot["tracks"]],
            "notes":notes,"chord_regions":chords()["items"]})

    def save_stage(label):
        before=musical(bridge.snapshot())
        path=capture/(label+".emproj")
        request("save_project",path=str(path))
        request("open_project",path=str(path))
        after=musical(bridge.snapshot())
        assert before==after,"Save/reopen changed musical content for "+label
        report["stages"][label]=str(path)
        report["checks"].append(label+": real save/reopen preserved musical state")
        return path

    def plan(scene_id,phase="ready",scope="project"):
        scene=scenes[scene_id]
        before=bridge.snapshot()["revision"]
        runtime.plan_request(scene["prompts"][0],scope=scope,language="en")
        wait(phase)
        assert bridge.snapshot()["revision"]==before,"Planning mutated the project."
        assert runtime.usage["calls"]==0,"Replay unexpectedly recorded language API calls."
        report["checks"].append(scene_id+": exact instruction resolved to a native verified candidate without a project edit")
        return deepcopy(runtime.plan)

    def apply_and_undo_redo():
        before=musical(bridge.snapshot())
        approved=deepcopy(runtime.plan)
        runtime.apply(approved["id"]);wait()
        after=musical(bridge.snapshot())
        assert after!=before and runtime.undo_target
        try:runtime.apply(approved["id"])
        except ValueError:pass
        else:raise AssertionError("An already applied plan was submitted again.")
        runtime.undo();wait()
        assert musical(bridge.snapshot())==before,"One Undo did not restore the previous music state."
        request("redo")
        assert musical(bridge.snapshot())==after,"Redo did not restore the imported music."
        report["checks"].append(stage+": Apply, single Undo, native Redo and duplicate-plan rejection passed")
        return approved,after

    def preview_generation():
        rev=bridge.snapshot()["revision"]
        runtime.preview_generation_plan(runtime.plan["id"])
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            preview=runtime.state()["generation_preview"]
            if preview["status"] not in {"preparing","loading"}:break
            time.sleep(.1)
        assert preview["status"] in {"playing","completed","unavailable"},preview
        report["previews"].append({"scene":stage,"status":preview["status"],"physical_audio":False})
        runtime.preview_generation_plan(stop=True)
        assert bridge.snapshot()["revision"]==rev

    def chords():
        items=[];total=None
        while total is None or len(items)<total:
            page=client.completed(client.raw({"command":"get_chord_regions","args":{"offset":len(items),"limit":100}}))
            assert total is None or total==page["total"],"Chord count changed during readback."
            total=page["total"]
            assert page["items"] or len(items)==total,"Chord pagination made no progress."
            items.extend(page["items"])
        assert len(items)==total
        return {"total":total,"items":items}

    install_loopback_guard()
    try:
        # Production preferences must remain unreachable even by accident.
        with patch("music_agent.runtime.load_config",side_effect=AssertionError("production configuration accessed")), \
             patch("music_agent.runtime.has_key",side_effect=AssertionError("production credentials accessed")), \
             patch("music_agent.runtime.create_provider",side_effect=AssertionError("network provider constructed")):
            client=Client(frozen,timeout=args.timeout,show=False,offline_test=True)
            bridge=DawBridge(client=client)
            runtime=AgentRuntime(bridge,ReplayProvider(package.root))
            assert bridge.generation_capabilities()["available"]
            assert "showcase_select_clip" in bridge.capabilities()["commands"]
            open_start(scenes["yue"]["project_id"])
            assert not bridge.snapshot()["tracks"]
            save_stage("D1-00-New-ideas")
            stage="yue";plan("yue");preview_generation();apply_and_undo_redo()
            yue_track=bridge.snapshot()["tracks"][0]["id"]
            yue_clip=bridge.snapshot()["tracks"][0]["clips"][0]["id"]
            save_stage("D1-01-YuE2")
            stage="ace";plan("ace");preview_generation();apply_and_undo_redo()
            tracks=bridge.snapshot()["tracks"]
            assert len(tracks)==2
            ace_track=next(t for t in tracks if t["id"]!=yue_track)
            save_stage("D1-02-Both-takes")
            # Wrong real audio cannot become a reviewable/applicable candidate.
            stage="wrong-source-refusal"
            select(yue_clip)
            before=musical(bridge.snapshot())
            before_jobs=set(runtime.analysis_jobs)
            runtime.plan_request(scenes["separate"]["prompts"][0],scope="clip",language="en")
            runtime.worker.join(args.timeout)
            refusal={"phase":runtime.phase,"error":str(runtime.error),"messages":runtime.state(False)["messages"][-2:],
                "jobs":[job for key,job in runtime.analysis_jobs.items() if key not in before_jobs]}
            report["wrong_source_refusal"]=refusal
            assert not runtime.busy(),"Wrong-source refusal timed out."
            assert runtime.phase=="error" and runtime.error,f"Wrong source was not explicitly rejected: {refusal}"
            assert runtime.plan is None,"Wrong source produced an applicable plan."
            assert all(job.get("status") not in {"ready","applied"} for job in refusal["jobs"]),"Wrong source produced a usable native candidate."
            assert musical(bridge.snapshot())==before,"Wrong-source attempt edited the project."
            report["checks"].append("SCNet replay explicitly refuses the actual YuE2 source; no candidate, stems or edits are fabricated")
            request("remove_track",track_id=yue_track)
            assert len(bridge.snapshot()["tracks"])==1
            save_stage("D1-03-ACE-chosen")
            select(ace_track["clips"][0]["id"])
            stage="separate";plan("separate",scope="clip")
            name=bridge.snapshot()["tracks"][0]["name"]
            _,after=apply_and_undo_redo()
            assert len(after["tracks"])==5 and next(t for t in after["tracks"] if t["id"]==ace_track["id"])["name"]==name
            assert {c.get("analysis_role") for t in after["tracks"] if t["id"]!=ace_track["id"] for c in t["clips"]}=={"vocals","drums","bass","other"}
            save_stage("D1-04-Four-stems")

            stage="chords"
            new_light=open_start(scenes["chords"]["project_id"])
            source=new_light["tracks"][0]["clips"][0]
            save_stage("D2-00-New-Light")
            select(source["id"])
            plan("chords",phase="done",scope="clip")
            assert runtime.plan is None and chords()["total"]==0
            ready=next(j for j in reversed(list(runtime.analysis_jobs.values())) if j.get("status")=="ready")
            rid=ready.get("result_id") or ready["job_id"]
            expected=bridge.analysis_result(rid)["total"]
            assert expected>0
            request("accept_analysis_result",result_id=rid)  # Same command used by Analysis panel's Add chord track.
            assert chords()["total"]==expected
            request("undo");assert chords()["total"]==0
            request("redo");assert chords()["total"]==expected
            report["checks"].append("Chord candidate stays unapplied until the Analysis-panel native accept command; Undo/Redo restore all regions")
            save_stage("D2-01-Chords")

            stage="beats"
            select(source["id"])
            before_chords=chords()["items"]
            assert len(before_chords)==expected and before_chords,"Chord regions were lost before Warp."
            before_clip=next(c for t in bridge.snapshot()["tracks"] for c in t["clips"] if c["id"]==source["id"])
            plan("beats",scope="clip");apply_and_undo_redo()
            after_clip=next(c for t in bridge.snapshot()["tracks"] for c in t["clips"] if c["id"]==source["id"])
            assert after_clip["warp_enabled"] and after_clip["warp_follow_tempo"]
            after_chords=chords()["items"]
            assert len(after_chords)==len(before_chords)
            factor=before_clip.get("warp_speed_ratio",1)/after_clip["warp_speed_ratio"]
            by_id={r["id"]:r for r in after_chords}
            for region in before_chords:
                changed=by_id[region["id"]]
                assert changed["label"]==region["label"]
                for field in ("start_seconds","end_seconds"):
                    mapped=after_clip["start_seconds"]+(region[field]-before_clip["start_seconds"])*factor
                    assert abs(changed[field]-mapped)<1e-6,"Chord timing did not follow the real Warp operation."
            report["checks"].append("Pitch-preserving Warp is executed by the native engine; chord labels stay intact and times follow its exact mapping")
            save_stage("D2-02-Warp")

            stage="transcribe"
            tea=open_start(scenes["transcribe"]["project_id"])
            save_stage("D3-00-Tea-for-Two")
            select(tea["tracks"][0]["clips"][0]["id"])
            plan("transcribe",scope="clip")
            count=runtime.plan["analysis"]["summary"]["note_count"]
            _,after=apply_and_undo_redo()
            assert count==132 and sum(c.get("note_count",0) for t in after["tracks"] for c in t["clips"] if c["kind"]=="midi")==count
            path=save_stage("D3-01-Piano-MIDI")
            persisted=read_json(path)
            assert persisted["analyses"]
            retained=read_json(contained(package.root,scenes["transcribe"]["result_path"]))
            saved_notes=[n for t in persisted["tracks"] for c in t["clips"] if c["kind"]=="midi" for n in c["notes"]]
            expected_notes=[n for t in retained["midi_tracks"] for n in t["notes"]]
            note_key=lambda n:(n["start_seconds"],n["pitch"],n["channel"],n["velocity"],n["duration_seconds"])
            actual_notes=[{"pitch":n["pitch"],"channel":n["channel"],"velocity":n["velocity"],
                "start_seconds":n["start_beats"]*60/persisted["bpm"],"duration_seconds":n["length_beats"]*60/persisted["bpm"]} for n in saved_notes]
            # Rounding both sides separately is not a tolerance: equivalent
            # seconds->beats->seconds values can straddle a half-microsecond.
            max_timing_error=0.0
            for index,(actual,expected_note) in enumerate(zip(sorted(actual_notes,key=note_key),sorted(expected_notes,key=note_key))):
                assert all(actual[field]==expected_note[field] for field in ("pitch","channel","velocity")),f"Transcribed MIDI identity/value mismatch at note {index}: {actual} != {expected_note}"
                timing_error=max(abs(actual[field]-expected_note[field]) for field in ("start_seconds","duration_seconds"))
                max_timing_error=max(max_timing_error,timing_error)
                assert timing_error<=1e-6,f"Transcribed MIDI timing error at note {index}: {timing_error} seconds"
            report["transcription_max_timing_error_seconds"]=max_timing_error
            report["checks"].append("All 132 retained TransKun pitches/times/velocities/channels reach editable MIDI and survive Apply/Undo/Redo/save/reopen; full chord regions are likewise preserved")
            assert runtime.usage["calls"]==0
            report["passed"]=True
    except Exception as error:
        report["failure"]={"stage":stage,"type":type(error).__name__,"detail":str(error)[:1200]}
        report["failure"]["traceback"]=traceback.format_exc(limit=6)
        if runtime:
            report["failure"].update(agent_phase=runtime.phase,agent_error=str(runtime.error)[:700])
            report["failure"]["last_messages"]=runtime.state(False)["messages"][-2:]
        print(json.dumps(report["failure"],ensure_ascii=False),flush=True)
    finally:
        if client:client.close()
        changed=[path for path,hash_value in protected.items() if not Path(path).exists() or sha256(path)!=hash_value]
        report["starting_projects_unchanged"]=not changed
        if changed:report["passed"]=False;report["changed_starting_files"]=changed
        (directory/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"passed":report["passed"],"checks":len(report["checks"]),"report":str(directory/"report.json")}),flush=True)
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
