"""Record bounded 0.13.3 demo validation commands without rebuilding the DAW."""
import os
from pathlib import Path
import sys
from dev import Recorder, configure_console_output

configure_console_output()
temporary = Path('E:/MusicAgent&DAW/demo-video/2026-11-14/temporary')
temporary.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
os.environ['EMUSICIAN_AUDIO_CACHE_ROOT'] = 'E:/MusicAgent&DAW/audio-cache'
if len(sys.argv) < 2:
    raise SystemExit('Pass the executable and its arguments.')
Recorder('demo-rehearsal-check', '0.13.3/Release; no native build',
         'Exact English demo prompts; bounded real model calls on disposable offline-device projects; no user UI control').execute(sys.argv[1:])
