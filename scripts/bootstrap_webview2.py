"""Fetch and verify the pinned official WebView2 SDK; no machine-wide install."""
from pathlib import Path
import hashlib
import json
import sys
import urllib.request
import zipfile
from dev import Recorder
ROOT=Path(__file__).resolve().parent.parent
def main():
    if "--worker" not in sys.argv:
        return Recorder("webview2-bootstrap","SDK","Pinned Microsoft NuGet SDK; isolated in .cache").execute([sys.executable,__file__,"--worker",*sys.argv[1:]]).returncode
    manifest=json.loads((ROOT/"cmake/webview2.json").read_text())
    directory=ROOT/".cache/webview2"
    target=directory/("Microsoft.Web.WebView2."+manifest["version"])
    if "--verify-only" in sys.argv:
        for name,key in [("build/native/include/WebView2.h","header_sha256"),("build/native/x64/WebView2LoaderStatic.lib","x64_library_sha256")]:
            if not (target/name).is_file() or hashlib.sha256((target/name).read_bytes()).hexdigest()!=manifest[key]:
                raise RuntimeError("Pinned WebView2 SDK is missing or changed.")
        print("Pinned WebView2 SDK verified without writes:",manifest["version"])
        return 0
    directory.mkdir(parents=True,exist_ok=True)
    archive=directory/("webview2-"+manifest["version"]+".nupkg")
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest["sha256"]:
        with urllib.request.urlopen(manifest["url"],timeout=45) as response:
            data=response.read(32*1024*1024)
        if len(data)>=32*1024*1024 or hashlib.sha256(data).hexdigest()!=manifest["sha256"]:
            raise RuntimeError("WebView2 archive hash mismatch.")
        archive.write_bytes(data)
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            if not (target/member.filename).resolve().is_relative_to(target.resolve()):
                raise RuntimeError("Unsafe archive path.")
        z.extractall(target)
    for name,key in [("build/native/include/WebView2.h","header_sha256"),("build/native/x64/WebView2LoaderStatic.lib","x64_library_sha256")]:
        if hashlib.sha256((target/name).read_bytes()).hexdigest()!=manifest[key]:
            raise RuntimeError("WebView2 SDK file hash mismatch.")
    print("Pinned WebView2 SDK verified:",manifest["version"])
    return 0
if __name__=="__main__":raise SystemExit(main())
