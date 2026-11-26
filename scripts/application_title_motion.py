"""Application-film title cards over the retained, unmodified background movies.

The five supplied references inform typewriter, selective focus and one card-stack
transition. No reference video pixels are incorporated. No DAW, model or network.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS = 1920, 1080, 30
DEFAULT_OUT = Path('E:/MusicAgent&DAW/demo-video/application-script-2026-11-27/motion')
BACKGROUND = Path('E:/MusicAgent&DAW/demo-video/showcase-v1/motion')
FFMPEG = Path('E:/SUMIN/ABC_Ocean/_tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe')
FFPROBE = Path('E:/Users/28712/AppData/Local/Programs/Audio Jam/lib/win32/ffprobe.exe')
FONT = Path('C:/Windows/Fonts/arial.ttf')
LOGO = ROOT / 'assets/brand/yi-yue-shi-logo.png'
LOGO_SHA = '6b94245a35170ebbcab97a1cec0a5d5bde08233f1c8bbe8f671f314fd34005a2'
URL = 'github.com/TonyWang2182/E-Musician'
SPECS = [
    dict(id='part-01-opening', seconds=14, part=1, background='chapter-03-harmony', style='opening', colour='dark', title='E-musician', subtitle='A workspace for making music.'),
    dict(id='part-02-generation', seconds=4, part=2, background='chapter-01-generation', style='typewriter', colour='light', title='Start with an idea.', lines=['Start with', 'an idea.']),
    dict(id='part-04-separation', seconds=4, part=4, background='chapter-02-separation', style='focus', colour='light', title='Hear the parts.', lines=['Hear the parts.']),
    dict(id='part-06-harmony', seconds=4, part=6, background='chapter-03-harmony', style='phrase', colour='dark', title='Follow the harmony.', lines=['Follow the', 'harmony.']),
    dict(id='part-08-pulse', seconds=4, part=8, background='chapter-04-timing', style='focus', colour='dark', title='Find the pulse.', lines=['Find the pulse.']),
    dict(id='part-10-transcription', seconds=4, part=10, background='chapter-05-transcription', style='stack', colour='dark', title='From sound to notes.', lines=['From sound', 'to notes.']),
    dict(id='part-12-workspace', seconds=4, part=12, background='chapter-06-workspace', style='focus', colour='light', title='Make it your own.', lines=['Make it', 'your own.']),
    dict(id='part-14-closing', seconds=14, part=14, background='chapter-03-harmony', style='closing', colour='dark', title='E-musician', subtitle='Explore the project.', url=URL),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def ease(t, start, duration):
    k = max(0., min(1., (t - start) / duration))
    return 1. - (1. - k) ** 3


def text_layer(lines, size=150, colour=(245, 248, 248), centre=(960, 540), leading=1.08):
    font = ImageFont.truetype(str(FONT), size)
    layer = Image.new('RGBA', (W, H))
    d = ImageDraw.Draw(layer)
    heights = [d.textbbox((0, 0), line, font=font)[3] - d.textbbox((0, 0), line, font=font)[1] for line in lines]
    total = size * leading * (len(lines) - 1) + heights[-1]
    top = centre[1] - total / 2
    for i, line in enumerate(lines):
        box = d.textbbox((0, 0), line, font=font)
        width = d.textlength(line, font=font)
        d.text((centre[0] - width / 2, top + i * size * leading - box[1]), line, font=font, fill=(*colour, 255))
    bbox = layer.getbbox()
    assert bbox is not None and bbox[0] >= 105 and bbox[2] <= W - 105, (lines, bbox)
    assert bbox[1] >= 90 and bbox[3] <= H - 90, (lines, bbox)
    return layer


def focus_reveal(layer, t, start=.08, duration=1.25):
    if t < start:
        return Image.new('RGBA', layer.size)
    if t >= start + duration:
        return layer
    box = layer.getbbox()
    if not box:
        return layer
    progress = max(0., min(1., (t - start) / duration))
    # A narrow defocus band travels left to right; resolved text stays in place.
    x = box[0] - 100 + (box[2] - box[0] + 200) * progress
    xs = np.arange(W, dtype=np.float32)
    sharp = np.clip((x + 65 - xs) / 130, 0, 1)
    mask = Image.fromarray(np.tile(np.uint8(sharp * 255), (H, 1)))
    blur = layer.filter(ImageFilter.GaussianBlur(13))
    result = Image.composite(layer, blur, mask)
    opacity = ease(t, start, .18)
    result.putalpha(result.getchannel('A').point(lambda a: round(a * opacity)))
    return result


class TitleMotion:
    def __init__(self, spec):
        self.s = spec
        self.colour = (247, 249, 248) if spec['colour'] == 'light' else (18, 29, 34)
        self.font = ImageFont.truetype(str(FONT), 150)
        self.logo = Image.open(LOGO).convert('RGBA')
        if 'lines' in spec:
            self.title = text_layer(spec['lines'], colour=self.colour)
        self.observed_bounds = []

    def typewriter(self, t):
        lines = self.s['lines']
        font = self.font
        layer = Image.new('RGBA', (W, H))
        d = ImageDraw.Draw(layer)
        heights = [d.textbbox((0, 0), x, font=font)[3] - d.textbbox((0, 0), x, font=font)[1] for x in lines]
        y0 = 540 - (150 * 1.08 * (len(lines) - 1) + heights[-1]) / 2
        count = int(max(0, min(1, (t - .15) / 1.5)) * sum(map(len, lines)))
        cursor = None
        remaining = count
        for index, line in enumerate(lines):
            width = d.textlength(line, font=font)
            box = d.textbbox((0, 0), line, font=font)
            x, y = 960 - width / 2, y0 + index * 162 - box[1]
            n = min(len(line), remaining)
            if n:
                d.text((x, y), line[:n], font=font, fill=(*self.colour, 255))
            if remaining <= len(line) and cursor is None:
                cursor = (x + d.textlength(line[:n], font=font) + 10, y + box[1])
            remaining -= n
        if t >= .15 and t < 2.3 and int(t * 3.2) % 2 == 0 and cursor:
            x, y = cursor
            d.rectangle((x, y - 8, x + 3, y + 115), fill=(*self.colour, 255))
        return layer

    def brand(self, t, closing=False):
        layer = Image.new('RGBA', (W, H))
        # Same approved artwork, scaled only; pale retained background is untouched.
        logo = self.logo.resize((260, 260), Image.Resampling.LANCZOS)
        logo.putalpha(logo.getchannel('A').point(lambda a: round(a * ease(t, .1, .65))))
        layer.alpha_composite(logo, (830, 170))
        title = text_layer(['E-musician'], size=134, colour=self.colour, centre=(960, 510))
        layer.alpha_composite(focus_reveal(title, t, .35, 1.15))
        subtitle = text_layer([self.s['subtitle']], size=52, colour=self.colour, centre=(960, 660))
        layer.alpha_composite(focus_reveal(subtitle, t, 1.15, .75))
        if closing:
            url = text_layer([URL], size=42, colour=(30, 68, 74), centre=(960, 810))
            layer.alpha_composite(focus_reveal(url, t, 2.6, .85))
        return layer

    def phrase(self, t):
        # The first clause resolves, then the sentence settles into its full layout.
        layer = Image.new('RGBA', (W, H))
        first = text_layer(['Follow the'], colour=self.colour, centre=(960, 460))
        second = text_layer(['harmony.'], colour=self.colour, centre=(960, 622))
        layer.alpha_composite(focus_reveal(first, t, .05, .65))
        layer.alpha_composite(focus_reveal(second, t, .65, .8))
        return layer

    def stack(self, background, t):
        before = background.copy().convert('RGBA')
        from_text = text_layer(['From sound'], colour=self.colour)
        before.alpha_composite(focus_reveal(from_text, t, .04, .55))
        after = background.copy().convert('RGBA')
        after.alpha_composite(self.title)
        if t < .82:
            return before
        if t >= 1.8:
            return after
        k = (t - .82) / .98
        p = 1 - (1-k)**3
        # A single stack transition adapts reference4's receding horizontal cards.
        canvas = Image.new('RGBA', (W, H), (8, 22, 26, 255))
        for i in range(5, -1, -1):
            scale = 1 - .045 * i - .22 * p
            width = max(1, round(W * scale))
            height = max(1, round(H * (1 - .88 * p) * (1 - .09 * i)))
            card = before.resize((width, height), Image.Resampling.BICUBIC)
            mask = Image.new('L', (width, height))
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, width-1, height-1), radius=round(22 * p), fill=255)
            card.putalpha(mask)
            canvas.alpha_composite(card, ((W-width)//2, round(390 * p + i * 26 * p)))
        front = max(0., min(1., (k - .15) / .85))
        front = 1 - (1-front)**3
        width = round(W * (.88 + .12 * front))
        height = round(H * (.66 + .34 * front))
        card = after.resize((width, height), Image.Resampling.BICUBIC)
        canvas.alpha_composite(card, ((W-width)//2, round(H * (1-front))))
        return canvas

    def render(self, background, t):
        style = self.s['style']
        if style == 'stack':
            return self.stack(background, t).convert('RGB')
        if style == 'typewriter': overlay = self.typewriter(t)
        elif style in ('opening', 'closing'): overlay = self.brand(t, style == 'closing')
        elif style == 'phrase': overlay = self.phrase(t)
        else: overlay = focus_reveal(self.title, t)
        bounds = overlay.getbbox()
        if bounds:
            self.observed_bounds.append(bounds)
        image = background.convert('RGBA')
        image.alpha_composite(overlay)
        return image.convert('RGB')


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            raise EOFError(f'Background frame ended at {len(data)}/{size}')
        data.extend(part)
    return bytes(data)


def render_asset(spec, out, overwrite=False):
    source = BACKGROUND / (spec['background'] + '-1080p30.mp4')
    target = out / (spec['id'] + '-1080p30.mp4')
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    started = now()
    source_hash = sha(source)
    frame_count = spec['seconds'] * FPS
    decoder_args = [str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-stream_loop', '-1', '-i', str(source), '-an', '-t', str(spec['seconds']), '-vf', 'fps=30', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
    encoder_args = [str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{W}x{H}', '-framerate', str(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)]
    out.mkdir(parents=True, exist_ok=True)
    (out / 'stills').mkdir(exist_ok=True)
    (out / 'logs').mkdir(exist_ok=True)
    motion = TitleMotion(spec)
    capture_times = [.0, .35, .75, 1.2, 1.8, 2.6, 3.5] if spec['seconds'] == 4 else [.0, .6, 1.3, 2., 3.5, 7., 12.]
    capture_frames = {round(t * FPS): t for t in capture_times}
    frames = []
    with (out / 'logs' / (spec['id'] + '-decode.log')).open('wb') as dl, (out / 'logs' / (spec['id'] + '-encode.log')).open('wb') as el:
        decoder = subprocess.Popen(decoder_args, stdout=subprocess.PIPE, stderr=dl)
        encoder = subprocess.Popen(encoder_args, stdin=subprocess.PIPE, stderr=el)
        try:
            for i in range(frame_count):
                background = Image.frombytes('RGB', (W, H), read_exact(decoder.stdout, W*H*3))
                rendered = motion.render(background, i / FPS)
                if i in capture_frames:
                    thumb = rendered.resize((480, 270), Image.Resampling.LANCZOS)
                    frames.append((capture_frames[i], thumb))
                    rendered.save(out / 'stills' / f"{spec['id']}-{capture_frames[i]:04.1f}s.png")
                encoder.stdin.write(rendered.tobytes())
            encoder.stdin.close()
            assert encoder.wait(timeout=90) == 0, target.name
            decoder.stdout.close()
            assert decoder.wait(timeout=30) == 0, source.name
        except BaseException:
            decoder.kill(); encoder.kill()
            decoder.wait(); encoder.wait()
            raise
    assert sha(source) == source_hash, 'Retained background changed'
    contact = Image.new('RGB', (480 * 4, 308 * 2), '#e7edee')
    d = ImageDraw.Draw(contact)
    font = ImageFont.truetype(str(FONT), 22)
    for i, (t, im) in enumerate(frames):
        x, y = i % 4 * 480, i // 4 * 308
        contact.paste(im, (x, y))
        d.text((x+10, y+278), f"{spec['id']} | {t:.2f}s", font=font, fill='#13232a')
    contact.save(out / 'stills' / (spec['id'] + '-contact.jpg'), quality=92)
    return {**spec, 'file': target.name, 'sha256': sha(target), 'bytes': target.stat().st_size, 'source': str(source), 'source_sha256': source_hash, 'source_unchanged': True, 'started_at': started, 'finished_at': now(), 'frames': frame_count, 'decoder_command': decoder_args, 'encoder_command': encoder_args, 'observed_text_bounds_union': [min(x[0] for x in motion.observed_bounds), min(x[1] for x in motion.observed_bounds), max(x[2] for x in motion.observed_bounds), max(x[3] for x in motion.observed_bounds)] if motion.observed_bounds else None}


def verify(out):
    manifest = json.loads((out / 'MANIFEST.json').read_text(encoding='utf-8'))
    records = []
    for item in manifest['assets']:
        target = out / item['file']
        probe = json.loads(subprocess.check_output([str(FFPROBE), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(target)]))
        streams = probe['streams']
        video = next(x for x in streams if x['codec_type'] == 'video')
        assert not any(x['codec_type'] == 'audio' for x in streams)
        assert (video['width'], video['height'], video['r_frame_rate']) == (W, H, '30/1')
        assert int(video['nb_frames']) == item['seconds'] * FPS
        assert abs(float(probe['format']['duration']) - item['seconds']) < .001
        subprocess.run([str(FFMPEG), '-v', 'error', '-i', str(target), '-f', 'null', '-'], check=True, stdout=subprocess.DEVNULL)
        assert sha(target) == item['sha256']
        assert sha(item['source']) == item['source_sha256']
        bounds = item.get('observed_text_bounds_union')
        assert bounds is None or (bounds[0] > 0 and bounds[1] > 0 and bounds[2] < W and bounds[3] < H), bounds
        records.append({'file': item['file'], 'seconds': item['seconds'], 'frames': int(video['nb_frames']), 'full_decode': True, 'sha256': item['sha256'], 'silent': True})
    assert sha(LOGO) == LOGO_SHA
    dump(out / 'VALIDATION.json', {'checked_at': now(), 'status': 'passed', 'logo_unchanged': True, 'assets': records})
    print(json.dumps({'verified_assets': len(records), 'seconds': sum(x['seconds'] for x in records)}), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--mode', choices=['render', 'verify'], default='render')
    p.add_argument('--only')
    p.add_argument('--overwrite', action='store_true')
    p.add_argument('--record', action='store_true')
    a = p.parse_args()
    if a.record:
        from dev import Recorder
        class DeferredRecorder(Recorder):
            def append_devlog(self, record, record_path, log_path):
                dump(ROOT / 'build-logs' / ('application-motion-deferred-' + record['id'] + '.json'), {'record': str(record_path), 'log': str(log_path), 'summary': record['status']})
        r = DeferredRecorder('application-title-motion-' + a.mode, '1920x1080/30fps/silent', 'New title overlays on retained backgrounds, exact original logo, five supplied text-motion references; deferred DEVLOG for root consolidation.')
        args = [x for x in sys.argv[1:] if x != '--record']
        r.execute([sys.executable, str(Path(__file__).resolve()), *args])
        return
    assert sha(LOGO) == LOGO_SHA
    if a.mode == 'verify':
        verify(a.out)
        return
    specs = [s for s in SPECS if not a.only or s['id'] == a.only]
    assert specs, 'Unknown asset id'
    path = a.out / 'MANIFEST.json'
    manifest = json.loads(path.read_text(encoding='utf-8')) if a.only and path.exists() else {'created_at': now(), 'resolution': [W, H], 'fps': FPS, 'font': str(FONT), 'font_sha256': sha(FONT), 'logo_sha256': LOGO_SHA, 'assets': [], 'reference_policy': 'Reference motion language only; no reference pixels or audio reused.'}
    for s in specs:
        print('Rendering ' + s['id'], flush=True)
        item = render_asset(s, a.out, a.overwrite)
        manifest['assets'] = [x for x in manifest['assets'] if x['id'] != s['id']] + [item]
        manifest['assets'].sort(key=lambda x: x['part'])
        dump(path, manifest)
        print('Completed ' + s['id'], flush=True)
    source = a.out / 'source'
    source.mkdir(exist_ok=True)
    shutil.copyfile(__file__, source / Path(__file__).name)
    shutil.copyfile(LOGO, source / LOGO.name)
    dump(source / 'titles.json', SPECS)


if __name__ == '__main__':
    main()
