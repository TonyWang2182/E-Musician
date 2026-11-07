"""Native smoke test: render only our window, collect fresh readings, then close it."""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys
import time
import tkinter as tk
import zlib

def capture_client(root, destination):
    """PrintWindow targets this test's own Tk HWND; no desktop capture or UI control."""
    user = ctypes.windll.user32
    gdi = ctypes.windll.gdi32
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    hwnd = user.GetParent(root.winfo_id())
    width, height = root.winfo_width(), root.winfo_height()
    screen = user.GetDC(hwnd)
    dc = gdi.CreateCompatibleDC(screen)
    bitmap = gdi.CreateCompatibleBitmap(screen, width, height)
    previous = gdi.SelectObject(dc, bitmap)
    try:
        if not user.PrintWindow(hwnd, dc, 3):
            raise RuntimeError("PrintWindow failed")
        gdi.SelectObject(dc, previous)
        header = ctypes.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height,
                                                       1, 32, 0, width*height*4, 0, 0, 0, 0))
        pixels = ctypes.create_string_buffer(width*height*4)
        if gdi.GetDIBits(screen, bitmap, 0, height, pixels, header, 0) != height:
            raise RuntimeError("GetDIBits failed")
        raw = pixels.raw
        scanlines = bytearray()
        for y in range(height):
            scanlines.append(0)
            row = raw[y*width*4:(y+1)*width*4]
            rgb = bytearray(width*3)
            rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
            scanlines.extend(rgb)
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data))
        destination.write_bytes(b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(dc)
        user.ReleaseDC(hwnd, screen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--module-dir", type=Path, help="Exercise the installed copy rather than the worktree")
    args = parser.parse_args()
    if args.module_dir:
        sys.path.insert(0, str(args.module_dir.resolve()))
    from backup_monitor import MonitorWindow
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    window = MonitorWindow(root, args.backup_dir)
    started = time.perf_counter()
    result = {"started_utc": datetime.now(timezone.utc).isoformat(), "snapshots": [], "errors": []}
    def callback_error(kind, value, tb):
        result["errors"].append(f"{kind.__name__}: {value}")
    root.report_callback_exception = callback_error

    def check_layout(name):
        root.update()
        outside = []
        top = root.winfo_rooty()
        bottom = top + root.winfo_height()
        for key, label in window.labels.items():
            if label.winfo_rooty() < top or label.winfo_rooty()+label.winfo_height() > bottom:
                outside.append(key)
        if outside:
            result["errors"].append(f"{name} labels outside client: {outside}")
        capture_client(root, args.output_dir / f"{name}.png")

    def sample():
        if window.snapshot:
            result["snapshots"].append(dict(window.snapshot))

    def compact():
        check_layout("default")
        root.geometry(f"{round(640*window.dpi_scale)}x{round(530*window.dpi_scale)}")

    def finish():
        sample()
        check_layout("compact")
        result.update(render_count=window.render_count, dpi_scale=window.dpi_scale,
                      elapsed_seconds=round(time.perf_counter()-started, 3),
                      finished_utc=datetime.now(timezone.utc).isoformat())
        if window.render_count < 5:
            result["errors"].append("Fewer than five UI updates")
        if not window.snapshot.get("total_bytes"):
            result["errors"].append("No real receipt total")
        window.copy_summary()
        if "GB" not in root.clipboard_get():
            result["errors"].append("Copy summary failed")
        original = dict(window.snapshot)
        for phase in ("verifying", "failed"):
            fixture = dict(original, phase=phase, completed=False,
                           verification_percent=42.5, members_verified=132188,
                           status_text="界面测试：全量校验" if phase == "verifying" else "界面测试：传输失败",
                           detail_text="模拟状态，仅用于检查排版；实际下载继续运行。",
                           error=None if phase == "verifying" else "Connection interrupted. Run Resume Backup.cmd to continue.")
            if phase == "verifying":
                fixture.update(download_percent=100, downloaded_bytes=original["total_bytes"],
                               remaining_bytes=0, verified_bytes=original["total_bytes"],
                               parts_verified=original["parts_total"])
            window.render(fixture)
            check_layout(phase + "-fixture")
        window.close()

    root.after(3000, sample)
    root.after(6000, compact)
    root.after(16000, finish)
    root.mainloop()
    result["status"] = "passed" if not result["errors"] else "failed"
    (args.output_dir / "native-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "snapshots"}, ensure_ascii=False))
    return int(bool(result["errors"]))


if __name__ == "__main__":
    sys.exit(main())
