"""Recorded, isolated recording/showcase builds. Never overwrites 0.13.6."""
import argparse
import os
from pathlib import Path
from dev import Recorder, configure_console_output

BUILD = 'E:/emusician-analysis-build'
OUTPUTS = {'recording': BUILD + '/bin-0.13.6-recording', 'showcase': BUILD + '/bin-showcase-v1'}

def main():
    configure_console_output()
    parser = argparse.ArgumentParser()
    parser.add_argument('variant', choices=OUTPUTS)
    parser.add_argument('action', choices=['configure', 'build', 'test', 'command'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    temporary = Path(__file__).resolve().parents[1] / 'build' / 'showcase-temp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    output = OUTPUTS[args.variant]
    recorder = Recorder('showcase-' + args.variant + '-' + args.action,
        'Release/' + args.variant, 'Offline showcase and live recording display; inference and physical listening are separate evidence')
    if args.action == 'configure':
        recorder.execute(['cmake', '--preset', 'windows-msvc', '-S', 'E:/emusician-analysis-source',
            '-B', BUILD, '-DEMUSICIAN_RUNTIME_OUTPUT_ROOT=' + output,
            '-DEMUSICIAN_SHOWCASE=' + ('ON' if args.variant == 'showcase' else 'OFF'),
            '-DEMUSICIAN_SHOWCASE_ROOT=E:/MusicAgent&DAW/demo-video/showcase-v1/workspace'])
    elif args.action == 'build':
        cache = (Path(BUILD) / 'CMakeCache.txt').read_text(encoding='utf-8')
        expected_mode = 'EMUSICIAN_SHOWCASE:BOOL=' + ('ON' if args.variant == 'showcase' else 'OFF')
        if 'EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH=' + output not in cache.splitlines() or expected_mode not in cache.splitlines():
            recorder.preflight_failure('Configure this isolated variant before building.')
            return 2
        jobs = str(max(1, min(2, int(os.environ.get('EMUSICIAN_BUILD_JOBS', '1')))))
        recorder.execute(['cmake', '--build', BUILD, '--config', 'Release', '--parallel', jobs, '--',
            '/p:UseMultiToolTask=true', '/p:CL_MPCount=' + jobs, '/p:EnforceProcessCountAcrossBuilds=true'])
    elif args.action == 'test':
        cache = (Path(BUILD) / 'CMakeCache.txt').read_text(encoding='utf-8')
        expected_mode = 'EMUSICIAN_SHOWCASE:BOOL=' + ('ON' if args.variant == 'showcase' else 'OFF')
        if 'EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH=' + output not in cache.splitlines() or expected_mode not in cache.splitlines():
            recorder.preflight_failure('Configure and build this isolated variant before testing.')
            return 2
        recorder.execute(['ctest', '--test-dir', BUILD, '-C', 'Release', '--output-on-failure', *args.arguments])
    else:
        if not args.arguments:
            parser.error('command requires executable and arguments')
        recorder.execute(args.arguments)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
