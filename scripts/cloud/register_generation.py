"""Check the private cloud service and optionally register its validated model."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid
from run_generation import ROOT, Tunnel, atomic_json, read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / "registry.json"
    registry = read_json(path) if path.exists() else {"schema_version": 1, "available": False,
        "python_executable": sys.executable, "model_id": "ace-step-1.5-xl-turbo", "ssh_alias": "emusician-cloud", "remote_port": 18081}
    directory = ROOT / "experiments" / ("connection-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    tunnel = Tunnel(registry, directory)
    try:
        health = tunnel.open()
        capabilities = tunnel.call("GET", "/capabilities")
        provider = next((p for p in capabilities.get("providers", []) if p.get("model_id") == registry["model_id"]), {})
        ready = provider.get("available") is True
        report = {"checked_at": datetime.now(timezone.utc).isoformat(), "health": health,
                  "capabilities": capabilities, "available": ready, "inference_performed": False}
        atomic_json(directory / "report.json", report)
        if args.register:
            if not ready:
                raise RuntimeError("The cloud model is not validated and ready yet; registry was not changed.")
            registry.update(available=True, python_executable=sys.executable, checked_at=report["checked_at"], status="configured; connectivity checked at job start")
            atomic_json(path, registry)
        print(f"Service reachable; validated model available: {ready}. Report: {directory / 'report.json'}")
    finally:
        tunnel.close()


if __name__ == "__main__":
    main()
