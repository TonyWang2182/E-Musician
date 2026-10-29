"""Recorded developer and launch commands for the embedded Agent build."""
from pathlib import Path
import argparse
import sys
from dev import Recorder
ROOT=Path(__file__).resolve().parent.parent
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["build","test","run"])
    parser.add_argument("--config",choices=["Debug","Release"],default="Release")
    parser.add_argument("--exe",type=Path)
    args=parser.parse_args()
    recorder=Recorder("agent-native-"+args.action,args.config,"Embedded Agent batch 2; physical audio acceptance remains manual")
    if args.action=="build":
        recorder.execute([sys.executable,str(ROOT/"scripts/bootstrap_webview2.py"),"--worker"])
        recorder.execute(["cmake","--preset","windows-msvc","-B","build/agent-batch2"])
        recorder.execute(["cmake","--build","build/agent-batch2","--config",args.config,"--parallel","2",
            "--","/p:UseMultiToolTask=true","/p:CL_MPCount=2","/p:EnforceProcessCountAcrossBuilds=true"])
    elif args.action=="test":
        recorder.execute(["ctest","--test-dir","build/agent-batch2","-C",args.config,"--output-on-failure"])
        recorder.execute([sys.executable,str(ROOT/"scripts/check_agent.py"),"--exe",
            str(ROOT/"build/agent-batch2/bin"/args.config/"E-musician.exe")])
        recorder.execute([sys.executable,str(ROOT/"tests/EmbeddedHelperStartup.py")])
        recorder.execute([sys.executable,str(ROOT/"tests/EmbeddedAgentIntegration.py"),"--recorded","--exe",
            str(ROOT/"build/agent-batch2/bin"/args.config/"E-musician.exe")])
    else:
        exe=args.exe or ROOT/"build/agent-batch2/bin"/args.config/"E-musician.exe"
        if not exe.is_file():
            recorder.preflight_failure("Embedded DAW executable missing.")
            parser.error("Build first with: python scripts/dev_agent.py build")
        recorder.execute([str(exe.resolve()),"--agent"],launch_only=True)
    return 0
if __name__=="__main__":raise SystemExit(main())
