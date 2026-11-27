"""Inspect deployment evidence; never activate a model or contact the DAW."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

CHECKS = ("files_verified", "environment_verified", "cpu_load_verified", "gpu_inference_verified")


def read_json(path: Path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError(f"Deployment record exceeds 4 MiB: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(path: Path):
    record = read_json(path)
    model_id = record.get("id")
    if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", model_id):
        raise ValueError(f"Invalid model identifier in {path}")
    checks = record.get("checks", {})
    for name in CHECKS:
        if name in checks and type(checks[name]) is not bool:
            raise ValueError(f"{model_id}: {name} must be a boolean")
    if record.get("daw_connected") is not False:
        raise ValueError(f"{model_id}: this deployment phase requires daw_connected=false")
    if checks.get("gpu_inference_verified") and not all(checks.get(k) for k in CHECKS[:2]):
        raise ValueError(f"{model_id}: GPU verification lacks artifact/environment checks")
    if checks.get("cpu_load_verified") and not all(checks.get(k) for k in CHECKS[:2]):
        raise ValueError(f"{model_id}: CPU loading lacks artifact/environment checks")
    level = "recorded"
    for name, label in zip(CHECKS, ("files-verified", "environment-verified", "cpu-loaded", "gpu-tested")):
        if checks.get(name):
            level = label
    return {
        "id": model_id,
        "task": record.get("task"),
        "level": level,
        "checks": {k: checks.get(k, False) for k in CHECKS},
        "verification_scope": record.get("gpu_verified_scope", record.get("verified_scope", "See deployment record and probe evidence")),
        "daw_connected": False,
        "blockers": record.get("blockers", []),
        "source_revision": record.get("source_revision"),
        "model_revisions": record.get("model_revisions"),
        "paths": record.get("paths", {}),
        "deployment_record": str(path),
    }


def collect(root: Path):
    library = root / "manifests/model-library"
    entries, errors = [], []
    for path in sorted(library.glob("*/deployment.json")):
        try:
            entry = summarize(path)
            if any(old["id"] == entry["id"] for old in entries):
                raise ValueError(f"Duplicate identifier {entry['id']}")
            entries.append(entry)
        except (OSError, ValueError, TypeError, AttributeError) as error:
            errors.append({"record": str(path), "error": str(error)})
    disk = shutil.disk_usage(root)
    return {
        "schema_version": 1,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "cloud-only-deployment-evidence-not-a-service-registry",
        "root": str(root),
        "models": entries,
        "errors": errors,
        "legacy_manifests": [str(p) for p in (root / "manifests/ace-runtime.json",
            root / "manifests/mir-stage-status.json") if p.is_file()],
        "disk_bytes": {"total": disk.total, "used": disk.used, "free": disk.free},
        "minimum_free_budget_bytes": 50_000_000_000,
        "minimum_free_budget_satisfied": disk.free >= 50_000_000_000,
        "model_data_copied_by_this_tool": False,
        "service_activation_performed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/root/autodl-tmp/emusician"))
    parser.add_argument("--write", action="store_true", help="Atomically write the cloud catalog after all records validate")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    report = collect(root)
    if args.write and not report["errors"]:
        target = root / "manifests/model-library/catalog.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
