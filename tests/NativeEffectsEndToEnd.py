"""Native EQ/compressor control and rendered audio integration; disposable files only."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from agent_client import Client, ControlError
from NativeDeviceEndToEnd import make_fixture, rms_window


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--exe", type=Path, required=True); ap.add_argument("--timeout", type=float, default=90)
    args = ap.parse_args()
    directory = ROOT / "build" / "native-effects-e2e" / str(uuid.uuid4()); directory.mkdir(parents=True)
    fixture = directory / "tone.wav"; make_fixture(fixture)
    result = {"passed": False, "checks": []}
    client = None
    native_tracks = set()
    def wait_reopened_samples():
        # open_project completes the project load, but native PCM preparation
        # remains asynchronous. Wait for every owned instrument, including muted
        # tracks, before requesting an export. Do not retry a failed write.
        deadline = time.monotonic() + args.timeout
        remaining = set(native_tracks)
        while remaining and time.monotonic() < deadline:
            for track_id in tuple(remaining):
                info = client.completed(client.raw({"command": "get_native_instrument", "args": {"track_id": track_id}}))
                if info.get("load_status") == "error":
                    raise AssertionError("Reopened native sample failed: " + str(info.get("error")))
                if info.get("load_status") == "ready":
                    remaining.remove(track_id)
            if remaining:
                time.sleep(.03)
        if remaining:
            raise AssertionError("Reopened native samples did not become ready: " + repr(sorted(remaining)))
    def write(name, arguments=None):
        response = client.request({"command": name, "args": arguments or {}}, wait=True).get("result", {})
        if name == "add_native_instrument":
            native_tracks.add(arguments["track_id"])
        if name == "open_project":
            wait_reopened_samples()
        return response
    def read(track, device): return client.completed(client.raw({"command":"get_native_effect", "args":{"track_id":track,"device_id":device}}))["state"]
    def render(name):
        path = directory / name
        write("export_wav", {"path":str(path),"start_seconds":0.0,"end_seconds":0.13,"tail_seconds":0.0,"sample_rate":48000,"bit_depth":24,"realtime":False})
        return rms_window(path,.04,.06)
    try:
        client = Client(args.exe, timeout=args.timeout, show=False, offline_test=True)
        write("import_audio", {"paths":[str(fixture)]})
        track = client.state()["tracks"][0]["id"]
        baseline=render("flat.wav")
        added=write("add_native_effect", {"track_id":track,"type":"eq8"}); eq=added["device_id"]
        state=read(track,eq); assert len(state["bands"])==8
        state["bands"][4].update(frequency=440, gain_db=12, q=1)
        write("set_native_effect", {"track_id":track,"device_id":eq,"state":state})
        boosted=render("boost.wav"); assert boosted>baseline*3.0,(baseline,boosted)
        write("undo"); assert abs(read(track,eq)["bands"][4]["gain_db"])<1e-5
        assert abs(render("undo.wav")-baseline)<.003
        write("redo"); assert abs(read(track,eq)["bands"][4]["gain_db"]-12)<1e-5
        assert render("redo.wav")>baseline*3
        result["checks"].append("EQ changes actual audio; Undo/Redo restores state and rendering")
        # New filter modes must alter real audio at zero gain and survive archive.
        original_eq=read(track,eq); highpass=copy.deepcopy(original_eq)
        highpass["bands"][4].update(shape="high_pass",frequency=3000,gain_db=0,q=.7071)
        write("set_native_effect",{"track_id":track,"device_id":eq,"state":highpass})
        cut=render("highpass.wav");assert cut<baseline*.05,(cut,baseline)
        shape_project=directory/"filter-shapes.emproj"
        write("save_project",{"path":str(shape_project)});write("open_project",{"path":str(shape_project)})
        assert read(track,eq)["version"]==2 and read(track,eq)["bands"][4]["shape"]=="high_pass" and render("highpass-reopen.wav")<baseline*.05
        for badshape in ("unknown",1):
            bad=copy.deepcopy(highpass);bad["bands"][4]["shape"]=badshape;version=client.state()["revision"]
            try:write("set_native_effect",{"track_id":track,"device_id":eq,"state":bad})
            except ControlError:pass
            else:raise AssertionError("invalid filter shape accepted")
            assert client.state()["revision"]==version
        write("set_native_effect",{"track_id":track,"device_id":eq,"state":original_eq})
        write("undo");assert read(track,eq)["bands"][4]["shape"]=="high_pass"
        write("redo");assert render("shape-redo.wav")>baseline*3
        result["checks"].append("new EQ shapes change real audio, persist, undo/redo and reject invalid state")
        # Alias is typed and supports adding then editing in one atomic candidate.
        compressor_state={"version":1,"type":"compressor","threshold_db":-30,"ratio":10,"attack_ms":.1,"release_ms":100,"makeup_db":0}
        batch=write("batch", {"commands":[
            {"command":"add_native_effect","args":{"track_id":track,"type":"compressor"},"as":"comp"},
            {"command":"set_native_effect","args":{"track_id":track,"device_id":"@comp","state":compressor_state}}]})
        comp=batch["refs"]["comp"]
        assert read(track,comp)["ratio"]==10 and read(track,comp)["dry_wet"]==1
        compressed=render("compressed.wav"); assert compressed<boosted*.7,(boosted,compressed)
        result["checks"].append("batch alias controls compressor and renders reduced signal")
        # Legacy states lack dry_wet. They decode as fully wet; new writes
        # preserve the mix across Undo, Redo and later save/reopen.
        dry_state=read(track,comp);dry_state["dry_wet"]=0
        write("set_native_effect",{"track_id":track,"device_id":comp,"state":dry_state})
        dry=render("dry.wav");assert abs(dry-boosted)<.003,(dry,boosted)
        half_state=copy.deepcopy(dry_state);half_state["dry_wet"]=.5
        write("set_native_effect",{"track_id":track,"device_id":comp,"state":half_state})
        half=render("half.wav");assert compressed<half<dry,(compressed,half,dry)
        write("undo");assert read(track,comp)["dry_wet"]==0
        write("redo");assert read(track,comp)["dry_wet"]==.5
        half_restored=directory/"mix.emproj";write("save_project",{"path":str(half_restored)});write("open_project",{"path":str(half_restored)})
        assert read(track,comp)["dry_wet"]==.5 and abs(render("half-reopened.wav")-half)<.003
        write("set_native_effect",{"track_id":track,"device_id":comp,"state":compressor_state})
        assert read(track,comp)["dry_wet"]==1
        result["checks"].append("legacy default and real dry/wet render, Undo/Redo, save and reopen")
        before=client.state()["revision"]; bad=copy.deepcopy(compressor_state);bad["ratio"]=0
        try:write("set_native_effect", {"track_id":track,"device_id":comp,"state":bad})
        except ControlError:pass
        else:raise AssertionError("invalid state accepted")
        assert client.state()["revision"]==before and read(track,comp)["ratio"]==10
        result["checks"].append("invalid parameter rejected without project mutation")
        master=write("add_native_effect", {"track_id":"master","type":"eq8"})["device_id"]
        assert read("master",master)["type"]=="eq8"
        project=directory/"effects.emproj";write("save_project", {"path":str(project)});write("open_project", {"path":str(project)})
        assert read(track,eq)["bands"][4]["gain_db"]==12 and read(track,comp)["ratio"]==10 and read("master",master)["type"]=="eq8"
        restored=render("restored.wav");assert abs(restored-compressed)<.003,(restored,compressed)
        result["checks"].append("track and master device states survive save/reopen and render consistently")
        # A sampler and effects share one MIDI track; selection must never treat
        # an effect as an instrument and sampler edits must target the sampler.
        write("set_track_muted", {"track_id":track,"muted":True})
        write("create_track", {"kind":"instrument","name":"Sampler coexistence"})
        sampler_track=next(t["id"] for t in client.state()["tracks"] if t["name"]=="Sampler coexistence")
        write("add_native_instrument", {"track_id":sampler_track,"type":"sampler"})
        write("set_native_sample", {"track_id":sampler_track,"pad":0,"path":str(fixture)})
        effect_id=write("add_native_effect", {"track_id":sampler_track,"type":"eq8"})["device_id"]
        def sampler():
            return client.completed(client.raw({"command":"get_native_instrument","args":{"track_id":sampler_track}}))
        assert sampler()["type"]=="sampler" and sampler()["pads"][0]["asset_id"]
        write("set_native_pad", {"track_id":sampler_track,"pad":0,"gain_db":-6,"muted":False})
        assert abs(sampler()["pads"][0]["gain_db"]+6)<.001
        write("create_midi_clip", {"track_id":sampler_track,"start_beats":0,"length_beats":1})
        clip=next(t for t in client.state()["tracks"] if t["id"]==sampler_track)["clips"][0]["id"]
        write("write_notes", {"clip_id":clip,"notes":[{"pitch":60,"start_beats":0,"length_beats":.2,"velocity":100,"channel":1}]})
        heard=render("sampler-eq.wav");assert heard>.001
        coexist=directory/"coexist.emproj";write("save_project", {"path":str(coexist)});write("open_project", {"path":str(coexist)})
        info=sampler()
        assert info["type"]=="sampler" and abs(info["pads"][0]["gain_db"]+6)<.001 and read(sampler_track,effect_id)["type"]=="eq8"
        again=render("sampler-eq-reopened.wav");assert abs(again-heard)<.003,(heard,again)
        result["checks"].append("sampler and EQ coexist, sampler parameters target correct device, save/reopen and render")
        write("set_track_muted", {"track_id":sampler_track,"muted":True})
        write("create_track", {"kind":"instrument","name":"Rack coexistence"})
        rack_track=next(t["id"] for t in client.state()["tracks"] if t["name"]=="Rack coexistence")
        write("add_native_instrument", {"track_id":rack_track,"type":"drum_rack"})
        write("set_native_sample", {"track_id":rack_track,"pad":0,"path":str(fixture)})
        rack_eq=write("add_native_effect", {"track_id":rack_track,"type":"eq8"})["device_id"]
        def rack():return client.completed(client.raw({"command":"get_native_instrument","args":{"track_id":rack_track}}))
        assert rack()["type"]=="drum_rack" and rack()["pads"][0]["asset_id"]
        write("set_native_pad", {"track_id":rack_track,"pad":0,"gain_db":-6,"muted":False})
        assert abs(rack()["pads"][0]["gain_db"]+6)<.001
        write("create_midi_clip", {"track_id":rack_track,"start_beats":0,"length_beats":1})
        clip=next(t for t in client.state()["tracks"] if t["id"]==rack_track)["clips"][0]["id"]
        write("write_notes", {"clip_id":clip,"notes":[{"pitch":36,"start_beats":0,"length_beats":.2,"velocity":100,"channel":1}]})
        rack_audio=render("rack-eq.wav");assert rack_audio>.001
        rack_project=directory/"rack-coexist.emproj";write("save_project", {"path":str(rack_project)});write("open_project", {"path":str(rack_project)})
        info=rack()
        assert info["type"]=="drum_rack" and abs(info["pads"][0]["gain_db"]+6)<.001 and read(rack_track,rack_eq)["type"]=="eq8"
        rack_again=render("rack-eq-reopened.wav");assert abs(rack_again-rack_audio)<.003,(rack_audio,rack_again)
        result["checks"].append("rack and EQ coexist, rack parameters target correct device, save/reopen and render")
        # One isolated audio track proves the repeated signal and bypass, not
        # just state round-trips. The 140 ms source has finished at 150 ms.
        write("set_track_muted",{"track_id":rack_track,"muted":True})
        write("import_audio",{"paths":[str(fixture)]})
        delay_track=client.state()["tracks"][-1]["id"]
        delay_id=write("add_native_effect",{"track_id":delay_track,"type":"delay"})["device_id"]
        delay_state={"version":1,"type":"delay","delay_ms":100,"feedback":.5,"dry_wet":1}
        write("set_native_effect",{"track_id":delay_track,"device_id":delay_id,"state":delay_state})
        def delay_render(name):
            path=directory/name
            write("export_wav",{"path":str(path),"start_seconds":0,"end_seconds":.35,"tail_seconds":0,"sample_rate":48000,"bit_depth":24,"realtime":False})
            return rms_window(path,.16,.04),rms_window(path,.27,.04)
        echo=delay_render("delay.wav");assert echo[0]>.01 and echo[1]>.005,echo
        write("set_plugin_enabled",{"track_id":delay_track,"plugin_id":delay_id,"enabled":False})
        bypass=delay_render("delay-bypass.wav");assert max(bypass)<1e-5,bypass
        write("undo");assert delay_render("delay-undo.wav")[0]>.01
        delay_project=directory/"delay.emproj";write("save_project",{"path":str(delay_project)});write("open_project",{"path":str(delay_project)})
        assert abs(read(delay_track,delay_id)["delay_ms"]-100)<.001 and delay_render("delay-reopen.wav")[0]>.01
        result["checks"].append("delay creates repeated audio; bypass, Undo and reopen preserve real behavior")
        # Verify a real decaying tail beyond the 140 ms source, not merely the
        # reverb state. This also exercises Tracktion's no-input tail rendering.
        write("set_track_muted",{"track_id":delay_track,"muted":True})
        write("import_audio",{"paths":[str(fixture)]})
        reverb_track=client.state()["tracks"][-1]["id"]
        reverb_id=write("add_native_effect",{"track_id":reverb_track,"type":"reverb"})["device_id"]
        reverb_state={"version":1,"type":"reverb","decay_seconds":2.0,"damping":.2,"dry_wet":1.0}
        write("set_native_effect",{"track_id":reverb_track,"device_id":reverb_id,"state":reverb_state})
        def reverb_render(name):
            path=directory/name
            write("export_wav",{"path":str(path),"start_seconds":0,"end_seconds":.8,"tail_seconds":0,"sample_rate":48000,"bit_depth":24,"realtime":False})
            return rms_window(path,.25,.1)
        reverb_tail=reverb_render("reverb.wav");assert reverb_tail>.0001,reverb_tail
        write("set_plugin_enabled",{"track_id":reverb_track,"plugin_id":reverb_id,"enabled":False})
        assert reverb_render("reverb-bypass.wav")<1e-5
        write("undo");assert reverb_render("reverb-undo.wav")>.0001
        reverb_project=directory/"reverb.emproj";write("save_project",{"path":str(reverb_project)});write("open_project",{"path":str(reverb_project)})
        assert abs(read(reverb_track,reverb_id)["decay_seconds"]-2.0)<.001
        assert abs(reverb_render("reverb-reopened.wav")-reverb_tail)<.001
        result["checks"].append("reverb creates a real tail; bypass, Undo and reopen preserve real behavior")
        write("set_track_muted",{"track_id":reverb_track,"muted":True})
        write("import_audio",{"paths":[str(fixture)]})
        filter_track=client.state()["tracks"][-1]["id"]
        filter_id=write("add_native_effect",{"track_id":filter_track,"type":"auto_filter"})["device_id"]
        filt={"version":1,"type":"auto_filter","mode":"low_pass","frequency_hz":100,"resonance_q":.7071,"lfo_enabled":False,"lfo_hz":1,"lfo_depth":0,"dry_wet":1}
        write("set_native_effect",{"track_id":filter_track,"device_id":filter_id,"state":filt})
        filtered=render("filter.wav")
        write("set_plugin_enabled",{"track_id":filter_track,"plugin_id":filter_id,"enabled":False})
        unfiltered=render("filter-bypass.wav");assert filtered<unfiltered*.2,(filtered,unfiltered)
        write("undo");assert abs(render("filter-undo.wav")-filtered)<.003
        filter_project=directory/"filter.emproj";write("save_project",{"path":str(filter_project)});write("open_project",{"path":str(filter_project)})
        assert read(filter_track,filter_id)["frequency_hz"]==100 and abs(render("filter-reopen.wav")-filtered)<.003
        result["checks"].append("auto filter changes audio and preserves bypass, Undo and reopen")
        result.update(passed=True,baseline=baseline,boosted=boosted,compressed=compressed,restored=restored)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}";raise
    finally:
        if client:client.close()
        path=directory/"report.json";path.write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps({"report":str(path),**result}))
if __name__=="__main__": main()
