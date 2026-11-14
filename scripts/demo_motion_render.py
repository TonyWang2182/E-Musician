"""Deterministic brand-only demo bumpers. No model/API/UI calls or source-logo edits.

Uses the installed Windows Segoe UI fonts; font binaries are not copied. Outputs
editable JSON + SVG/HTML/Python sources, silent H.264 MP4 and VP9 alpha WebM.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version

WIDTH, HEIGHT, FPS = 1920, 1080, 30
PAPER = "#FEFEFD"
INK = "#171817"
SECONDARY = "#626560"
FOCUS = "#527D7A"
URL = "https://github.com/TonyWang2182/E-Musician"
LOGO_HASH = "6b94245a35170ebbcab97a1cec0a5d5bde08233f1c8bbe8f671f314fd34005a2"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ease(t, begin, duration):
    a = max(0.0, min(1.0, (t - begin) / duration))
    return 1.0 - (1.0 - a) ** 3


def default_config():
    return {
        "width": WIDTH, "height": HEIGHT, "fps": FPS,
        "paper": PAPER, "ink": INK, "secondary": SECONDARY, "focus": FOCUS,
        "logo": {"x": 260, "y": 330, "size": 350},
        "name": {"text": "E-musician", "x": 700, "y": 352, "size": 96},
        "rule": {"x": 700, "y": 478, "width": 720, "height": 2},
        "description": {"x": 700, "y": 518, "size": 36, "line_spacing": 52},
        "url": {"text": URL, "x": 700, "y": 668, "size": 29},
        "opener": {"seconds": 8, "lines": ["A music workspace", "with a built-in assistant."]},
        "closer": {"seconds": 6, "lines": ["Explore the code. Try it.", "Share feedback."]},
        "motion": {
            "opener": {"logo": [0.08, 0.64], "name": [0.36, 0.90], "description": [1.08, 0.56], "url": [1.80, 0.42]},
            "closer": {"logo": [0.0, 0.44], "name": [0.08, 0.56], "description": [0.36, 0.42], "url": [0.46, 0.36]},
        },
        "notes": "Brand reveal only; line is not task progress. No soundtrack. Last frame holds. Fonts referenced, not redistributed.",
    }


class Scene:
    def __init__(self, config, logo, regular, bold):
        self.c = config
        self.logo = Image.open(logo).convert("RGBA")
        self.font_regular = regular
        self.font_bold = bold
        self.layers = {}
        size = config["logo"]["size"]
        self.layers["logo"] = self.logo.resize((size, size), Image.Resampling.LANCZOS)
        self.layers["name"] = self.text(config["name"]["text"], config["name"]["size"], INK, bold)
        self.layers["url"] = self.text(URL, config["url"]["size"], FOCUS, regular)
        for kind in ("opener", "closer"):
            for i, line in enumerate(config[kind]["lines"]):
                self.layers[f"{kind}-{i}"] = self.text(line, config["description"]["size"], SECONDARY, regular)
        assert config["url"]["x"] + self.layers["url"].width <= WIDTH - 140
        assert config["name"]["x"] + self.layers["name"].width <= WIDTH - 140

    @staticmethod
    def text(text, size, color, font_path):
        scale = 2
        font = ImageFont.truetype(str(font_path), size * scale)
        bbox = font.getbbox(text, anchor="lt")
        layer = Image.new("RGBA", (bbox[2] + 6, bbox[3] + 8), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((0, 0), text, font=font, fill=color, anchor="lt")
        return layer.resize(((layer.width + 1) // 2, (layer.height + 1) // 2), Image.Resampling.LANCZOS)

    @staticmethod
    def put(target, layer, xy, opacity=1.0, reveal=1.0):
        if opacity <= 0 or reveal <= 0:
            return
        part = layer
        if reveal < 1:
            part = part.crop((0, 0, max(1, round(part.width * reveal)), part.height))
        if opacity < 1:
            part = part.copy()
            part.putalpha(part.getchannel("A").point(lambda a: round(a * opacity)))
        target.alpha_composite(part, tuple(map(round, xy)))

    def render(self, kind, t, transparent=False):
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0) if transparent else self.c["paper"])
        motions = self.c["motion"][kind]
        a = {key: ease(t, *timing) for key, timing in motions.items()}
        for key in ("logo", "name"):
            item = self.c[key]
            self.put(image, self.layers[key], (item["x"], item["y"]), a[key], a[key] if key == "name" else 1)
        rule = self.c["rule"]
        draw = ImageDraw.Draw(image)
        length = round(rule["width"] * a["name"])
        if length:
            draw.rectangle((rule["x"], rule["y"], rule["x"] + length, rule["y"] + rule["height"] - 1), fill=FOCUS)
        desc = self.c["description"]
        for i, _ in enumerate(self.c[kind]["lines"]):
            self.put(image, self.layers[f"{kind}-{i}"], (desc["x"], desc["y"] + i * desc["line_spacing"]), a["description"])
        url = self.c["url"]
        self.put(image, self.layers["url"], (url["x"], url["y"]), a["url"])
        return image


def svg_poster(config, kind, logo_base64):
    c = config
    elements = [f'<rect width="1920" height="1080" fill="{PAPER}"/>',
                f'<image x="{c["logo"]["x"]}" y="{c["logo"]["y"]}" width="350" height="350" href="data:image/png;base64,{logo_base64}"/>']
    n, d, u, r = c["name"], c["description"], c["url"], c["rule"]
    elements.append(f'<text x="{n["x"]}" y="{n["y"]}" dominant-baseline="text-before-edge" font-size="96" font-weight="700" fill="{INK}">{n["text"]}</text>')
    elements.append(f'<path d="M{r["x"]} {r["y"]}h{r["width"]}" stroke="{FOCUS}" stroke-width="2"/>')
    for i, line in enumerate(c[kind]["lines"]):
        elements.append(f'<text x="{d["x"]}" y="{d["y"]+i*d["line_spacing"]}" dominant-baseline="text-before-edge" font-size="36" fill="{SECONDARY}">{html.escape(line)}</text>')
    elements.append(f'<a href="{URL}"><text x="{u["x"]}" y="{u["y"]}" dominant-baseline="text-before-edge" font-size="29" fill="{FOCUS}">{URL}</text></a>')
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"><title>E-musician '+kind+'</title><g font-family="Segoe UI, sans-serif">'+''.join(elements)+'</g></svg>'


def html_preview(config):
    cfg = json.dumps(config, ensure_ascii=False)
    return r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>E-musician motion source</title>
<style>
:root{color-scheme:light;font-family:"Segoe UI",sans-serif;background:#FEFEFD;color:#171817}
*{box-sizing:border-box}body{margin:0;padding:24px}main{max-width:1280px;margin:auto}h1{font-size:24px;margin:0 0 18px}canvas{display:block;width:100%;height:auto;border:1px solid #C6C9C3}nav{display:flex;gap:12px;align-items:center;margin:16px 0;flex-wrap:wrap}button{font:inherit;color:#171817;background:#F1F2EE;border:1px solid #C6C9C3;border-radius:3px;padding:10px 16px;cursor:pointer}button:hover{background:#BFD2CF}button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid #527D7A;outline-offset:3px}a{color:#527D7A;text-underline-offset:4px}p{line-height:1.6;max-width:72ch;color:#626560}input{accent-color:#527D7A}::selection{background:#BFD2CF;color:#171817}
</style><main><h1>E-musician · editable motion preview</h1><canvas id="frame" width="1920" height="1080" aria-label="E-musician opening or closing animation"></canvas><nav><button id="open">Play opening · 8s</button><button id="close">Play closing · 6s</button><button id="pause">Pause</button><label><input id="reduce" type="checkbox"> Reduced motion</label><output id="time">0.00 s</output></nav><p>This canvas uses the original approved logo. Edit <code>motion-config.json</code> and re-render with the accompanying Python script for the exported videos. This self-contained source snapshot contains the same configuration. No sound is included.</p><p><a href="opener-1080p30.mp4">Opening MP4</a> · <a href="opener-6s-1080p30.mp4">Opening 6s MP4</a> · <a href="closer-1080p30.mp4">Closing MP4</a> · <a href="https://github.com/TonyWang2182/E-Musician">Project on GitHub</a></p></main>
<script>const C=CONFIG,cv=document.querySelector('#frame'),ctx=cv.getContext('2d'),logo=new Image();let mode='opener',start=0,running=false,raf=0;const reduce=document.querySelector('#reduce');reduce.checked=matchMedia('(prefers-reduced-motion: reduce)').matches;
function ease(t,b,d){const p=Math.max(0,Math.min(1,(t-b)/d));return 1-Math.pow(1-p,3)}
window.renderFrame=(t,kind=mode)=>{const m=C.motion[kind],a={};Object.entries(m).forEach(([k,v])=>a[k]=reduce.checked?1:ease(t,...v));ctx.clearRect(0,0,1920,1080);ctx.fillStyle=C.paper;ctx.fillRect(0,0,1920,1080);ctx.globalAlpha=a.logo;ctx.drawImage(logo,C.logo.x,C.logo.y,C.logo.size,C.logo.size);ctx.globalAlpha=a.name;ctx.save();ctx.beginPath();ctx.rect(C.name.x-1,C.name.y-20,760*a.name,150);ctx.clip();ctx.fillStyle=C.ink;ctx.font=`700 ${C.name.size}px "Segoe UI",sans-serif`;ctx.textBaseline='top';ctx.fillText(C.name.text,C.name.x,C.name.y);ctx.restore();ctx.globalAlpha=1;ctx.fillStyle=C.focus;ctx.fillRect(C.rule.x,C.rule.y,C.rule.width*a.name,C.rule.height);ctx.globalAlpha=a.description;ctx.fillStyle=C.secondary;ctx.font=`${C.description.size}px "Segoe UI",sans-serif`;C[kind].lines.forEach((line,i)=>ctx.fillText(line,C.description.x,C.description.y+i*C.description.line_spacing));ctx.globalAlpha=a.url;ctx.fillStyle=C.focus;ctx.font=`${C.url.size}px "Segoe UI",sans-serif`;ctx.fillText(C.url.text,C.url.x,C.url.y);ctx.globalAlpha=1;document.querySelector('#time').textContent=t.toFixed(2)+' s';};
function tick(now){if(!running)return;let t=Math.min(C[mode].seconds,(now-start)/1000);renderFrame(t);if(t<C[mode].seconds)raf=requestAnimationFrame(tick);else running=false;}
function play(kind){cancelAnimationFrame(raf);mode=kind;start=performance.now();running=true;raf=requestAnimationFrame(tick);}
document.querySelector('#open').onclick=()=>play('opener');document.querySelector('#close').onclick=()=>play('closer');document.querySelector('#pause').onclick=()=>{running=false;cancelAnimationFrame(raf)};reduce.onchange=()=>renderFrame(C[mode].seconds);document.addEventListener('visibilitychange',()=>{if(document.hidden){running=false;cancelAnimationFrame(raf)}});logo.onload=()=>renderFrame(C.opener.seconds);logo.src='source/yi-yue-shi-logo.png';</script></html>'''.replace("CONFIG", cfg)


def execute(command, logfile, records):
    start = now()
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logfile.write_bytes(result.stdout)
    records.append({"start_utc": start, "end_utc": now(), "command": command, "exit_code": result.returncode, "log": str(logfile)})
    if result.returncode:
        raise RuntimeError(f"Command failed: {logfile}")
    return result.stdout


def encode(scene, kind, dest, ffmpeg, transparent, records):
    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "warning", "-f", "rawvideo", "-vcodec", "rawvideo",
               "-pixel_format", "rgba", "-video_size", "1920x1080", "-framerate", "30", "-i", "pipe:0", "-an"]
    if transparent:
        command += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "12", "-deadline", "realtime", "-cpu-used", "6", "-row-mt", "1", "-auto-alt-ref", "0"]
    else:
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    command += [str(dest)]
    log = dest.parent / "logs" / (dest.stem + ".log")
    start = now()
    with log.open("wb") as stream:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stream, stderr=stream)
        try:
            for frame in range(int(scene.c[kind]["seconds"] * FPS)):
                proc.stdin.write(scene.render(kind, frame / FPS, transparent).tobytes())
            proc.stdin.close()
            code = proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
    records.append({"start_utc": start, "end_utc": now(), "command": command, "exit_code": code, "log": str(log), "frame_count": int(scene.c[kind]["seconds"] * FPS)})
    if code:
        raise RuntimeError(f"Encoding failed: {log}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--ffmpeg", type=Path, required=True)
    p.add_argument("--ffprobe", type=Path)
    p.add_argument("--config", type=Path)
    p.add_argument("--stills-only", action="store_true")
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    logo = repo / "assets/brand/yi-yue-shi-logo.png"
    if not logo.exists():
        logo = Path(__file__).resolve().parent / "yi-yue-shi-logo.png"
    assert sha(logo) == LOGO_HASH, "Unexpected logo: preserve approved source"
    for child in ("source", "stills", "logs"):
        (a.out / child).mkdir(parents=True, exist_ok=True)
    c = json.loads(a.config.read_text(encoding="utf-8")) if a.config else default_config()
    (a.out / "motion-config.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    copied_logo = a.out / "source/yi-yue-shi-logo.png"
    if copied_logo.resolve() != logo.resolve():
        shutil.copyfile(logo, copied_logo)
    target_script = a.out / "source/demo_motion_render.py"
    if target_script.resolve() != Path(__file__).resolve():
        shutil.copyfile(__file__, target_script)
    regular, bold = Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/segoeuib.ttf")
    scene = Scene(c, logo, regular, bold)
    b64 = base64.b64encode(logo.read_bytes()).decode()
    for kind in ("opener", "closer"):
        (a.out / "source" / f"{kind}-poster.svg").write_text(svg_poster(c, kind, b64), encoding="utf-8")
        for t in (0.0, 0.5, 1.0, 2.0, float(c[kind]["seconds"]) - 1/FPS):
            scene.render(kind, t).convert("RGB").save(a.out / "stills" / f"{kind}-{t:.3f}s.png")
        scene.render(kind, c[kind]["seconds"]).save(a.out / "stills" / f"{kind}-poster.png")
    (a.out / "preview.html").write_text(html_preview(c), encoding="utf-8")
    font_records = []
    from fontTools.ttLib import TTFont
    for f in (regular, bold):
        font = TTFont(f)
        items = {}
        for key, number in (("family", 1), ("copyright", 0), ("license", 13), ("license_url", 14)):
            names = [n.toUnicode() for n in font["name"].names if n.nameID == number and n.platformID == 3]
            items[key] = next(iter(names), "Not embedded")
        font_records.append({"path": str(f), "sha256": sha(f), "redistributed": False, **items})
    (a.out / "source/FONT-SOURCES.json").write_text(json.dumps(font_records, ensure_ascii=False, indent=2), encoding="utf-8")
    records = []
    report = {"status": "rendering", "started_utc": now(), "machine": platform.platform(), "python": sys.version,
              "pillow": pillow_version, "dimensions": [WIDTH, HEIGHT], "fps": FPS, "logo_source": str(logo), "logo_sha256": sha(logo),
              "logo_byte_copy_sha256": sha(copied_logo), "github": URL, "no_network": True, "no_gui_control": True, "audio": "none", "commands": records}
    receipt = a.out / "RENDER-REPORT.json"
    try:
        if not a.stills_only:
            for kind in ("opener", "closer"):
                for alpha in (False, True):
                    dest = a.out / f"{kind}-1080p30.{ 'webm' if alpha else 'mp4'}"
                    encode(scene, kind, dest, a.ffmpeg, alpha, records)
            execute([str(a.ffmpeg), "-y", "-hide_banner", "-i", str(a.out / "opener-1080p30.mp4"), "-t", "6", "-an", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(a.out / "opener-6s-1080p30.mp4")], a.out / "logs/opener-6s.log", records)
            videos = []
            for file in sorted(a.out.glob("*.mp4")) + sorted(a.out.glob("*.webm")):
                info = {"path": str(file), "bytes": file.stat().st_size, "sha256": sha(file)}
                if a.ffprobe:
                    raw = execute([str(a.ffprobe), "-v", "error", "-count_frames", "-show_entries", "stream=codec_name,width,height,pix_fmt,avg_frame_rate,nb_read_frames:stream_tags=alpha_mode:format=duration", "-of", "json", str(file)], a.out / "logs" / (file.name + ".probe.json"), records)
                    info["probe"] = json.loads(raw)
                    v = info["probe"]["streams"][0]
                    assert (v["width"], v["height"], v["avg_frame_rate"]) == (WIDTH, HEIGHT, "30/1")
                execute([str(a.ffmpeg), "-v", "error", "-i", str(file), "-f", "null", "-"], a.out / "logs" / (file.name + ".decode.log"), records)
                videos.append(info)
            report["videos"] = videos
            for kind in ("opener", "closer"):
                execute([str(a.ffmpeg), "-y", "-v", "error", "-ss", "3", "-i", str(a.out / f"{kind}-1080p30.mp4"), "-frames:v", "1", str(a.out / "stills" / f"{kind}-encoded-3s.png")], a.out / "logs" / f"{kind}-extract.log", records)
                alpha_png = a.out / "stills" / f"{kind}-alpha-decoded-3s.png"
                execute([str(a.ffmpeg), "-y", "-v", "error", "-c:v", "libvpx-vp9", "-ss", "3", "-i", str(a.out / f"{kind}-1080p30.webm"), "-frames:v", "1", "-pix_fmt", "rgba", str(alpha_png)], a.out / "logs" / f"{kind}-alpha.log", records)
                decoded = Image.open(alpha_png).convert("RGBA")
                amin, amax = decoded.getchannel("A").getextrema()
                assert amin == 0 and amax == 255, "Alpha did not survive VP9 round trip"
                report.setdefault("alpha_roundtrip", {})[kind] = {"minimum": amin, "maximum": amax, "background_corner": decoded.getpixel((0, 0))}
        report["status"] = "stills-ready" if a.stills_only else "exports-verified"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        report["finished_utc"] = now()
        receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(a.out), "report": str(receipt)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
