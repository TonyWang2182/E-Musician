"""Recorded isolated 0.13.6 audio-input and driver-settings work."""
import argparse
import os
from pathlib import Path
from dev import Recorder, configure_console_output

BUILD = 'E:/emusician-analysis-build'
OUTPUT = BUILD + '/bin-0.13.6'

def main():
    configure_console_output()
    temporary = Path(__file__).resolve().parents[1] / 'build' / 'audio-input-temp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    os.environ['EMUSICIAN_AUDIO_CACHE_ROOT'] = 'E:/MusicAgent&DAW/audio-cache'
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['configure', 'build', 'test', 'command', 'run'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    record = Recorder('audio-input-' + args.action, 'Release/0.13.6',
        'Physical input activation, portable device configuration and driver-panel lifecycle; listening is separate')
    if args.action == 'configure':
        record.execute(['cmake', '--preset', 'windows-msvc', '-S', 'E:/emusician-analysis-source',
            '-B', BUILD, '-DEMUSICIAN_RUNTIME_OUTPUT_ROOT=' + OUTPUT, '-DEMUSICIAN_SHOWCASE=OFF'])
    elif args.action == 'build':
        cache = (Path(BUILD) / 'CMakeCache.txt').read_text(encoding='utf-8')
        if 'EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH=' + OUTPUT not in cache.splitlines() or 'EMUSICIAN_SHOWCASE:BOOL=OFF' not in cache.splitlines():
            record.preflight_failure('Configure isolated 0.13.6 output before building.')
            return 2
        record.execute(['cmake', '--build', BUILD, '--config', 'Release', '--parallel', '1', '--',
            '/p:UseMultiToolTask=true', '/p:CL_MPCount=1', '/p:EnforceProcessCountAcrossBuilds=true'])
    elif args.action == 'test':
        record.execute(['ctest', '--test-dir', BUILD, '-C', 'Release', '--output-on-failure', *args.arguments])
    elif args.action == 'run':
        record.execute([OUTPUT + '/Release/E-musician.exe', '--agent'], launch_only=True)
    else:
        if not args.arguments:
            parser.error('command requires executable and arguments')
        record.execute(args.arguments)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
