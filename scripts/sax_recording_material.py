"""Post-production recording visualization from supplied playback pixels.

This never operates the DAW or records input. Provenance is retained in MANIFEST.
The source has silent AAC; outputs are silent for insertion under existing music.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('E:/MusicAgent&DAW/demo-video/sax-recording-2026-11-27')
FFMPEG=Path('E:/SUMIN/ABC_Ocean/_tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe')
FFPROBE=Path('E:/Users/28712/AppData/Local/Programs/Audio Jam/lib/win32/ffprobe.exe')
SOURCE=Path('F:/屏幕录制/屏幕录制 2026-11-27 034145.mp4')
PROJECT=Path('E:/MusicAgent&DAW/demo-video/showcase-v1/captures/projects/demo4/test drive.emproj')
FRAME=OUT/'reference-review/frame-00-000.0s.png'
W,H,FPS=2556,1488,30
SECONDS=36
SOURCE_IN=14.6
START=15.00859375-SOURCE_IN
TAKE=34.94165987326702
LEFT,TOP,RIGHT,BOTTOM=597,1269,1483,1400
RECORD=(163,66,66)
FONT=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
SMALL=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',16)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def source_audio():
    data=json.loads(PROJECT.read_text(encoding='utf-8'))
    track=next(t for t in data['tracks'] if t['name']=='sax_player')
    clip=track['clips'][0]
    asset=next(a for a in data['assets'] if a['id']==clip['asset_id'])
    path=PROJECT.parent/asset['source']
    cmd=[str(FFMPEG),'-v','error','-ss',str(clip['source_offset']),'-i',str(path),'-t',str(TAKE),'-ar','48000','-ac','2','-f','f32le','pipe:1']
    pcm=np.frombuffer(subprocess.check_output(cmd),dtype='<f4').reshape(-1,2)
    return pcm,path,cmd

class Composer:
    def __init__(self):
        clean=Image.open(FRAME).convert('RGB')
        self.toolbar=clean.crop((550,48,1064,120))
        # Empty region at the same grid phase: 1064 = 7 x 152-pixel 4-bar periods.
        tile=clean.crop((1661,TOP,1813,BOTTOM))
        self.empty=Image.new('RGB',(RIGHT-LEFT,BOTTOM-TOP))
        for x in range(0,RIGHT-LEFT,152):self.empty.paste(tile,(x,0))
        self.pcm,self.audio_path,self.audio_command=source_audio()
        self.last=LEFT
        self.positions=[]

    def compose(self,frame,t):
        original=frame.copy()
        frame.paste(self.toolbar,(550,48))  # remove the entire source tooltip/cursor
        frame.paste(self.empty,(LEFT,TOP))
        active=START<=t<START+TAKE
        expected=267+(SOURCE_IN+t-1.97734375)*(76/3)
        lo,hi=max(267,int(expected)-14),min(1948,int(expected)+15)
        row=np.asarray(original)[215,lo:hi,:]
        hit=np.flatnonzero(row.mean(axis=1)<70)+lo
        measured=float(hit.mean()) if len(hit) else expected
        edge=min(RIGHT,max(LEFT,round(measured))) if t>=START else LEFT
        self.last=max(self.last,edge)
        edge=self.last
        d=ImageDraw.Draw(frame)
        # Preserve the Playing button state at the small overlap with that patch.
        d.rounded_rectangle((550,10,595,53),radius=4,fill=(21,24,22),outline=(170,176,171),width=1)
        d.rectangle((566,23,571,40),fill=(250,251,248))
        d.rectangle((577,23,582,40),fill=(250,251,248))
        if t>=START+TAKE:
            frame.paste(original.crop((LEFT,TOP,RIGHT,BOTTOM)),(LEFT,TOP))
            edge=RIGHT
        elif edge>LEFT:
            frame.paste(original.crop((LEFT,TOP,edge,BOTTOM)),(LEFT,TOP))
            d.rectangle((LEFT,TOP,edge-1,TOP+26),fill=(239,220,217))
            if edge-LEFT>114:
                d.ellipse((LEFT+8,TOP+10,LEFT+14,TOP+16),fill=RECORD)
                d.text((LEFT+22,TOP+4),'Recording',font=FONT,fill=(25,30,29))
            d.rectangle((LEFT,TOP,edge-1,BOTTOM-1),outline=RECORD,width=1)
            d.line((edge-1,TOP,edge-1,BOTTOM-1),fill=RECORD,width=2)
        if active:
            d.rounded_rectangle((657,11,699,52),radius=4,fill=(246,227,224),outline=RECORD,width=1)
            d.ellipse((671,22,688,39),fill=RECORD)
            d.rectangle((0,1445,290,H-1),fill=(240,241,236))
            d.ellipse((20,1465,28,1473),fill=RECORD)
            d.text((37,1459),'Recording',font=FONT,fill=(65,70,68))
            n=max(0,int((t-START)*48000))
            block=self.pcm[n:min(n+1600,len(self.pcm))]
            peaks=np.max(np.abs(block),axis=0) if len(block) else np.zeros(2)
            db=20*np.log10(np.maximum(peaks,1e-6))
            # Feedback derived from the preserved source, not the silent recording.
            d.rectangle((25,1307,253,1349),fill=(232,233,228))
            d.text((27,1311),f'IN {max(-60.,float(db.max())):.1f} dB',font=SMALL,fill=(84,88,84))
            for c in range(2):
                y=1337+c*6
                d.rectangle((27,y,251,y+2),fill=(204,209,204))
                width=round(224*max(0.,min(1.,(float(db[c])+60)/60)))
                if width:d.rectangle((27,y,27+width,y+2),fill=(87,135,120))
        self.positions.append(dict(t=round(t,4),edge=edge,playhead=round(measured,3),active=active))
        return frame

def exact(stream,n):
    b=bytearray()
    while len(b)<n:
        p=stream.read(n-len(b))
        if not p:raise EOFError(f'{len(b)} / {n}')
        b.extend(p)
    return b

def render():
    (OUT/'stills').mkdir(exist_ok=True)
    (OUT/'logs').mkdir(exist_ok=True)
    c=Composer(); source_sha=sha(SOURCE); project_sha=sha(PROJECT)
    main=OUT/'sax-recording-workspace-36s-1080p.mp4'
    detail=OUT/'sax-recording-closeup-36s.mp4'
    decode=[str(FFMPEG),'-v','error','-ss',str(SOURCE_IN),'-i',str(SOURCE),'-t',str(SECONDS),'-an','-vf','fps=30','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    filters='[0:v]split[main][detail];[main]scale=1856:1080:flags=lanczos,pad=1920:1080:32:0:color=0xf7f8f4[m];[detail]crop=896:140:590:1266,scale=1280:200:flags=lanczos[d]'
    encode=[str(FFMPEG),'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-filter_complex',filters]
    for map_name,path in [('[m]',main),('[d]',detail)]:
        encode+=['-map',map_name,'-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(path)]
    sample={0,30,120,300,540,900,1079}
    with (OUT/'logs/decode.log').open('wb') as dl,(OUT/'logs/encode.log').open('wb') as el:
        reader=subprocess.Popen(decode,stdout=subprocess.PIPE,stderr=dl)
        writer=subprocess.Popen(encode,stdin=subprocess.PIPE,stderr=el)
        try:
            for i in range(SECONDS*FPS):
                frame=Image.frombytes('RGB',(W,H),bytes(exact(reader.stdout,W*H*3)))
                frame=c.compose(frame,i/FPS)
                if i in sample:
                    frame.save(OUT/'stills'/f'workspace-{i/FPS:05.2f}s.png')
                    frame.crop((590,1266,1486,1406)).resize((1280,200),Image.Resampling.LANCZOS).save(OUT/'stills'/f'closeup-{i/FPS:05.2f}s.png')
                writer.stdin.write(frame.tobytes())
                if i%300==0:print(f'rendered {i}/{SECONDS*FPS} frames',flush=True)
            writer.stdin.close(); assert writer.wait(timeout=60)==0
            reader.stdout.close();assert reader.wait(timeout=30)==0
        except BaseException:
            reader.kill();writer.kill();reader.wait();writer.wait();raise
    assert sha(SOURCE)==source_sha and sha(PROJECT)==project_sha
    write(OUT/'FRONTIER.json',c.positions)
    write(OUT/'MANIFEST.json',dict(created_at=datetime.now(timezone.utc).isoformat(),
        kind='post-production recording visualization; not live DAW capture',source=str(SOURCE),source_sha256=source_sha,
        original_source_audio='all-zero AAC; not used',project=str(PROJECT),project_sha256=project_sha,
        waveform='actual original clip pixels progressively revealed',meter_source=str(c.audio_path),meter_source_sha256=sha(c.audio_path),
        seconds=SECONDS,fps=FPS,frames=SECONDS*FPS,source_in=SOURCE_IN,take_start=START,take_seconds=TAKE,
        commands=[c.audio_command,decode,encode],files=[dict(file=p.name,sha256=sha(p),bytes=p.stat().st_size)for p in [main,detail]]))
    print('Rendered two silent visualization assets.',flush=True)

def verify():
    m=json.loads((OUT/'MANIFEST.json').read_text(encoding='utf-8'))
    positions=json.loads((OUT/'FRONTIER.json').read_text(encoding='utf-8'))
    assert len(positions)==1080
    assert all(a['edge']<=b['edge']for a,b in zip(positions,positions[1:]))
    assert positions[0]['edge']==LEFT and positions[-1]['edge']==RIGHT
    errors=[abs(p['edge']-p['playhead'])for p in positions if p['active'] and LEFT+2<p['edge']<RIGHT-2]
    assert max(errors)<5, max(errors)
    for f,size in zip(m['files'],[(1920,1080),(1280,200)]):
        p=OUT/f['file']; probe=json.loads(subprocess.check_output([str(FFPROBE),'-v','error','-show_streams','-show_format','-of','json',str(p)]))
        assert len(probe['streams'])==1
        v=probe['streams'][0]
        assert (v['width'],v['height'])==size and v['r_frame_rate']=='30/1'
        assert int(v['nb_frames'])==1080 and abs(float(probe['format']['duration'])-36)<.001
        subprocess.run([str(FFMPEG),'-v','error','-i',str(p),'-f','null','-'],check=True,stdout=subprocess.DEVNULL)
        assert sha(p)==f['sha256']
    assert sha(SOURCE)==m['source_sha256'] and sha(PROJECT)==m['project_sha256']
    assert sha(m['meter_source'])==m['meter_source_sha256']
    report=dict(status='passed',files=2,seconds_each=36,frames_each=1080,full_decode=True,
        silence_intentional=True,monotonic_frontier=True,max_playhead_alignment_error_px=max(errors),source_project_and_audio_unchanged=True)
    write(OUT/'VALIDATION.json',report);print(json.dumps(report),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['render','verify'],default='render');p.add_argument('--record',action='store_true');a=p.parse_args()
    if a.record:
        from dev import Recorder
        Recorder('sax-material-'+a.mode,'30fps/36s/silent/post-production',
                 'User-requested recording visualization from original playback pixels; no DAW operation or live-input claim.').execute([sys.executable,str(Path(__file__).resolve()),'--mode',a.mode])
    elif a.mode=='render':render()
    else:verify()
