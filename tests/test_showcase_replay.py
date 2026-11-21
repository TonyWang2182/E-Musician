"""Retained-result planner/worker boundaries. Synthetic fixture media, no models.

Run with the repository Recorder. These are unit checks, not listening or GUI
acceptance; the production native candidate/import pipeline needs its own test.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from showcase.package import Package, contained, read_json, sha256
from showcase.replay_worker import prepare
from music_agent.replay_provider import ReplayProvider, CONTEXT_MARKER
from music_agent.runtime import AgentRuntime


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "results/a").mkdir(parents=True)
        self.directory = self.root / "runtime/analysis/cache/jobs/newjob"
        self.directory.mkdir(parents=True)
        self.request_file = self.directory / "request.json"
        self.audio = self.root / "source.wav"
        with wave.open(str(self.audio), "wb") as wav:
            wav.setparams((1,2,44100,0,"NONE","not compressed"))
            wav.writeframes(b"\x00\x00"*44100)
        self.scene = {"id":"a", "project_id":"p1", "kind":"transcribe", "model_id":"transkun",
            "prompts":["Transcribe the selected piano."], "application":"import", "wait_seconds":0,
            "parameters":{}, "source":{"sha256":sha256(self.audio),"offset_seconds":0,"duration_seconds":1,"sample_rate":44100,"warp_speed_ratio":1},
            "result_path":"results/a/result.json"}
        self.result = {"schema_version":1,"job_id":"original","result_id":"original","kind":"transcribe",
            "model":{"id":"transkun","version":"test"},"parameters":{},"duration_seconds":1,
            "source":{"project_id":"old","source_sha256":sha256(self.audio)},
            "notes":[{"pitch":60,"start_seconds":0,"end_seconds":.5,"velocity":90,"channel":1}]}
        self.request = {"job_id":"newjob","kind":"transcribe","model_id":"transkun","parameters":{},
            "source_path":str(self.audio),"source_offset_seconds":0,"duration_seconds":1,
            "source":{"project_id":"p1","clip_id":"selected","sample_rate":44100,"warp_speed_ratio":1}}
        self.commit()

    def commit(self):
        self.write(self.root / self.scene["result_path"], self.result)
        self.scene["result_sha256"] = sha256(self.root / self.scene["result_path"])
        self.write(self.root / "manifest.json", {"schema_version":1,
            "projects":[{"id":f"p{i}","path":f"projects/{i}.emproj"} for i in range(1,4)],"scenarios":[self.scene]})
        self.write(self.request_file,self.request)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value,allow_nan=False),encoding="utf-8")

    def plan_messages(self, prompt=None, project="p1", clip="selected"):
        context={"project_id":project,"revision":2,"bpm":90,"selection_context":{"active_clip_id":clip},
            "tracks":[{"id":"track","clips":[{"id":"selected","kind":"audio","source_offset":0}]}]}
        return [{"role":"user","content":(prompt or self.scene["prompts"][0])+CONTEXT_MARKER+json.dumps(context)}]

    @staticmethod
    def tools():
        return [{"function":{"name":s}} for s in ("start_generation","start_audio_analysis","propose_generation_import","propose_analysis_import","propose_beat_application")]

    def test_worker_preserves_notes_and_original_result(self):
        original=(self.root/self.scene["result_path"]).read_bytes()
        result=prepare(self.root,self.request_file)
        self.assertEqual(result["notes"],self.result["notes"])
        self.assertEqual(result["source"]["clip_id"],"selected")
        self.assertEqual(result["result_id"],"newjob")
        self.assertFalse(result["retained_result"]["inference_performed"])
        self.assertEqual(result["retained_result"]["original_job_id"],"original")
        self.assertEqual(result["parameters"],{})  # Native public parameter schema remains unchanged.
        self.assertEqual((self.root/self.scene["result_path"]).read_bytes(),original)
        self.assertEqual(read_json(self.directory/"progress.json")["phase"],"ready")

    def test_source_content_change_is_rejected(self):
        with self.audio.open("ab") as stream:stream.write(b"changed")
        with self.assertRaisesRegex(ValueError,"selected audio"):prepare(self.root,self.request_file)
        self.assertFalse((self.directory/"result.json").exists())

    def test_result_content_change_is_rejected(self):
        (self.root/self.scene["result_path"]).write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"verification"):prepare(self.root,self.request_file)

    def test_wrong_project_or_model_rejected(self):
        for key in ("project", "model"):
            with self.subTest(key=key):
                request=deepcopy(self.request)
                if key=="project":request["source"]["project_id"]="p2"
                else:request["model_id"]="unknown"
                self.write(self.request_file,request)
                with self.assertRaises(ValueError):prepare(self.root,self.request_file)

    def test_range_rate_warp_and_options_rejected(self):
        mutations=[{"duration_seconds":.8},{"source_offset_seconds":.2},{"parameters":{"min_pitch":30}},
            {"source":{**self.request["source"],"sample_rate":48000}},
            {"source":{**self.request["source"],"warp_speed_ratio":1.25}}]
        for change in mutations:
            with self.subTest(change=change):
                self.write(self.request_file,{**self.request,**change})
                with self.assertRaises(ValueError):prepare(self.root,self.request_file)

    def test_output_cannot_escape_isolated_runtime(self):
        outside=self.root/"request.json";self.write(outside,self.request)
        with self.assertRaisesRegex(ValueError,"isolated runtime"):prepare(self.root,outside)

    def test_cancel_before_or_during_delay(self):
        (self.directory/"cancel").touch()
        with self.assertRaises(InterruptedError):prepare(self.root,self.request_file)
        (self.directory/"cancel").unlink()
        self.scene["wait_seconds"]=10;self.commit()
        def sleep(_): (self.directory/"cancel").touch()
        with self.assertRaises(InterruptedError):prepare(self.root,self.request_file,clock=lambda:0,sleep=sleep)
        self.assertFalse((self.directory/"result.json").exists())

    def test_delay_is_configurable_and_progress_is_honest(self):
        self.scene["wait_seconds"]=.12;self.commit();now=[0.0]
        def sleep(seconds):
            self.assertEqual(read_json(self.directory/"progress.json")["detail"],"Preparing...")
            now[0]+=seconds
        result=prepare(self.root,self.request_file,clock=lambda:now[0],sleep=sleep)
        self.assertGreaterEqual(now[0],.12)
        self.assertEqual(result["retained_result"]["presentation_wait_seconds"],.12)

    def test_manifest_traversal_duplicate_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError):contained(self.root,"../outside.wav")
        file=self.root/"bad.json"
        for value in ('{"x":1,"x":2}','{"x":1e999}','{"x":NaN}'):
            file.write_text(value,encoding="utf-8")
            with self.assertRaises(ValueError):read_json(file)

    def test_fixed_instruction_matches_case_and_whitespace_only(self):
        package=Package(self.root)
        self.assertEqual(package.instruction(" TRANSCRIBE   the selected piano! ","p1")["id"],"a")
        for prompt,project in [("Delete all tracks","p1"),(self.scene["prompts"][0],"p2")]:
            with self.assertRaises(ValueError):package.instruction(prompt,project)

    def test_planner_reads_selected_clip_and_uses_native_commands(self):
        response=ReplayProvider(self.root).complete(self.plan_messages(),self.tools())
        call=response["message"]["tool_calls"][0]["function"]
        self.assertEqual(call["name"],"start_audio_analysis")
        self.assertEqual(json.loads(call["arguments"])["clip_id"],"selected")
        with self.assertRaises(ValueError):ReplayProvider(self.root).complete(self.plan_messages(clip="wrong"),self.tools())

    def test_candidate_is_proposed_not_applied(self):
        messages=self.plan_messages()+[{"role":"tool","content":json.dumps({"candidate":{"kind":"transcribe","result_id":"native-id"}})}]
        response=ReplayProvider(self.root).complete(messages,self.tools())
        self.assertEqual(response["message"]["tool_calls"][0]["function"]["name"],"propose_analysis_import")

    def test_manual_chords_have_no_automatic_apply(self):
        self.scene.update(kind="chords",model_id="chordmini",application="manual");self.commit()
        response=ReplayProvider(self.root).complete(self.plan_messages()+[{"role":"tool","content":json.dumps({"candidate":{"kind":"chords","result_id":"native-id"}})}],self.tools())
        self.assertNotIn("tool_calls",response["message"])
        self.assertIn("Open Analysis",response["message"]["content"])

    def test_warp_uses_native_beat_application(self):
        self.scene.update(kind="beats",model_id="beat-this-final0",application="warp");self.commit()
        response=ReplayProvider(self.root).complete(self.plan_messages()+[{"role":"tool","content":json.dumps({"candidate":{"kind":"beats","result_id":"native-id"}})}],self.tools())
        call=response["message"]["tool_calls"][0]["function"]
        self.assertEqual(call["name"],"propose_beat_application")
        self.assertEqual(json.loads(call["arguments"])["mode"],"audio_to_project")

    def test_failed_native_job_never_returns_fake_success(self):
        with self.assertRaisesRegex(ValueError,"Unable to prepare"):
            ReplayProvider(self.root).complete(self.plan_messages()+[{"role":"tool","content":'{"candidate":null,"job":{"status":"failed"}}'}],self.tools())

    def test_replay_runtime_reads_no_production_keys_or_preferences(self):
        with patch("music_agent.runtime.load_config",side_effect=AssertionError("credentials")), \
             patch("music_agent.runtime.has_key",side_effect=AssertionError("credentials")), \
             patch("music_agent.runtime.create_provider",side_effect=AssertionError("network provider")):
            runtime=AgentRuntime(SimpleNamespace(connected=False),ReplayProvider(self.root))
            state=runtime.state(False)
            self.assertTrue(state["presentation"])
            self.assertTrue(state["provider"]["configured"])
            self.assertEqual(state["usage"]["calls"],0)
            self.assertTrue(runtime.audit.path.is_relative_to(self.root/"runtime"))
            with self.assertRaises(ValueError):runtime.settings({"provider":"openai"})
            runtime._progress("analyzing","Connecting to cloud")
            self.assertEqual(runtime.progress["label"],"Preparing...")

    def test_page_offers_only_this_projects_exact_instructions(self):
        provider=ReplayProvider(self.root)
        offered=provider.capability_groups("p1")
        self.assertEqual([g["example"] for g in offered],self.scene["prompts"])
        self.assertEqual(provider.capability_groups("p2"),[])
        runtime=AgentRuntime(SimpleNamespace(connected=False),provider)
        runtime.snapshot={"project_id":"p1"}
        runtime.phase="ready"
        runtime.progress={"stage":"ready","label":"生成音频已下载；试听并确认后加入新轨道","completed":0,"total":0}
        self.assertEqual(runtime.state(False)["progress"]["label"],"Ready to review and apply.")
        runtime.phase="cancelled"
        self.assertEqual(runtime.state(False)["last_result"],"Cancelled. No changes were applied.")

    def test_generation_media_and_conditions_are_verified(self):
        (self.root/"results/a/audio.wav").write_bytes(self.audio.read_bytes())
        self.scene.update(kind="generate",model_id="yue2",parameters={"prompt":"Warm soul","lyrics":"Hi","seed":1,"bpm":90,"duration_seconds":10,"time_signature":"4/4"})
        self.result.update(kind="generate",model={"id":"yue2"},audio={"path":"audio.wav","sha256":sha256(self.audio)})
        self.request={"job_id":"newjob","kind":"generate","model_id":"yue2",**self.scene["parameters"],"meter_numerator":4,"meter_denominator":4,"source":{"project_id":"p1"}}
        self.commit()
        result=prepare(self.root,self.request_file)
        self.assertEqual(sha256(self.directory/"audio.wav"),result["audio"]["sha256"])
        for change in ({"bpm":120},{"seed":2},{"meter_numerator":3},{"prompt":"Something else"}):
            self.write(self.request_file,{**self.request,**change})
            with self.assertRaises(ValueError):prepare(self.root,self.request_file)

    def test_generation_planner_uses_original_conditioning(self):
        self.scene.update(kind="generate",model_id="yue2",parameters={"prompt":"Warm soul","lyrics":"Hi","seed":1,"bpm":90,"duration_seconds":10,"time_signature":"4/4"});self.commit()
        response=ReplayProvider(self.root).complete(self.plan_messages(),self.tools())
        call=response["message"]["tool_calls"][0]["function"]
        self.assertEqual(call["name"],"start_generation")
        args=json.loads(call["arguments"])
        self.assertEqual(args["prompt"],"Warm soul")
        self.assertEqual(args["seed"],1)

    def test_network_guard_blocks_external_connect_before_socket_io(self):
        code="import sys,socket;sys.path.insert(0,sys.argv[1]);from music_agent.replay_provider import install_loopback_guard;install_loopback_guard();s=socket.socket()\ntry:s.connect(('192.0.2.1',443))\nexcept PermissionError:print('blocked')\nelse:raise AssertionError('guard failed')"
        result=subprocess.run([sys.executable,"-c",code,str(SCRIPTS)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),"blocked")


if __name__=="__main__":unittest.main()
