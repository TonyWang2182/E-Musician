"""Read-only native backup progress window; closing it never stops the transfer."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from backup_progress import BackupProgress

PAPER = "#FEFEFD"
PANEL = "#F1F2EE"
INK = "#171817"
SECONDARY = "#626560"
RULE = "#C6C9C3"
FOCUS = "#527D7A"
ERROR = "#A33229"


def gb(value):
    return f"{max(0, value or 0) / 1_000_000_000:,.2f} GB"


def duration(value):
    if value is None:
        return "正在估算"
    minutes = max(1, round(value / 60))
    hours, minutes = divmod(minutes, 60)
    return f"约 {hours} 小时 {minutes} 分钟" if hours else f"约 {minutes} 分钟"


class MonitorWindow:
    def __init__(self, root: tk.Tk, backup_dir: Path):
        self.root = root
        self.backup_dir = backup_dir.resolve()
        self.model = BackupProgress(self.backup_dir)
        self.snapshot = {}
        self.render_count = 0
        self.stop_event = threading.Event()
        self.updates = queue.Queue(maxsize=1)
        self.labels = {}
        self.root.title("备份进度 · E-musician")
        self.root.configure(bg=PAPER)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        self.dpi_scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.root.geometry(f"{round(720*self.dpi_scale)}x{round(570*self.dpi_scale)}")
        self.root.minsize(round(640*self.dpi_scale), round(530*self.dpi_scale))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _event: self.close())
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Backup.Horizontal.TProgressbar", troughcolor=PANEL,
                        background=FOCUS, bordercolor=RULE, lightcolor=FOCUS,
                        darkcolor=FOCUS, thickness=15)
        style.configure("Verified.Horizontal.TProgressbar", troughcolor=PANEL,
                        background=SECONDARY, bordercolor=RULE,
                        lightcolor=SECONDARY, darkcolor=SECONDARY, thickness=6)
        style.configure("Backup.TButton", font=("Microsoft YaHei UI", 10),
                        background=PANEL, foreground=INK, padding=(12, 8))
        style.map("Backup.TButton", background=[("active", "#E3E9E5")])

        self.body = tk.Frame(root, bg=PAPER, padx=28, pady=22)
        self.body.pack(fill="both", expand=True)
        header = tk.Frame(self.body, bg=PAPER)
        header.pack(fill="x")
        self._label(header, "heading", "云端备份", size=18, bold=True).pack(side="left")
        self.topmost = tk.BooleanVar(value=False)
        tk.Checkbutton(header, text="保持置顶", variable=self.topmost,
                       command=lambda: root.attributes("-topmost", self.topmost.get()),
                       bg=PAPER, fg=SECONDARY, activebackground=PAPER,
                       selectcolor=PAPER, highlightthickness=1,
                       highlightbackground=PAPER, highlightcolor=FOCUS).pack(side="right")
        self._label(self.body, "status", "正在读取备份进度…", color=FOCUS).pack(
            anchor="w", pady=(7, 22))
        row = tk.Frame(self.body, bg=PAPER)
        row.pack(fill="x")
        self._label(row, "download_heading", "下载到 E 盘", size=12).pack(side="left", anchor="s")
        self._label(row, "percentage", "—", size=27, mono=True).pack(side="right")
        self.download_bar = ttk.Progressbar(self.body, style="Backup.Horizontal.TProgressbar",
                                            maximum=100)
        self.download_bar.pack(fill="x", pady=(6, 9))
        row = tk.Frame(self.body, bg=PAPER)
        row.pack(fill="x")
        self._label(row, "amount", "等待总量信息", mono=True).pack(side="left")
        self._label(row, "remaining", "", color=SECONDARY).pack(side="right")

        self._label(self.body, "verified", "等待校验信息", color=SECONDARY).pack(
            anchor="w", pady=(23, 6))
        self.verified_bar = ttk.Progressbar(self.body, style="Verified.Horizontal.TProgressbar",
                                            maximum=100)
        self.verified_bar.pack(fill="x")

        self.metrics = tk.Frame(self.body, bg=PAPER)
        self.metrics.pack(fill="x", pady=(24, 18))
        self.metrics.columnconfigure(0, weight=1)
        self.metrics.columnconfigure(1, weight=1)
        self._label(self.metrics, "speed_heading", "近一分钟速度", color=SECONDARY).grid(
            row=0, column=0, sticky="w")
        self._label(self.metrics, "eta_heading", "预计剩余（随网速变化）", color=SECONDARY).grid(
            row=0, column=1, sticky="w")
        self._label(self.metrics, "speed", "采样中…", size=13, mono=True).grid(
            row=1, column=0, sticky="w", pady=(7, 0))
        self._label(self.metrics, "eta", "正在估算", size=12).grid(
            row=1, column=1, sticky="w", pady=(7, 0))
        self._label(self.body, "detail", "仅查看进度，备份在独立后台运行。",
                    color=SECONDARY).pack(anchor="w", fill="x", pady=(0, 14))

        tk.Frame(self.body, height=1, bg=RULE).pack(fill="x")
        self._label(self.body, "destination_heading", "保存位置", color=SECONDARY).pack(
            anchor="w", pady=(14, 5))
        self.destination = tk.Entry(self.body, readonlybackground=PAPER, relief="flat",
                                    fg=SECONDARY, bd=0, highlightthickness=0,
                                    font=("Consolas", 9))
        self.destination.insert(0, str(self.backup_dir))
        self.destination.configure(state="readonly")
        self.destination.pack(fill="x")

        footer = tk.Frame(self.body, bg=PAPER)
        footer.pack(side="bottom", fill="x", pady=(16, 0))
        self._label(footer, "updated", "每 2 秒自动刷新 · 关闭窗口不停止备份",
                    size=9, color=SECONDARY).pack(anchor="w", pady=(0, 12))
        actions = tk.Frame(footer, bg=PAPER)
        actions.pack(fill="x")
        ttk.Button(actions, text="打开备份文件夹", style="Backup.TButton",
                   command=self.open_folder).pack(side="left")
        ttk.Button(actions, text="复制进度", style="Backup.TButton",
                   command=self.copy_summary).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="关闭窗口", style="Backup.TButton",
                   command=self.close).pack(side="right")
        self.root.bind("<Configure>", self._wrap)
        self._set_icon()
        threading.Thread(target=self._read_loop, name="backup-progress-reader", daemon=True).start()
        self.root.after(100, self._drain)

    def _label(self, parent, key, text, *, size=10, color=INK, bold=False, mono=False):
        label = tk.Label(parent, text=text, bg=PAPER, fg=color, anchor="w", justify="left",
                         font=("Consolas" if mono else "Microsoft YaHei UI", size,
                               "bold" if bold else "normal"), bd=0)
        self.labels[key] = label
        return label

    def _set_icon(self):
        candidates = [Path(__file__).with_name("yi-yue-shi-logo.png"),
                      Path(__file__).resolve().parents[2] / "assets/brand/yi-yue-shi-logo.png"]
        for candidate in candidates:
            if candidate.is_file():
                try:
                    icon = tk.PhotoImage(file=str(candidate))
                    self.icon = icon.subsample(max(1, icon.width() // 48))
                    self.root.iconphoto(True, self.icon)
                except tk.TclError:
                    pass
                break

    def _wrap(self, event):
        if event.widget is self.root:
            self.labels["detail"].configure(wraplength=max(540, event.width - 64))

    def _read_loop(self):
        while not self.stop_event.is_set():
            try:
                snapshot = self.model.poll()
            except Exception as error:
                snapshot = dict(self.snapshot, status_text="暂时无法读取进度",
                                error=str(error), detail_text="稍后自动重试；不会停止后台备份。")
            try:
                self.updates.put_nowait(snapshot)
            except queue.Full:
                try:
                    self.updates.get_nowait()
                except queue.Empty:
                    pass
                self.updates.put_nowait(snapshot)
            self.stop_event.wait(2)

    def _drain(self):
        try:
            snapshot = self.updates.get_nowait()
        except queue.Empty:
            pass
        else:
            self.render(snapshot)
        if not self.stop_event.is_set():
            self.root.after(200, self._drain)

    def render(self, snapshot):
        self.snapshot = snapshot
        self.render_count += 1
        total = snapshot.get("total_bytes") or 0
        percentage = snapshot.get("download_percent") or 0
        completed = snapshot.get("completed", False)
        known = total > 0
        percent_text = f"{percentage:.2f}%" if known else "—"
        self.root.title(f"{percent_text} · {'备份完成' if completed else '备份进度'} · E-musician")
        self.labels["percentage"].configure(text=percent_text)
        self.labels["status"].configure(text=snapshot.get("status_text", "读取中…"),
            fg=ERROR if snapshot.get("error") or snapshot.get("stale") else FOCUS)
        self.download_bar["value"] = percentage
        self.labels["amount"].configure(text=(
            f"{gb(snapshot.get('downloaded_bytes'))} / {gb(total)}" if known else "等待总量信息"))
        self.labels["remaining"].configure(text=f"剩余 {gb(snapshot.get('remaining_bytes'))}" if known else "")
        verified = snapshot.get("verified_bytes") or 0
        self.verified_bar["value"] = verified / total * 100 if total else 0
        self.labels["verified"].configure(text=(
            "全量完整性校验通过 · 尚未进行异机恢复测试" if completed else
            f"已通过分块校验 {gb(verified)} · {snapshot.get('parts_verified', 0)} / "
            f"{snapshot.get('parts_total', 0)} 块"))
        speed = snapshot.get("speed_bps")
        phase = snapshot.get("phase")
        if phase == "verifying" and not completed:
            verification = snapshot.get("verification_percent") or 0
            self.verified_bar["value"] = verification
            self.labels["verified"].configure(text=(
                f"全量校验 {verification:.2f}% · 已检查 {snapshot.get('members_verified', 0):,} / "
                f"{snapshot.get('members_total', 0):,} 个成员"))
        self.labels["speed"].configure(text=(
            "—" if completed or phase != "pulling" else
            f"{speed / 1_000_000:.2f} MB/s" if speed is not None else "采样中…"))
        eta = "已完成" if completed else duration(snapshot.get("eta_seconds"))
        if snapshot.get("stale") or snapshot.get("error"):
            eta = "暂无法估算"
        elif known and percentage >= 100 and not completed:
            eta = "等待全量校验结束"
        self.labels["eta"].configure(text=eta)
        detail = snapshot.get("warning") or snapshot.get("detail_text") or ""
        if snapshot.get("error") and str(snapshot["error"]) not in detail:
            detail = f"{detail}\n{str(snapshot['error'])[:180]}".strip()
        self.labels["detail"].configure(text=detail, fg=ERROR if snapshot.get("error") else SECONDARY)
        self.labels["updated"].configure(text=(
            f"进度更新：{snapshot.get('updated_local') or '未知'} · 关闭窗口不停止备份"))

    def copy_summary(self):
        text = "\n".join(self.labels[key].cget("text") for key in
                         ("status", "percentage", "amount", "remaining", "verified", "speed", "eta", "updated"))
        self.root.clipboard_clear()
        self.root.clipboard_append(text + "\n" + str(self.backup_dir))

    def open_folder(self):
        if self.backup_dir.is_dir():
            os.startfile(str(self.backup_dir))
        else:
            messagebox.showerror("备份目录不存在", str(self.backup_dir), parent=self.root)

    def close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--status-json", action="store_true", help="Read one snapshot without opening a window")
    args = parser.parse_args()
    if args.status_json:
        print(json.dumps(BackupProgress(args.backup_dir).poll(), ensure_ascii=False, indent=2))
        return 0
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    MonitorWindow(root, args.backup_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
