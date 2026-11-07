"""Read small backup metadata files for a local, strictly read-only monitor.

The download percentage covers archive parts, excluding metadata sidecars. A
100% download never substitutes for the separate full-stream verifier report.
No archive/partial files are opened, sized or hashed by this module.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re


MAX_METADATA_BYTES = 4 * 1024 * 1024
STALE_SECONDS = 90
SPEED_WINDOW_SECONDS = 60
MIN_SPEED_SECONDS = 10


def _integer(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except ValueError:
        return None


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate property")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("non-finite number")


def _identity(value):
    return (value.get("host"), value.get("remote_root")) if value else None


def _receipt(value):
    """Return totals plus a small comparison identity, without opening parts."""
    if not value:
        return {"total": 0, "parts": 0, "members": 0, "full": False, "key": None}
    summary = value.get("summary", {})
    summary = summary if isinstance(summary, dict) else {}
    counts = summary.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    members = sum(counts.values()) if all(_integer(v) for v in counts.values()) else 0
    parts = value.get("parts")
    full = isinstance(parts, list) and bool(parts) and all(
        isinstance(part, dict) and part.get("name") == f"part-{i:06d}.tarpart"
        and _integer(part.get("size")) and part["size"] > 0
        and isinstance(part.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
        for i, part in enumerate(parts))
    total = sum(part["size"] for part in parts) if full else summary.get("archive_bytes", 0)
    total = total if _integer(total) else 0
    count = len(parts) if isinstance(parts, list) else summary.get("parts", summary.get("part_count", 0))
    count = count if _integer(count) else 0
    manifest = value.get("manifest")
    valid_manifest = (isinstance(manifest, dict) and manifest.get("name") == "manifest.jsonl"
                      and _integer(manifest.get("size")) and manifest["size"] > 0
                      and isinstance(manifest.get("sha256"), str)
                      and re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]))
    consistent = "archive_bytes" not in summary or summary["archive_bytes"] == total
    key = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return {"total": total, "parts": count, "members": members,
            "full": bool(full and valid_manifest and consistent), "key": key}


class BackupProgress:
    """Poll only five named JSON files; retain the last readable metadata.

    ``verified_bytes``/``parts_verified`` represent individual part hashes.
    ``archive_bytes_read``/``members_verified`` are full-verifier callbacks.
    Speed and ETA describe archive download only, over 10–60 seconds of local
    observations; they reset on retries, restarts and counter regressions.
    """

    def __init__(self, backup_dir: Path):
        self.backup_dir = Path(backup_dir)
        self._good = {}
        self._samples = deque()
        self._speed_key = None
        self._attempts = {}
        self._last_progress_date = None
        self._source_identity = None
        self._source_changed_at = None

    def _read(self, name, warnings, *, required=False):
        try:
            with (self.backup_dir / name).open("rb") as stream:
                raw = stream.read(MAX_METADATA_BYTES + 1)
            if len(raw) > MAX_METADATA_BYTES:
                raise ValueError("metadata exceeds limit")
            value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
            if not isinstance(value, dict) or value.get("schema") != 2:
                raise ValueError("unsupported metadata schema")
            if name == "progress.json":
                if not isinstance(value.get("phase"), str):
                    raise ValueError("missing phase")
                for key in ("bytes_verified", "parts_verified", "current_part_bytes",
                            "archive_bytes_read", "members_verified"):
                    if key in value and not _integer(value[key]):
                        raise ValueError("invalid counter")
            if name == "source.json" and not all(
                    isinstance(value.get(key), str) and value[key] for key in ("host", "remote_root")):
                raise ValueError("invalid source identity")
            if name in ("receipt.json", "receipt.remote.json") and not _receipt(value)["total"]:
                raise ValueError("missing archive total")
            self._good[name] = value
            return value, True
        except FileNotFoundError:
            if required or name in self._good:
                warnings.append(f"{name} 暂不可用；保留最近有效数据" if name in self._good
                                else f"等待 {name}")
        except (OSError, ValueError, UnicodeError, RecursionError):
            warnings.append(f"{name} 暂不可读；保留最近有效数据" if name in self._good
                            else f"{name} 暂不可读，等待有效数据")
        return self._good.get(name), False

    @staticmethod
    def _embedded_identity_matches(value, source):
        embedded = value.get("source", {})
        if embedded is not None and not isinstance(embedded, dict):
            return False
        for container in (value, embedded or {}):
            for key in ("host", "remote_root"):
                if key in container and container[key] != source.get(key):
                    return False
        return True

    def _verified(self, report, receipt, info, source, progress, conflict):
        if not report or report.get("phase") != "verified":
            return False
        if not source or not receipt or not info["full"] or conflict:
            return False
        if any(report.get(key) is not True for key in (
                "part_hashes_verified", "member_hashes_verified", "metadata_verified", "tar_padding_verified")):
            return False
        if (type(report.get("parts")) is not int or report["parts"] != info["parts"]
                or type(report.get("archive_bytes")) is not int or report["archive_bytes"] != info["total"]):
            return False
        if not isinstance(report.get("raw_tar_sha256"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", report["raw_tar_sha256"]):
            return False
        summary = receipt.get("summary", {})
        summary = summary if isinstance(summary, dict) else {}
        counts = summary.get("counts")
        if counts is not None and (report.get("members") != counts
                                   or report.get("member_count") != info["members"]):
            return False
        if not _integer(report.get("member_count")) or not _integer(report.get("content_bytes")):
            return False
        metadata = receipt.get("metadata", {})
        if not isinstance(metadata, dict):
            return False
        sidecars = report.get("sidecars_verified")
        if (not isinstance(sidecars, list) or not all(isinstance(item, str) for item in sidecars)
                or sorted(sidecars) != sorted(name for name in metadata if name != "manifest.jsonl")):
            return False
        for value in (report, receipt):
            if not self._embedded_identity_matches(value, source):
                return False
            if "raw_tar_sha256" in value and value["raw_tar_sha256"] != report["raw_tar_sha256"]:
                return False
        root = summary.get("source_root")
        if root is not None and (not isinstance(root, str)
                or not source["remote_root"].startswith(root.rstrip("/") + "/exports/")):
            return False
        verified = _date(report.get("verified_utc"))
        if verified is None:
            return False
        for lower_bound in (_date(progress.get("started_utc")), self._source_changed_at):
            if lower_bound is not None and verified < lower_bound:
                return False
        finished = summary.get("finished_unix")
        if type(finished) in (int, float) and verified.timestamp() < finished:
            return False
        return True

    def _speed(self, now, downloaded, key, attempts, updated, enabled):
        retry = any(name in self._attempts and attempt != self._attempts[name]
                    for name, attempt in attempts.items())
        reset = (key != self._speed_key or retry
                 or (updated and self._last_progress_date and updated < self._last_progress_date)
                 or (self._samples and (downloaded < self._samples[-1][1] or now <= self._samples[-1][0])))
        if reset or not enabled:
            self._samples.clear()
        self._speed_key, self._attempts = key, attempts
        self._last_progress_date = updated
        if not enabled:
            return None
        self._samples.append((now, downloaded))
        while len(self._samples) > 1 and (now - self._samples[0][0]).total_seconds() > SPEED_WINDOW_SECONDS:
            self._samples.popleft()
        elapsed = (now - self._samples[0][0]).total_seconds()
        if elapsed < MIN_SPEED_SECONDS:
            return None
        return max(0.0, (downloaded - self._samples[0][1]) / elapsed)

    def poll(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        warnings = []
        source, _ = self._read("source.json", warnings, required=True)
        identity = _identity(source)
        if self._source_identity is not None and identity != self._source_identity:
            self._source_changed_at = now
            self._samples.clear()
            warnings.append("备份来源已变化；等待本次来源的校验记录")
        self._source_identity = identity
        progress, fresh = self._read("progress.json", warnings, required=True)
        progress = progress or {}
        local, _ = self._read("receipt.json", warnings)
        remote, _ = self._read("receipt.remote.json", warnings)
        report, _ = self._read("verification.json", warnings)
        receipt = local or remote
        info = _receipt(receipt)
        conflict = bool(local and remote and _receipt(local)["key"] != _receipt(remote)["key"])
        if conflict:
            warnings.append("本地与远端收据不一致，尚不能确认全量完成")
        if not receipt:
            warnings.append("等待归档收据，暂无法计算总量")
        completed = self._verified(report, receipt, info, source, progress, conflict)
        if report and report.get("phase") == "verified" and not completed:
            warnings.append("全量校验记录与当前备份尚不能对应，未确认完成")
        phase = "verified" if completed else progress.get("phase", "waiting")
        total, parts_total = info["total"], info["parts"]
        verified_bytes = progress.get("bytes_verified", 0)
        parts_verified = progress.get("parts_verified", 0)
        # On transfer failure, the last published partial count is still useful.
        # Metadata phases use the same counter for sidecars, which do not belong
        # in the archive denominator.
        active_is_archive = phase == "pulling" or (
            phase in ("failed", "interrupted")
            and isinstance(progress.get("current_part"), str)
            and progress["current_part"].endswith(".tarpart"))
        active = progress.get("current_part_bytes", 0) if active_is_archive else 0
        downloaded = verified_bytes + active
        if total:
            verified_bytes = min(verified_bytes, total)
            downloaded = min(downloaded, total)
        if parts_total:
            parts_verified = min(parts_verified, parts_total)
        members = progress.get("members_verified", 0)
        archive_read = progress.get("archive_bytes_read", 0)
        if total:
            archive_read = min(archive_read, total)
        if info["members"]:
            members = min(members, info["members"])
        if completed:
            downloaded = verified_bytes = archive_read = total
            parts_verified, members = parts_total, report["member_count"]
        updated = _date(report.get("verified_utc")) if completed else _date(progress.get("updated_utc"))
        stale = bool(not completed and updated and (now - updated).total_seconds() >= STALE_SECONDS)
        error = None
        if phase in ("failed", "interrupted"):
            raw_error = progress.get("error", progress.get("error_type", ""))
            error = str(raw_error)[:400] if raw_error else ("传输失败" if phase == "failed" else "传输已中断")
        attempts = progress.get("active_parts", {})
        attempts = ({name: value.get("attempt") for name, value in attempts.items() if isinstance(value, dict)}
                    if isinstance(attempts, dict) else {})
        speed = self._speed(now, downloaded, (identity, info["key"], progress.get("started_utc")),
                            attempts, updated, fresh and phase == "pulling" and not stale and updated is not None)
        remaining = max(0, total - downloaded) if total else None
        eta = remaining / speed if remaining is not None and speed is not None and speed > 0 else None
        percent = min(100.0, downloaded / total * 100) if total else None
        verification_percent = min(100.0, archive_read / total * 100) if total and phase in ("verifying", "verified") else None
        statuses = {"pulling": "正在下载归档", "manifest": "归档下载完成，正在下载清单",
                    "metadata": "归档下载完成，正在下载恢复资料", "verifying": "下载完成，正在全量校验",
                    "verified": "全量校验通过，备份已完成" if completed else "下载已报告完成，等待全量校验证据",
                    "failed": "备份传输失败", "interrupted": "备份传输已中断", "waiting": "等待备份进度"}
        status = statuses.get(phase, "正在读取备份状态")
        if phase == "pulling" and percent == 100:
            status = "归档下载 100%，等待后续全量校验"
        if stale:
            status += " · 进度暂未更新"
        if phase == "verifying":
            detail = f"已校验 {members:,} / {info['members']:,} 个成员；已读取 {archive_read:,} / {total:,} 字节"
        elif completed:
            detail = f"{parts_total:,} 个分块、{members:,} 个成员的完整校验记录已确认；异机恢复另行验收"
        else:
            detail = f"分块哈希已通过 {parts_verified:,} / {parts_total:,}；下载百分比包含当前分块，100% 后仍需全量校验"
        if error:
            detail += "；" + error
        warning = "；".join(warnings)
        if warning:
            detail += "；" + warning
        try:
            updated_local = updated.astimezone().strftime("%Y-%m-%d %H:%M:%S") if updated else "尚无更新时间"
        except (OverflowError, ValueError):
            updated_local = updated.isoformat()
        return {"download_percent": percent, "downloaded_bytes": downloaded, "total_bytes": total,
                "remaining_bytes": remaining, "verified_bytes": verified_bytes,
                "parts_verified": parts_verified, "parts_total": parts_total, "phase": phase,
                "status_text": status, "detail_text": detail,
                "updated_local": updated_local,
                "stale": stale, "speed_bps": speed, "eta_seconds": eta, "completed": completed,
                "error": error, "warning": warning, "members_verified": members,
                "members_total": info["members"], "archive_bytes_read": archive_read,
                "verification_percent": verification_percent}
