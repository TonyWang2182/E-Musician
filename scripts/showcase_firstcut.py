"""Prepare evidence-backed editorial inserts and a deliberately incomplete shot map.

No application pixels are painted, task completion simulated, or recording
waveforms animated here. Stopped screenshots are composited as editorial stills.
"""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

from showcase_assemble import digest, execute, probe, write, audio_volume

FFMPEG=Path('E:/SUMIN/ABC_Ocean/_tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe')
FFPROBE=Path('E:/Users/28712/AppData/Local/Programs/Audio Jam/lib/win32/ffprobe.exe')
KIT=Path('E:/MusicAgent&DAW/demo-video/showcase-v1')


def render(kit, only_vst=False):
    out=kit/'captures/editorial';out.mkdir(parents=True,exist_ok=True)
    logs=out/'logs';logs.mkdir(exist_ok=True);records=[];inputs={}
    folder=kit/'captures/demo4'
    selected=json.loads((folder/'selected-final-manifest.json').read_text())
    for item in selected['selected']:
        p=folder/item['file'];assert digest(p)==item['sha256'];inputs[str(p)]=item['sha256']

    def montage(name,images,crop,duration):
        parts=[]
        for i,entry in enumerate(images):
            image,seconds=entry[:2]
            src=folder/image;x,y,w,h=entry[2] if len(entry)>2 else crop
            target=out/f'{name}-{i+1:02}.mp4'
            # A restrained push-in adds editorial movement to a documented still.
            n=round(seconds*30);filters=f"crop={w}:{h}:{x}:{y},scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xe5e9e9,setsar=1,zoompan=z='1+0.018*min(on/{n-1},1)':x='iw/2-iw/(2*zoom)':y='ih/2-ih/(2*zoom)':d=1:s=1920x1080:fps=30,format=yuv420p"
            execute([FFMPEG,'-y','-v','error','-loop','1','-framerate','30','-i',src,'-vf',filters,'-t',seconds,'-an','-c:v','libx264','-preset','fast','-crf','18','-r','30',target],logs/f'{name}-{i+1:02}.log',records)
            parts.append(target)
        concat=out/f'{name}.txt';concat.write_text(''.join("file '"+p.as_posix()+"'\n" for p in parts))
        target=out/f'{name}-1080p30.mp4'
        execute([FFMPEG,'-y','-v','error','-f','concat','-safe','0','-i',concat,'-c','copy','-movflags','+faststart',target],logs/f'{name}-concat.log',records)
        assert abs(float(probe(FFPROBE,target)['format']['duration'])-duration)<.04
        return target

    montage('D402-piano-rolls',[('33-main-drum-piano-verified.png',2.5),('30-ep-piano-final.png',2.5),('35-ep-keyscape-editor.png',3,(0,0,1972,1138))],(288,238,1476,678),8)
    if not only_vst:
        montage('D406-effects',[('25-eq-final.png',3),('22-compressor-final.png',3),('26-filter-final.png',3),('27-reverb-final.png',3)],(288,498,1476,419),12)

    sax=folder/'16-lower-tracks.png';inputs[str(sax)]=digest(sax)
    abstract=kit/'motion/sax-abstract-1080p30.mp4';inputs[str(abstract)]=digest(abstract)
    target=out/'D403-sax-split-1080p30.mp4'
    # The older capture is independently reviewed only within this pixel crop.
    # Its erroneous footer is below y=936 and is not present in the result.
    # No R button, input meter, transport state or waveform is changed.
    graph=("color=c=0xe8edee:s=1056x1080:r=30:d=9[paper];"
           "[0:v]crop=1458:676:289:216,scale=1016:-2,setsar=1[track];"
           "[paper][track]overlay=20:(H-h)/2[left];"
           "[1:v]scale=-2:1080,crop=864:1080:600:0,setsar=1[right];"
           "[left][right]hstack=inputs=2,format=yuv420p[v]")
    if not only_vst:
        execute([FFMPEG,'-y','-v','error','-loop','1','-framerate','30','-i',sax,'-i',abstract,'-filter_complex',graph,'-map','[v]','-t','9','-an','-c:v','libx264','-preset','fast','-crf','18','-r','30','-movflags','+faststart',target],logs/'D403-sax-split.log',records)
    previous=json.loads((out/'COMPOSITE-MANIFEST.json').read_text()) if only_vst else None
    outputs=[x for x in previous['outputs'] if 'D402' not in x['path']] if previous else []
    names=('D402-piano-rolls',) if only_vst else ('D402-piano-rolls','D403-sax-split','D406-effects')
    for name in names:
        p=out/f'{name}-1080p30.mp4'
        execute([FFMPEG,'-v','error','-i',p,'-f','null','-'],logs/f'{name}-decode.log',records)
        info=probe(FFPROBE,p);v=next(s for s in info['streams'] if s['codec_type']=='video')
        assert (v['width'],v['height'],v['avg_frame_rate'])==(1920,1080,'30/1')
        assert int(v['nb_frames'])==round(float(info['format']['duration'])*30)
        for t in (1,float(info['format']['duration'])-1):
            png=out/f'{name}-{t:g}s.png'
            execute([FFMPEG,'-y','-v','error','-ss',t,'-i',p,'-frames:v','1',png],logs/f'{name}-{t:g}s.log',records)
        outputs.append({'path':str(p),'sha256':digest(p),'probe':info})
    write(out/'COMPOSITE-MANIFEST.json',{'created':datetime.now(timezone.utc).isoformat(),'status':'technical-verification-passed','real_recording_pending':True,'application_interaction_captured':False,'microphone_recording_captured':False,'inputs':inputs,'outputs':outputs,'records':(previous['records'] if previous else [])+records,'sax_crop':{'source':str(sax),'rectangle_xywh':[289,216,1458,676],'source_kind':'actual stopped DAW screenshot','excluded_footer':True,'audio_evidence':'existing project render only','person_video':'not supplied; abstract graphic only'},'d402_segments':[{'from':0,'to':2.5,'source':'33-main-drum-piano-verified.png'},{'from':2.5,'to':5,'source':'30-ep-piano-final.png'},{'from':5,'to':8,'source':'35-ep-keyscape-editor.png','track':'EP','preset':'Rhodes - LA Custom Suitcase'}],'notes':['D402 includes the actual loaded Keyscape editor from the EP track, after both real piano rolls.','D403 shows an existing sax clip, not an incoming recording. Replace with genuine recording/performer footage before claiming a live take.','D406 uses real static effect panels; no audible parameter adjustment is claimed.']})


def draft(kit):
    data=json.loads((kit/'scripts/shot-map-template.json').read_text());shots={s['id']:s for s in data['shots']}
    df=kit/'captures/demo4';ed=kit/'captures/editorial'
    for id,file in {'D401':'29-arrangement-final.png','D404':'32-sampler-verified.png','D405':'21-rack-final.png','D407':'29-arrangement-final.png'}.items():
        shots[id].update(media=str(df/file),kind='image',capture_kind='actual-stopped-native-ui',crop=[288,130,1476,787],zoom=[1,1.025])
    for id,file in {'D402':'D402-piano-rolls','D403':'D403-sax-split','D406':'D406-effects'}.items():
        shots[id].update(media=str(ed/f'{file}-1080p30.mp4'),kind='video',crop=None,zoom=[1,1],capture_kind='editorial composite of actual stopped UI')
    shots['D403']['pending_real_recording']=True
    shots['D403']['does_not_show']=['live input','growing recording waveform','person performing']
    shots['D402']['pending_loaded_vst_editor']=False
    shots['D402']['vst_editor_source']={'path':str(df/'35-ep-keyscape-editor.png'),'track':'EP','preset':'Rhodes - LA Custom Suitcase','source_kind':'actual native plugin editor capture'}
    for s in data['shots']:
        s['picture_status']='pending-real-capture' if s['media'] is None else 'available'

    # Bind sound to the successful, separately documented export runs.
    accepted={}
    for runid,mode in [('960d48c37d61','demo4'),('0fd220ba9275','d3'),('89f4b0bd8dc5','d2')]:
        d=json.loads((kit/f'audio/evidence/{runid}/summary.json').read_text())
        r=next(x for x in d['runs'] if x['mode']==mode)
        assert r['status']=='passed';a=r['audio'];assert digest(a['path'])==a['sha256']
        accepted[mode]={'path':a['path'],'sha256':a['sha256'],'evidence':str(kit/f'audio/evidence/{runid}/summary.json'),'seconds':a['seconds'],'physical_device_used':r['physical_device_used'],'listening_acceptance':r['listening_acceptance']}
    audio=[]
    def add(label,media,start,source,duration,gain,fi=.04,fo=.08,**kw):
        p=Path(media);assert p.is_file()
        row={'label':label,'media':str(p),'timeline_start':start,'source_in':source,'duration':duration,'gain_db':gain,'fade_in':fi,'fade_out':fo,**kw}
        audio.append(row);return row
    original=accepted['demo4']['path'];piano=accepted['d3']['path'];results=kit/'workspace/results'
    add('Opening bed: original composition',original,0,0,18,-8,.6,.7)
    for name,start in [('yue',31),('ace',49)]:
        p=results/name/'audio.wav';r=json.loads((results/name/'result.json').read_text());assert digest(p)==r['audio']['sha256']
        add(f'{name} preview',p,start,4,6,-4)
    # A common source clock starts at source second 6 when film second 80 begins.
    separation=json.loads((results/'separate/result.json').read_text())
    for name,start in [('drums',80),('bass',83.5),('other',87),('vocals',90.5)]:
        p=results/'separate'/f'{name}.wav';r=next(x for x in separation['stems'] if x['name']==name);assert digest(p)==r['sha256']
        add(f'SCNet cumulative {name}',p,start,6+(start-80),94-start,-6,.02,.08,source_clock='source_seconds = film_seconds - 74')
    newlight=kit/'workspace/projects/media/New-Light.wav'
    add('New Light source audition',newlight,94,0,5,-5)
    add('New Light under chord inspection',newlight,114,0,8,-14)
    add('Actual New Light Warp output, project 120 BPM',accepted['d2']['path'],135,.25,7,-5,source_clock='DAW render starts at timeline zero; accepted warped clip starts at 0.25 seconds')
    add('Tea for Two original piano',kit/'workspace/projects/media/Tea-for-Two.wav',142,0,6,-10)
    add('Actual Keyscape MIDI output (source audio muted)',piano,161,0,7,8)
    # One continuous 60-second source clock for the whole D4 chapter.
    nm=json.loads((kit/'narration/NARRATION-MANIFEST.json').read_text())
    envelope={0.0:0.0,60.0:0.0}
    for voice in nm['entries']:
        if not voice['id'].startswith('D4'):continue
        lo=max(0.0,voice['start']-168);hi=min(60.0,voice['end']-168)
        envelope[round(max(0,lo-.18),5)]=0.0;envelope[round(lo,5)]=-8.0
        envelope[round(hi,5)]=-8.0;envelope[round(min(60,hi+.35),5)]=0.0
    env=[{'time':k,'gain_db':v} for k,v in sorted(envelope.items())]
    bed=add('Continuous current test drive mix',original,168,0,60,4,.04,.15,gain_envelope=env,source_clock='source_seconds = film_seconds - 168; no cuts/restarts')
    audio_volume(bed)
    add('Closing bed: original composition tail',original,228,48,12,-8,.7,3)
    data['audio']=audio
    data['accepted_audio']=accepted
    data['missing_audio']=[]
    data['pending_shots']=[s['id'] for s in data['shots'] if s['media'] is None]
    data['status']='editorial-draft-with-explicit-missing-picture'
    data['internal_notes']=['Root owns the final shot map; this file will not overwrite it.','All D4 UI is stopped-frame editorial imagery, not live transport/recording evidence.','D4 sound is one accepted current project render, with smooth loudness ducking only.','D3 sound is the accepted realtime export, not rejected fast export, not original source piano.','No inference calls, cloud connection, new model inference or synthetic human footage were used.','Music gains are editorial starting points; final listening/balance acceptance remains.']
    target=kit/'scripts/shot-map-firstcut-draft.json';write(target,data)
    write(kit/'scripts/audio-timeline-draft.json',{'narration':data['narration'],'duration':240,'audio':audio,'missing_audio':data['missing_audio'],'accepted_audio':accepted,'notes':data['internal_notes']})
    lines=['# First-cut audio and capture handoff','','This is an editorial handoff, not a claim of new model inference or physical recording.','','| Timeline | Sound | Source in | Gain |','|---|---|---:|---:|']
    for a in audio:lines.append(f"| {a['timeline_start']:g}–{a['timeline_start']+a['duration']:g}s | {a['label']} | {a['source_in']:g}s | {a['gain_db']:+g} dB{' with voice ducking' if a.get('gain_envelope') else ''} |")
    lines+=['','## Required before final acceptance','', '- Replace null picture paths for O02 and D1–D3 with actual captures.', '- Add the real Warp audio output for W03 (135–142s); the current draft does not fake it.', '- D403 is a crop of an existing sax track plus abstract sax motion. It does not prove recording. Replace it with the user’s real recording/performer footage to demonstrate the process.', '- D402 now includes both real piano rolls followed by the actual EP Keyscape editor (Rhodes - LA Custom Suitcase).', '- Keep D4 source clock continuous from 0 to 60s at film 168–228s. The sampler detail occurs after its audible 15–18s trigger; do not imply a live trigger at the later close-up.', '- Verify final listening balance and audition/source-picture synchronization. Technical checks are not hearing acceptance.', '', '## Source provenance', '', f"- D4: `{accepted['demo4']['sha256']}`; successful run 960d48c37d61.",f"- D3: `{accepted['d3']['sha256']}`; successful run 0fd220ba9275. The no-MIDI control was silent.",f"- D2 Warp: `{accepted['d2']['sha256']}`; successful run 89f4b0bd8dc5, actual clip start 0.25s.",'- Never use `d3-keyscape-midi-only.wav`; that fast export failed its attribution control.','', '## Gain envelope schema','', '`gain_envelope` is an ordered list of `{time, gain_db}` covering 0 through the cut duration. Its dB values are added to `gain_db`, with continuous interpolation. It changes level without restarting/retiming the source.','']
    (kit/'scripts/FIRST-CUT-HANDOFF.md').write_text('\n'.join(lines),encoding='utf-8')
    shutil.copy2(__file__,kit/'motion/source/showcase_firstcut.py')
    shutil.copy2(Path(__file__).with_name('showcase_assemble.py'),kit/'motion/source/showcase_assemble.py')
    print(f'Draft written: {target}; {len(data["pending_shots"])} picture entries pending; actual Warp audio mapped')


def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['render','vst','draft'],required=True);p.add_argument('--kit',type=Path,default=KIT);a=p.parse_args()
    if a.mode=='vst':render(a.kit,only_vst=True)
    else:(render if a.mode=='render' else draft)(a.kit)

if __name__=='__main__':main()
