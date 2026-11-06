"""Real isolated native DAW + configured generation service, deterministic LLM.

This deliberately performs one real short music-generation request unless an
explicit fixture registry has been selected externally. The default language
provider is deterministic. --live explicitly uses the existing configured
language API, at most four calls, without modifying settings or printing keys.
No physical audio devices are accessed. Run through Recorder.
"""
from pathlib import Path
from copy import deepcopy
from contextlib import ExitStack
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from agent_client import Client
from music_agent.bridge import DawBridge
from music_agent.runtime import AgentRuntime
from music_agent.config import DEFAULT_CONFIG
from music_agent.generation import COMMANDS
from MusicAgentAnalysisIntegration import Provider, Audit, tool


def protected_snapshot():
    """Guard user material, not concurrently written disposable render jobs.

    Include the real LOCALAPPDATA Agent preferences and encrypted key files.
    Never print their contents or digests. Only runtime cache/render/temp files
    and the Agent's own append-only audit are outside this comparison.
    """
    app = Path(os.environ["APPDATA"])/"E-musician"
    agent = Path(os.environ["LOCALAPPDATA"])/"E-musician"/"agent"
    paths = {"app/"+p.relative_to(app).as_posix(): p for p in app.rglob("*")
             if p.is_file() and p.relative_to(app).parts[0] not in {"cache", "render-jobs", "Temporary"}}
    paths.update({"agent/"+p.name: p for p in agent.glob("*") if p.is_file() and p.name != "audit.jsonl" and p.name != "audit.previous.jsonl"})
    roots = {Path(p).resolve() for p in ("E:/MusicAgent&DAW/test-projects", "E:/E-musician/test-projects") if Path(p).is_dir()}
    for i, root in enumerate(sorted(roots)):
        paths.update({f"projects-{i}/"+p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()})
    result = {}
    for name, path in paths.items():
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024*1024), b""): digest.update(block)
        result[name] = digest.hexdigest()
    return result


def protected_changes(before, after):
    changed = sorted(name for name in before if before.get(name) != after.get(name))
    added = sorted(set(after)-set(before))
    return {"unchanged": not changed and not added, "changed_or_removed": changed, "unexpected_additions": added,
            "exclusions": "Transient render-jobs, cache, Temporary and own append-only audit logs"}


class GenerateProvider(Provider):
    def __init__(self, prompt, duration):
        super().__init__("start_generation", {"prompt": prompt, "duration_seconds": duration, "seed": 7021})
    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1: return tool(self.name, self.args)
        reply = json.loads(next(m["content"] for m in reversed(messages) if m["role"] == "tool"))
        assert reply["job"]["status"] == "ready", reply
        return tool("propose_generation_import", {"result_id": reply["candidate"]["result_id"], "summary": "Add the actual generated audio to a new track"})


class BoundedBridge(DawBridge):
    def __init__(self, client, duration):
        super().__init__(client=client)
        self.duration_budget, self.generation_attempts = duration, 0
    def start_generation(self, context, scope, args):
        duration = args.get("duration_seconds")
        if self.generation_attempts or type(duration) not in (int, float) or not 10 <= duration <= self.duration_budget:
            raise ValueError("Probe permits one generation request within the explicit duration budget")
        self.generation_attempts += 1
        return super().start_generation(context, scope, args)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", type=Path, required=True)
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--duration", type=float, default=16)
    ap.add_argument("--live", action="store_true", help="Explicit opt-in: one semantic probe with the existing configured language provider, at most four calls")
    ap.add_argument("--prompt", default="Instrumental warm electric piano, mellow bass and soft drums, clean studio sound, relaxed groove")
    ap.add_argument("--fixture-service", action="store_true", help="Evidence label only; service registry must be separately configured to a deterministic fixture")
    args = ap.parse_args()
    if args.live and args.fixture_service: ap.error("--live requires real generation service evidence")
    directory = ROOT/"build/agent-generation-e2e"/uuid.uuid4().hex; directory.mkdir(parents=True)
    executable = directory/"E-musician.exe"; shutil.copy2(args.exe, executable)
    report = {"passed": False, "mode": "real-native-with-fixture-generation" if args.fixture_service else "real-native-and-cloud-generation",
              "language_provider": "existing-configured-live" if args.live else "deterministic-fixture-no-LLM-call", "physical_audio": False, "quality_claim": False,
              "exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "checks": []}
    checks = report["checks"]; before = protected_snapshot(); client = None; runtime = None
    def wait(runtime, phase="done"):
        runtime.worker.join(args.timeout)
        assert not runtime.busy(), "Generation Agent timed out"
        assert runtime.phase == phase, "Agent stopped in phase " + runtime.phase
    try:
        client = Client(executable, timeout=max(180, args.timeout), show=False, offline_test=True)
        bridge = BoundedBridge(client, args.duration); initial = bridge.snapshot()
        assert not initial["tracks"] and COMMANDS <= set(bridge.capabilities()["commands"])
        assert bridge.generation_capabilities()["available"]
        checks.append("Actual native generation commands and configured runtime are available on an empty project")
        with ExitStack() as stack:
            stack.enter_context(patch("music_agent.runtime.MAX_MODEL_ROUNDS", 4))
            if not args.live:
                stack.enter_context(patch("music_agent.runtime.load_config", return_value=deepcopy(DEFAULT_CONFIG)))
                stack.enter_context(patch("music_agent.runtime.has_key", return_value=False))
                stack.enter_context(patch("music_agent.providers.has_key", return_value=False))
            runtime = AgentRuntime(bridge, provider=None if args.live else GenerateProvider(args.prompt, args.duration), audit=Audit())
            report["language_model"] = runtime.provider.model
            started = time.monotonic()
            runtime.plan_request(f"Generate {args.duration:g} seconds of instrumental music: {args.prompt}. Use the current project tempo. Do not retry or generate another candidate. Propose importing the generated audio to a new track for my review; do not apply it yet.", scope="selection")
            wait(runtime, "ready"); report["request_to_review_seconds"] = time.monotonic()-started
            assert 1 <= runtime.usage["calls"] <= 4 and runtime.generation_request
            assert bridge.generation_attempts == 1
            if not args.live: assert runtime.provider.calls == 2
            assert bridge.snapshot()["revision"] == initial["revision"] and not bridge.snapshot()["tracks"]
            plan = deepcopy(runtime.plan); result = plan["generation"]
            report["candidate"] = result
            assert result["audio"]["duration_seconds"] > 0 and result["model"]["id"]
            checks.append("An actual generated/downloaded candidate reaches review within four language calls without mutating the empty project")
            runtime.preview_generation_plan(plan["id"])
            preview_deadline = time.monotonic() + 10
            while time.monotonic() < preview_deadline:
                audition = runtime.state()["generation_preview"]
                if audition["status"] not in {"preparing", "loading"}: break
                time.sleep(.1)
            report["preview_status"] = audition
            assert audition["status"] in {"playing", "completed", "unavailable"}, "Preview did not report a playback/device outcome"
            runtime.preview_generation_plan(stop=True)
            assert bridge.snapshot()["revision"] == initial["revision"]
            checks.append("Preview preparation and stream/device status are read back; Stop preserves project revision. Physical playback is not tested")
            runtime.apply(plan["id"]); wait(runtime)
            applied = bridge.snapshot()
            assert len(applied["tracks"]) == 1 and applied["revision"] == initial["revision"]+1 and runtime.undo_target
            assert bridge.generation_result(result["result_id"])["applied"]
            checks.append("Explicit Agent confirmation imports one audio track once and verifies local candidate identity, start and duration")
            runtime.undo(); wait(runtime); assert not bridge.snapshot()["tracks"]
            client.request({"command": "redo"}); assert len(bridge.snapshot()["tracks"]) == 1
            checks.append("One Agent Undo removes the generated track; native Redo restores it")
            project = directory/"generated.emproj"
            client.request({"command": "save_project", "args": {"path": str(project)}})
            client.request({"command": "open_project", "args": {"path": str(project)}})
            reopened = bridge.snapshot(); clip = reopened["tracks"][0]["clips"][0]
            assert len(reopened["tracks"]) == 1 and clip["kind"] == "audio"
            assert abs(clip["duration_seconds"]-result["audio"]["duration_seconds"]) < .002
            checks.append("Actual save/reopen preserves the generated audio track and duration")
            report["saved_project"] = str(project)
        client.close(); client = None
        # A separate fresh DAW cannot use the cloud service. Accepted audio must
        # remain independent of configuration and remote job/cache lifetime.
        offline_root = directory/"no-generation-service"; offline_root.mkdir()
        with patch.dict(os.environ, {"EMUSICIAN_GENERATION_ROOT": str(offline_root)}):
            client = Client(executable, timeout=180, show=False, offline_test=True)
        bridge = DawBridge(client=client); assert not bridge.generation_capabilities()["available"]
        client.request({"command": "open_project", "args": {"path": str(project)}})
        offline = bridge.snapshot(); assert len(offline["tracks"]) == 1 and abs(offline["tracks"][0]["clips"][0]["duration_seconds"]-result["audio"]["duration_seconds"]) < .002
        checks.append("A fresh native process with no generation registry reopens the saved local audio project")
        report["passed"] = True
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        if runtime: report["agent_phase"] = runtime.phase
        raise
    finally:
        if runtime:
            report["language_usage"] = dict(runtime.usage)
            if runtime.busy():
                runtime.cancel(); runtime.worker.join(15)
        if client: client.close()
        report["protected_file_changes"] = protected_changes(before, protected_snapshot())
        report["passed"] = report["passed"] and report["protected_file_changes"]["unchanged"]
        output = directory/"result.json"; output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2)); print(output)
    assert report["passed"]


if __name__ == "__main__": main()
