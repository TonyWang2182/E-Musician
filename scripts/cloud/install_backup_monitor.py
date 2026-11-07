"""Install a self-contained copy of the read-only monitor beside an existing backup."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--shortcut-dir", type=Path, action="append", default=[])
    args = parser.parse_args()
    destination = args.backup_dir.resolve()
    source = Path(__file__).resolve().parent
    if not (destination / "source.json").is_file():
        parser.error("An existing backup source.json is required")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        parser.error("The Windows Python installation must include pythonw.exe and Tk")
    target = destination / "tools"
    target.mkdir(exist_ok=True)
    records = []
    for name in ("backup_monitor.py", "backup_progress.py"):
        shutil.copy2(source / name, target / name)
        records.append({"file": f"tools/{name}", "sha256": hashlib.sha256((target / name).read_bytes()).hexdigest()})
    logo = source.parents[1] / "assets/brand/yi-yue-shi-logo.png"
    if logo.is_file():
        shutil.copy2(logo, target / logo.name)
    # UTF-8 command text after an ASCII code-page switch also permits non-ASCII directories.
    script = ("@echo off\nchcp 65001 >nul\nsetlocal\n"
              f'if not exist "{pythonw}" (\n'
              " echo Python is missing. Install Python with Tcl/Tk to open this monitor.\n pause\n exit /b 1\n)\n"
              f'start "" "{pythonw}" "%~dp0tools\\backup_monitor.py" --backup-dir "%~dp0."\n'
              "exit /b 0\n")
    launcher = destination / "Check Backup.cmd"
    launcher.write_text(script, encoding="utf-8", newline="\r\n")
    shortcuts = []
    for directory in args.shortcut_dir:
        directory = directory.resolve()
        if not directory.is_dir():
            parser.error(f"Shortcut directory does not exist: {directory}")
        shortcut = directory / "查看备份进度.cmd"
        shortcut.write_text(f'@echo off\nchcp 65001 >nul\ncall "{launcher}"\n', encoding="utf-8", newline="\r\n")
        shortcuts.append(str(shortcut))
    report = {"schema": 1, "installed_utc": datetime.now(timezone.utc).isoformat(),
              "backup_dir": str(destination), "python": str(pythonw), "files": records,
              "launcher": str(launcher), "shortcuts": shortcuts,
              "mode": "read-only; does not manage downloader"}
    (destination / "monitor-install.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
