"""Logged 0.10.0 workstation build/test entry; no paid model calls."""
import argparse
import sys
from pathlib import Path
from dev import Recorder, configure_console_output

def main():
    configure_console_output()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['configure','build','ctest','agent','worker','e2e','agent-e2e','tempo-e2e','web'])
    parser.add_argument('--build-dir',default='E:/emusician-analysis-build')
    parser.add_argument('--source-dir',default='E:/emusician-analysis-source')
    parser.add_argument('--analysis-python',default='E:/MusicAgent&DAW/analysis/runtimes/beats-cuda-py310/Scripts/python.exe')
    args=parser.parse_args()
    build=Path(args.build_dir);exe=build/'bin-0.10.0/Release/E-musician.exe'
    commands={
      'configure':['cmake','-S',args.source_dir,'-B',str(build),'-DEMUSICIAN_RUNTIME_OUTPUT_ROOT='+str(build/'bin-0.10.0')],
      'build':['cmake','--build',str(build),'--config','Release','--parallel','2','--','/p:UseMultiToolTask=true','/p:CL_MPCount=2','/p:EnforceProcessCountAcrossBuilds=true'],
      'ctest':['ctest','--test-dir',str(build),'-C','Release','--output-on-failure'],
      'agent':[sys.executable,'-m','unittest','discover','-s','tests','-p','test_music_agent*.py','-v'],
      'worker':[args.analysis_python,'-m','unittest','discover','-s','tests','-p','test_audio_analysis*.py','-v'],
      'e2e':[sys.executable,'tests/AudioAnalysisEndToEnd.py','--exe',str(exe),'--six-stems'],
      'agent-e2e':[sys.executable,'tests/MusicAgentAnalysisIntegration.py','--exe',str(exe),'--six-stems'],
      'tempo-e2e':[sys.executable,'tests/MusicAgentTempoIntegration.py','--exe',str(exe),'--timeout','300'],
      'web':[sys.executable,'tests/AnalysisAgentWebSmoke.py'],
    }
    result=Recorder('tempo-warp-'+args.action,'Release/Python','0.10.0 fixed-tempo beat/Warp and workspace; offline checks, no physical audio or quality claim').execute(commands[args.action])
    return result.returncode

if __name__=='__main__':raise SystemExit(main())
