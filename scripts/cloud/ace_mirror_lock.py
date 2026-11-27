"""Change only PyPI wheel transport host, retaining upstream versions/hashes."""
import hashlib
import json
from pathlib import Path

ROOT = Path("/root/autodl-tmp/emusician")
SOURCE = ROOT / "workspace/third_party/ACE-Step-1.5-ca1e85fe9430179831e6bc6be790c332190a3866"
lock = SOURCE / "uv.lock"
original = SOURCE / "uv.lock.upstream"
if not original.exists():
    original.write_bytes(lock.read_bytes())
raw = original.read_bytes()
patched = raw.replace(b"https://files.pythonhosted.org/packages/", b"https://mirrors.aliyun.com/pypi/packages/")
lock.write_bytes(patched)
record = {"reason": "Remote PyPI file downloads stalled; use mirror transport with original SHA-256 validation.",
          "upstream_sha256": hashlib.sha256(raw).hexdigest(), "transport_lock_sha256": hashlib.sha256(patched).hexdigest(),
          "replace_from": "https://files.pythonhosted.org/packages/", "replace_to": "https://mirrors.aliyun.com/pypi/packages/",
          "versions_hashes_unchanged": True}
ROOT.joinpath("manifests/ace-lock-transport.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record))
