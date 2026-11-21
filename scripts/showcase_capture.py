"""Capture actual E-musician windows, without CUA, drivers, or synthetic UI.

Import API (call only after the native build has passed):
    with Client(exe, show=True) as client:
        with CaptureSession(client=client, output=out) as capture:
            capture.open_project(staged_project)
            capture.screenshot('arrangement')  # inspect this before choosing coordinates
            capture.invoke('devices', 2)  # observed MIDI track, index from controls()
            capture.invoke_menu('edit', 'Edit MIDI notes...')
            capture.screenshot('piano-roll')
            capture.record('piano-playback', seconds=5, ffmpeg=ffmpeg)

Coordinates are physical pixels relative to the captured main client area.
Use explicit coordinates from an inspected screenshot, not hidden UI mocks.
Screenshots and clips are real pixels. Clips are SILENT; no fake microphone take
or loopback driver is installed. Receipts describe timing, scope, and provenance.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from PIL import ImageGrab
from agent_client import Client

STAGED_PROJECTS = Path('E:/MusicAgent&DAW/demo-video/showcase-v1/captures/projects')


def utc():
    return datetime.now(timezone.utc).isoformat()


class Win32:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Native capture requires Windows.')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        try:
            self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            self.user.SetProcessDPIAware()
        self.callback = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = {
            'EnumWindows': ([self.callback, W.LPARAM], W.BOOL),
            'GetWindowThreadProcessId': ([W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            'GetWindowTextW': ([W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetWindowTextLengthW': ([W.HWND], ctypes.c_int),
            'IsWindowVisible': ([W.HWND], W.BOOL),
            'IsWindow': ([W.HWND], W.BOOL),
            'GetParent': ([W.HWND], W.HWND),
            'GetAncestor': ([W.HWND, W.UINT], W.HWND),
            'GetForegroundWindow': ([], W.HWND),
            'SetForegroundWindow': ([W.HWND], W.BOOL),
            'AttachThreadInput': ([W.DWORD, W.DWORD, W.BOOL], W.BOOL),
            'ShowWindow': ([W.HWND, ctypes.c_int], W.BOOL),
            'SetWindowPos': ([W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT], W.BOOL),
            'GetClientRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            'ClientToScreen': ([W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
            'ScreenToClient': ([W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
            'WindowFromPoint': ([W.POINT], W.HWND),
            'ChildWindowFromPointEx': ([W.HWND, W.POINT, W.UINT], W.HWND),
            'SendMessageTimeoutW': ([W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT,
                                     ctypes.POINTER(ctypes.c_size_t)], ctypes.c_size_t),
        }
        for name, (args, result) in signatures.items():
            f = getattr(self.user, name)
            f.argtypes, f.restype = args, result

    def pid(self, hwnd):
        value = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
        return value.value

    def title(self, hwnd):
        text = ctypes.create_unicode_buffer(self.user.GetWindowTextLengthW(hwnd) + 1)
        self.user.GetWindowTextW(hwnd, text, len(text))
        return text.value

    def windows(self, pid):
        found = []
        @self.callback
        def collect(hwnd, _):
            if self.pid(hwnd) == pid and self.user.IsWindowVisible(hwnd):
                found.append({'hwnd': int(hwnd), 'title': self.title(hwnd)})
            return True
        self.user.EnumWindows(collect, 0)
        return found

    def send(self, hwnd, message, wparam=0, lparam=0):
        result = ctypes.c_size_t()
        if not self.user.SendMessageTimeoutW(hwnd, message, wparam, lparam, 0x0002, 2000, ctypes.byref(result)):
            raise RuntimeError('App did not acknowledge native UI message within 2 seconds.')


class CaptureSession:
    def __init__(self, *, client=None, pid=None, output: Path, project_root=STAGED_PROJECTS):
        self.win = Win32()
        self.client = client
        self.pid = int(client.process.pid if client is not None else pid or 0)
        if not self.pid:
            raise ValueError('Supply an owned Client or the explicit E-musician PID.')
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.project_root = Path(project_root).resolve()
        self.events = []
        self.started = utc()
        self.receipt_path = self.output / ('capture-receipt-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        deadline = time.monotonic() + 20
        self.hwnd = None
        while time.monotonic() < deadline:
            windows = self.win.windows(self.pid)
            matches = [w for w in windows if 'E-musician' in w['title'] and 'Audio' in w['title']]
            if matches:
                self.hwnd = matches[0]['hwnd']
                break
            if client is not None and client.process.poll() is not None:
                raise RuntimeError('Owned DAW exited before creating its visible window.')
            time.sleep(.1)
        if not self.hwnd:
            raise RuntimeError('No visible E-musician audio workspace for the specified PID.')
        self.log('attach', title=self.win.title(self.hwnd), hwnd=self.hwnd, pid=self.pid)

    def log(self, action, **data):
        self.events.append({'utc': utc(), 'action': action, **data})

    def validate(self, hwnd=None):
        hwnd = hwnd or self.hwnd
        if not self.win.user.IsWindow(hwnd) or self.win.pid(hwnd) != self.pid:
            raise RuntimeError('Target window is no longer owned by the captured DAW process.')
        return hwnd

    def windows(self):
        return self.win.windows(self.pid)

    def bounds(self, hwnd=None):
        hwnd = self.validate(hwnd)
        rect, point = W.RECT(), W.POINT()
        if not self.win.user.GetClientRect(hwnd, ctypes.byref(rect)) or not self.win.user.ClientToScreen(hwnd, ctypes.byref(point)):
            raise RuntimeError('Unable to read native client geometry.')
        if rect.right <= 0 or rect.bottom <= 0:
            raise RuntimeError('Target has no visible client area.')
        return (point.x, point.y, point.x + rect.right, point.y + rect.bottom)

    def foreground(self, hwnd=None):
        hwnd = self.validate(hwnd)
        self.win.user.ShowWindow(hwnd, 9)  # Restore only this explicit app window.
        self.win.user.SetForegroundWindow(hwnd)
        if self.win.pid(self.win.user.GetForegroundWindow()) != self.pid:
            # Windows can deny focus to an automation process with no recent
            # input. Briefly share its queue with the foreground thread; do not
            # synthesize global mouse/key input or send messages to other apps.
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentThreadId.restype = W.DWORD
            current = kernel.GetCurrentThreadId()
            foreground_thread = self.win.user.GetWindowThreadProcessId(self.win.user.GetForegroundWindow(), None)
            attached = current != foreground_thread and self.win.user.AttachThreadInput(current, foreground_thread, True)
            try:
                self.win.user.SetForegroundWindow(hwnd)
            finally:
                if attached: self.win.user.AttachThreadInput(current, foreground_thread, False)
        time.sleep(.15)
        if self.win.pid(self.win.user.GetForegroundWindow()) != self.pid:
            raise RuntimeError('Windows did not focus E-musician; capture stopped instead of operating another app.')

    def resize(self, width=1600, height=950, x=0, y=0):
        self.validate()
        if not 800 <= width <= 7680 or not 600 <= height <= 4320:
            raise ValueError('Unsupported capture window dimensions.')
        self.foreground()
        if not self.win.user.SetWindowPos(self.hwnd, None, x, y, width, height, 0x0004):
            raise RuntimeError('Could not position the DAW window.')
        time.sleep(.3)
        self.log('resize', bounds=self.bounds())

    def open_project(self, path):
        if self.client is None:
            raise RuntimeError('Opening projects requires the owned stdio Client.')
        path = Path(path).resolve()
        if not path.is_relative_to(self.project_root) or not path.is_file() or path.suffix.lower() != '.emproj':
            raise ValueError('Capture opens staged .emproj copies only; do not point it at an original user project.')
        response = self.client.request({'command': 'open_project', 'args': {'path': str(path)}})
        self.log('open_project', path=str(path), status=response['status'])
        return response

    def command(self, name, args=None, wait=True):
        if self.client is None:
            raise RuntimeError('Native control command requires the owned stdio Client.')
        result = self.client.request({'command': name, 'args': args or {}}, wait=wait)
        # Do not copy API keys, provider configuration, or a complete project into receipts.
        self.log('native_command', command=name, status=result['status'])
        return result

    def controls(self):
        """Read actual JUCE accessibility controls under this owned HWND."""
        return self._uia('inspect')

    def invoke(self, name, index=0):
        """Invoke an observed native accessibility control, without global input."""
        result = self._uia('invoke', name=name, index=index)
        self.log('native_invoke', name=name, index=index, result=result)
        time.sleep(.15)
        return result

    def invoke_menu(self, button, item):
        """Invoke an observed app menu item in the same UIA client lifetime."""
        self.foreground()
        result = self._uia('menu', name=button, item=item, index=0)
        self.log('native_menu_invoke', button=button, item=item, result=result)
        time.sleep(.2)
        return result

    def _uia(self, action, **values):
        self.validate()
        payload = base64.b64encode(json.dumps({'hwnd':self.hwnd,'pid':self.pid,'action':action,**values}).encode()).decode()
        script = """
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD'))|ConvertFrom-Json
$root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$request.hwnd)
if($root.Current.ProcessId -ne $request.pid){throw 'UIA process ownership changed'}
$elements=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
if($request.action -eq 'inspect') {
 $result=@($elements|Where-Object {-not $_.Current.IsOffscreen}|ForEach-Object {
  $r=$_.Current.BoundingRectangle
  [PSCustomObject]@{name=$_.Current.Name;type=$_.Current.ControlType.ProgrammaticName;enabled=$_.Current.IsEnabled;x=$r.X;y=$r.Y;width=$r.Width;height=$r.Height}
 })
 $result|ConvertTo-Json -Compress
} else {
 $matches=@($elements|Where-Object {$_.Current.Name -ceq $request.name -and -not $_.Current.IsOffscreen -and $_.Current.IsEnabled})
 if($request.action -eq 'combo_menu') {$matches=@($elements|Where-Object {$_.Current.ControlType -eq [System.Windows.Automation.ControlType]::ComboBox -and $_.Current.ProcessId -eq $request.pid -and -not $_.Current.IsOffscreen -and $_.Current.IsEnabled})}
 if($request.index -lt 0 -or $request.index -ge $matches.Count){throw 'Observed enabled native control not found'}
 $target=$matches[$request.index]
 if($target.Current.ProcessId -ne $request.pid){throw 'Native control belongs to a different process'}
 $targetName=$target.Current.Name
 $pattern=$null
 if($target.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)) {$pattern.Invoke()}
 elseif($target.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$pattern)) {$pattern.Toggle()}
 elseif($target.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$pattern)) {$pattern.Expand()}
 else {throw 'Control has no native Invoke/Toggle pattern'}
 if($request.action -eq 'menu' -or $request.action -eq 'combo_menu') {
  $owned=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$request.pid)
  $name=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,[string]$request.item)
  $deadline=[DateTime]::UtcNow.AddSeconds(3)
  $item=$null
  do {
   $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$owned)
   foreach($window in $windows) {
    try {$item=$window.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$name)} catch {$item=$null}
    if($item -and $item.Current.IsEnabled -and -not $item.Current.IsOffscreen){break}
    $item=$null
   }
   if(-not $item){Start-Sleep -Milliseconds 30}
  } while(-not $item -and [DateTime]::UtcNow -lt $deadline)
  if(-not $item){throw 'Observed enabled native menu item not found'}
  $pattern=$item.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $pattern.Invoke()
 }
 [PSCustomObject]@{name=$targetName;invoked=$true}|ConvertTo-Json -Compress
}
""".replace('PAYLOAD', payload)
        powershell = Path(os.environ.get('SystemRoot','C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-Command',script], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('Native accessibility operation failed: '+result.stderr.strip()[-800:])
        return json.loads(result.stdout.lstrip('\ufeff'))

    def click(self, x, y, *, double=False, hwnd=None):
        """Send a real mouse gesture at a previously inspected client coordinate."""
        hwnd = self.validate(hwnd)
        self.foreground(hwnd)
        left, top, right, bottom = self.bounds(hwnd)
        if not (0 <= x < right-left and 0 <= y < bottom-top):
            raise ValueError('Click is outside the captured native client area.')
        screen = W.POINT(left + int(x), top + int(y))
        under = self.win.user.WindowFromPoint(screen)
        root = self.win.user.GetAncestor(under, 2)
        if root != hwnd:
            raise RuntimeError('Target coordinate is covered by another window; no click sent.')
        # JUCE controls share one HWND; WebView child surfaces have their own HWND.
        # Only route down the explicitly owned app hierarchy, never by global title.
        target = hwnd
        while True:
            local = W.POINT(screen.x, screen.y)
            self.win.user.ScreenToClient(target, ctypes.byref(local))
            child = self.win.user.ChildWindowFromPointEx(target, local, 0x0001 | 0x0002 | 0x0004)
            if not child or child == target:
                break
            target = child
        point = W.POINT(screen.x, screen.y)
        self.win.user.ScreenToClient(target, ctypes.byref(point))
        location = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
        self.win.send(target, 0x0200, 0, location)
        self.win.send(target, 0x0201, 1, location)
        self.win.send(target, 0x0202, 0, location)
        if double:
            # JUCE counts its own consecutive press/release events and ignores
            # WM_LBUTTONDBLCLK in this pinned Windows backend.
            self.win.send(target, 0x0201, 1, location)
            self.win.send(target, 0x0202, 0, location)
        time.sleep(.15)
        self.log('double_click' if double else 'click', x=x, y=y, hwnd=hwnd)

    def _grab(self, hwnd=None):
        hwnd = self.validate(hwnd)
        box = self.bounds(hwnd)
        # Stop if another application stole foreground. Captures are restricted
        # to the selected client rectangle, never the full desktop.
        if self.win.pid(self.win.user.GetForegroundWindow()) != self.pid:
            raise RuntimeError('Another app is foreground; refusing unrelated desktop capture.')
        for fx, fy in ((.1,.1),(.5,.1),(.9,.1),(.1,.5),(.5,.5),(.9,.5),(.1,.9),(.5,.9),(.9,.9)):
            point = W.POINT(round(box[0]+(box[2]-box[0])*fx), round(box[1]+(box[3]-box[1])*fy))
            surface = self.win.user.WindowFromPoint(point)
            root = self.win.user.GetAncestor(surface, 2)
            if self.win.pid(root) != self.pid:
                raise RuntimeError('Captured app rectangle is obscured by another application.')
        return ImageGrab.grab(bbox=box, all_screens=True).convert('RGB')

    def screenshot(self, name, *, hwnd=None):
        path = self._destination(name, '.png')
        self.foreground(hwnd)
        image = self._grab(hwnd)
        image.save(path)
        self.log('screenshot', path=str(path), size=list(image.size), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                 source='actual-native-window', window_title=self.win.title(hwnd or self.hwnd))
        self.flush()
        return path

    def _destination(self, name, suffix):
        if not name or Path(name).name != name or name in ('.','..'):
            raise ValueError('Capture names must be a single safe filename stem.')
        path = self.output / (name + suffix)
        if path.exists():
            raise FileExistsError(f'Refusing to replace prior capture: {path}')
        return path

    def record(self, name, *, seconds, ffmpeg, fps=15, hwnd=None):
        """Encode fresh native-window frames. No audio device capture is performed."""
        if not 0 < seconds <= 60 or not 1 <= fps <= 60:
            raise ValueError('Record at most 60 seconds per clip, at 1–60 fps.')
        path = self._destination(name, '.mp4')
        self.foreground(hwnd)
        first = self._grab(hwnd)
        width, height = first.size
        log = path.with_suffix('.ffmpeg.log')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        stamps = []
        count = round(seconds * fps)
        started = time.monotonic()
        with log.open('wb') as stderr:
            process = subprocess.Popen([str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-n',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps), '-i', '-',
                '-an', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264', '-preset', 'veryfast',
                '-crf', '19', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)],
                stdin=subprocess.PIPE, stderr=stderr, stdout=subprocess.DEVNULL, creationflags=flags)
            try:
                for index in range(count):
                    time.sleep(max(0, started + index/fps - time.monotonic()))
                    if self.win.pid(self.win.user.GetForegroundWindow()) != self.pid:
                        # A separately launched local helper can briefly take
                        # foreground. Reacquire only this explicitly owned
                        # workspace, then keep the full occlusion checks below.
                        self.foreground(hwnd)
                        time.sleep(.03)
                    frame = first if index == 0 else self._grab(hwnd)
                    if frame.size != (width, height):
                        raise RuntimeError('Window dimensions changed during recording.')
                    stamps.append(time.monotonic() - started)
                    process.stdin.write(frame.tobytes())
                process.stdin.close()
                if process.wait(timeout=30):
                    raise RuntimeError(f'Video encoder failed; see {log}')
            except BaseException:
                process.terminate()
                process.wait(timeout=5)
                self.log('capture_failed', path=str(path), captured_frames=len(stamps))
                self.flush()
                raise
        elapsed = time.monotonic() - started
        self.log('video', path=str(path), size=[width,height], frames=count, requested_fps=fps,
                 capture_elapsed_seconds=elapsed, frame_times_seconds=stamps, audio=False,
                 source='actual-native-window', sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.flush()
        return path

    def flush(self):
        receipt = {'schema_version':1, 'started_utc':self.started, 'updated_utc':utc(), 'pid':self.pid,
                   'capture_kind':'real-window-pixels', 'inference_evidence':False,
                   'microphone_capture':False, 'events':self.events}
        encoded = json.dumps(receipt, ensure_ascii=False, indent=2)+'\n'
        self.receipt_path.write_text(encoded, encoding='utf-8')
        (self.output/'capture-receipt.json').write_text(encoded, encoding='utf-8')

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error:
            self.log('error', type=kind.__name__, message=str(error))
        self.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--exe', type=Path, help='Launch an owned --control-stdio --show process.')
    source.add_argument('--pid', type=int, help='Capture only the explicitly identified existing DAW.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path, help='Staged copy under captures/projects only.')
    parser.add_argument('--recipe', type=Path, help='JSON actions: screenshot, invoke, menu, click, double_click, wait, command, record.')
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--offline-test', action='store_true', help='Use the isolated native offline test mode; do not open user audio hardware.')
    parser.add_argument('--webview-port', type=int, help='Enable CDP on the owned child only (e.g. 9229) for the embedded Agent DOM.')
    parser.add_argument('--name', default='workspace')
    args = parser.parse_args()
    if args.webview_port and (not args.exe or not 1024 <= args.webview_port <= 65535):
        parser.error('--webview-port requires --exe and a port from 1024 to 65535.')
    old_webview = os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS')
    try:
        if args.webview_port:
            os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--remote-debugging-port=' + str(args.webview_port)
        client = Client(args.exe, show=True, offline_test=args.offline_test) if args.exe else None
    finally:
        if old_webview is None: os.environ.pop('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', None)
        else: os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = old_webview
    try:
        with CaptureSession(client=client, pid=args.pid, output=args.output) as capture:
            if args.project:
                capture.open_project(args.project)
                time.sleep(1)
            if not args.recipe:
                capture.screenshot(args.name)
            else:
                recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
                for action in recipe:
                    kind = action['action']
                    if kind == 'screenshot': capture.screenshot(action['name'])
                    elif kind in ('click','double_click'): capture.click(action['x'], action['y'], double=kind=='double_click')
                    elif kind == 'wait': time.sleep(min(10, max(0, float(action['seconds']))))
                    elif kind == 'command': capture.command(action['command'], action.get('args'), action.get('wait',True))
                    elif kind == 'record':
                        if not args.ffmpeg: raise ValueError('record actions require --ffmpeg.')
                        capture.record(action['name'], seconds=action['seconds'], ffmpeg=args.ffmpeg, fps=action.get('fps',15))
                    elif kind == 'resize': capture.resize(action.get('width',1600),action.get('height',950))
                    elif kind == 'invoke': capture.invoke(action['name'],action.get('index',0))
                    elif kind == 'menu': capture.invoke_menu(action['button'],action['item'])
                    elif kind == 'combo_menu':
                        result=capture._uia('combo_menu', name='', index=action['index'], item=action['item'])
                        capture.log('combo_menu', index=action['index'], item=action['item'], result=result)
                    else: raise ValueError('Unknown capture action: '+kind)
    finally:
        if client: client.close()


if __name__ == '__main__':
    main()
