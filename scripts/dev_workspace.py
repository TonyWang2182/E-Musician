"""Logged 0.11.0 brand/workspace builds and checks; no paid model calls."""
import argparse
import sys
from pathlib import Path
from dev import Recorder, configure_console_output

def main():
    configure_console_output()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['configure','build','ctest','core','workspace','effects-benchmark','agent','web','tempo-e2e','colour-e2e','sidebar'])
    parser.add_argument('--build-dir',default='E:/emusician-analysis-build')
    parser.add_argument('--source-dir',default='E:/emusician-analysis-source')
    args=parser.parse_args()
    build=Path(args.build_dir)
    exe=build/'bin-0.11.0/Release/E-musician.exe'
    commands={
        'configure':['cmake','-S',args.source_dir,'-B',str(build),'-DEMUSICIAN_RUNTIME_OUTPUT_ROOT='+str(build/'bin-0.11.0')],
        'build':['cmake','--build',str(build),'--config','Release','--parallel','2','--','/p:UseMultiToolTask=true','/p:CL_MPCount=2','/p:EnforceProcessCountAcrossBuilds=true'],
        'ctest':['ctest','--test-dir',str(build),'-C','Release','--output-on-failure'],
        'core':['ctest','--test-dir',str(build),'-C','Release','--output-on-failure','-E','engine.integration_smoke|workspace.brand_colour|control.output_isolation'],
        'workspace':[sys.executable,'tests/RunWorkspaceSmoke.py',str(exe),'E:/emusician-analysis-build/workspace-smoke'],
        'effects-benchmark':[str(build/'Release/emusician_effects_benchmark.exe')],
        'agent':[sys.executable,'-m','unittest','discover','-s','tests','-p','test_music_agent*.py','-v'],
        'web':[sys.executable,'tests/AnalysisAgentWebSmoke.py'],
        'tempo-e2e':[sys.executable,'tests/MusicAgentTempoIntegration.py','--exe',str(exe),'--timeout','300'],
        'colour-e2e':[sys.executable,'tests/MusicAgentColourIntegration.py','--exe',str(exe),'--timeout','60'],
        'sidebar':[sys.executable,'tests/RunWorkspaceSidebar.py',str(exe),'E:/emusician-analysis-build/workspace-sidebar'],
    }
    return Recorder('workspace-brand-'+args.action,'Release/Python','0.11.0 brand, track colours and workspace; hardware/audio quality not inferred').execute(commands[args.action]).returncode

if __name__=='__main__':raise SystemExit(main())
