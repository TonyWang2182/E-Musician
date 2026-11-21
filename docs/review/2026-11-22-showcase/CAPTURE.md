# Actual native-window capture helper

Status: Python syntax/CLI checked. The initial Demo 4 / D3 still-image sessions below captured staged project copies without playback, recording or Save. Later independent showcase sessions performed actual Preview, Apply, project playback and Analysis operations; their results and failures are recorded separately in [GUI.md](GUI.md). All owned capture sessions have ended. No new model inference or physical microphone performance was captured. Native recording candidate validation remains a separate task.

`scripts/showcase_capture.py` uses Win32 window ownership/geometry, native mouse messages, and Pillow's actual client-rectangle pixels. No CUA, browser skill, virtual audio device, microphone simulation, or new Python package is required. Python 3.14 and Pillow are installed locally. Supply the existing FFmpeg path for video; FFmpeg is not on the current shell PATH.

## Callable API

Run from the repository with `scripts` on `sys.path`:

```python
from pathlib import Path
from agent_client import Client
from showcase_capture import CaptureSession

with Client(Path(executable), show=True) as client:
    with CaptureSession(client=client, output=Path(output)) as capture:
        capture.open_project(Path(staged_project))
        capture.resize(1600, 950)
        capture.screenshot('01-arrangement')
        # Inspect controls() for the track's exact button name/index first.
        capture.invoke('devices', observed_track_button_index)
        capture.invoke_menu('edit', 'Edit MIDI notes...')
        capture.screenshot('02-piano-roll')
        capture.command('play')
        capture.record('03-playback', seconds=5, fps=15, ffmpeg=Path(ffmpeg))
        capture.command('stop')
```

- `open_project()` only accepts staged `.emproj` copies inside `E:/MusicAgent&DAW/demo-video/showcase-v1/captures/projects`. An explicit alternative staging root may be passed to the constructor. It never saves the user’s original.
- `screenshot(name)` saves an actual PNG. Existing named media files are not overwritten.
- `click(x, y, double=False)` sends messages only within the selected app’s native client hierarchy. Coordinates are physical client pixels from an inspected screenshot. Double-click a real MIDI clip to open the actual piano roll. Click the actual track Devices button, then its device-chain item to open the native Sampler, Rack, or effect.
- Prefer `controls()` and `invoke(exact_observed_name, index=0)` for buttons. These read the app's genuine JUCE accessibility tree and execute Invoke/Toggle patterns. Synthetic mouse messages may leave a transient drag rejection; a normal toolbar Stop clears this UI status without changing music. Screenshots still require visual inspection. The generic double-click message is ignored by this pinned JUCE backend, so the helper sends two native press/release pairs.
- `invoke_menu(button, item)` opens and invokes an observed popup menu item within one UIA client lifetime. This is necessary because the popup can disappear between separate PowerShell/UIA clients. For a MIDI track, its `devices` button selects the track/first clip; `invoke_menu('edit', 'Edit MIDI notes...')` then opens the genuine piano roll without synthetic clip dragging. Prefer this to coordinate double-clicks: one D3 attempt moved the isolated in-memory clip, was undone/reloaded without Save, and is excluded from selected captures. Opening the Agent uses the observed `Agent` button; owned WebView CDP can control the sidebar afterwards.
- `command(name, args)` uses the owned stdio client. For an already loaded VST, `open_plugin` with its real track/plugin IDs can open the actual editor; call `windows()` to locate its same-process HWND, then `screenshot(name, hwnd=...)`. A separate-process plugin editor is deliberately unsupported by this helper.
- `record()` writes fresh frames to FFmpeg at the requested frame rate. Clips have **no audio**. Receipts retain actual frame timestamps, rather than claiming frame-rate or hardware performance guarantees.
- `CaptureSession(pid=..., output=...)` can capture an explicitly identified existing E-musician, but cannot issue stdio commands or open a project. It does not close that process.
- `--webview-port 9229` applies a WebView2 remote-debugging argument only to a newly owned `--exe` child; the Python environment is restored immediately after launch. The existing `tests/analysis_agent_web_capture.mjs` CDP approach can then drive the actual embedded Agent DOM. Do not inject invented task results for a screenshot.

## CLI

```powershell
python scripts/showcase_capture.py --exe <isolated-exe> --offline-test --project <staged-project.emproj> --output <capture-folder> --name arrangement
python scripts/showcase_capture.py --pid <owned-daw-pid> --output <capture-folder> --recipe <observed-actions.json> --ffmpeg <ffmpeg.exe>
```

Recipe is an ordered JSON array: `screenshot` (`name`), `invoke` (`name`, optional `index`), `menu` (`button`, `item`), `click`/`double_click` (`x`, `y`), `wait` (`seconds`, max 10), `command` (`command`, optional `args`/`wait`), `record` (`name`, `seconds` ≤ 60, optional `fps`), or `resize` (`width`, `height`). Window control and capture stop if the expected DAW is gone, another application has foreground, or a coordinate is covered by another window. Foreground restoration is restricted to the owned DAW and temporarily attaches/detaches input queues; it sends no global keystrokes or cursor input.

Each session preserves its own timestamped capture receipt, plus `capture-receipt.json` as the most recent receipt. PNG/video entries include SHA-256, actual dimensions, owning PID and provenance. Receipts do not contain complete project/API configuration. `inference_evidence=false` and `microphone_capture=false` distinguish this footage from inference and physical recording validation.

## Captured evidence

`E:/MusicAgent&DAW/demo-video/showcase-v1/captures/demo4` holds actual native UI images and `source-verification.json`. The original `test drive.emproj` and all 27 referenced asset/state files were copied with matching hashes. The runtime remained clean (`dirty=false`) and no Save was called. Reviewed acceptable shots are recorded in `selected-final-manifest.json`; earlier attempts with stale footer errors, a still-loading waveform, a hover tooltip, or Keyscape's startup cover are excluded. Do not select files merely because their filename contains `final` or `clean`.

These are still images of the real stopped project, not a substitute for the user's intended continuous playback, Sax performance, live microphone waveform recording, or final video capture. No inference, audible VST, recording-device, or performance claim follows from them.

`captures/d3-piano/selected-final-manifest.json` selects five reviewed actual images from the copied `D3-Keyscape-MIDI-only` audition project: arrangement, lower piano roll, expanded roll, full 132-note Fit view, and the genuine Keyscape editor showing its saved LA Custom C7 Grand Piano. The original/staged project and two supporting files have matching hashes in `source-verification.json`. Final state was clean/stopped/not recording; process exit 0. `02` (reverted synthetic drag) and `06` (Keyscape cover) are excluded. Clicking the observed Keyscape cover at its logo dismissed that cover without changing the preset; `07-keyscape-editor.png` is the resulting actual editor. This capture did not play audio, re-run Transkun, save, or call a provider.

Demo 4 supplement `35-ep-keyscape-editor.png` shows the same `test drive` project's actual EP-track Keyscape editor, with its saved Rhodes - LA Custom Suitcase preset. Added as the eleventh accepted image after visual review; `34` is only the preceding cover and is excluded. No preset change, playback, recording or Save was triggered; final dirty/playing/recording flags were false and the owned process exited 0. Use this image for Demo 4 VST support; the D3 piano image belongs to its separate audition project.
