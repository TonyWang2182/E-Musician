"""Assemble the fixed 240-second film from explicitly mapped real local captures.

Missing picture or sound sources fail preflight. This tool never draws a DAW UI,
recording waveform, button state or task progress. Images are identified as image
sources in the report; a finished file is not evidence of live model inference.
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

from showcase_motion import SHOTS


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def local(base,value):
    if not value:raise ValueError('Missing media path; supply an actual capture rather than a placeholder')
    p=Path(value)
    if not p.is_absolute():p=base/p
    p=p.resolve()
    if not p.is_file():raise FileNotFoundError(p)
    return p


def probe(ffprobe,path):
    return json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(path)]))


def execute(args,log,records):
    begin=datetime.now(timezone.utc).isoformat()
    p=subprocess.run([str(v) for v in args],capture_output=True)
    log.write_bytes(p.stdout+p.stderr)
    records.append({'command':[str(v) for v in args],'started':begin,'finished':datetime.now(timezone.utc).isoformat(),'exit_code':p.returncode,'log':str(log)})
    if p.returncode:raise RuntimeError(f'Command failed ({p.returncode}); see {log}')


def audio_volume(item):
    """Optional smooth gain envelope, in seconds relative to this one source cut.

    The envelope changes loudness only; it never restarts or retimes the source.
    Values are additional dB relative to gain_db and interpolate in dB.
    """
    base=float(item.get('gain_db',0));points=item.get('gain_envelope')
    if not points:return f'volume={base}dB'
    duration=float(item['duration']);last=-1.0
    for point in points:
        t=float(point['time']);g=float(point['gain_db'])
        if not 0<=t<=duration or t<=last or not -60<=g<=12:raise ValueError('Invalid audio gain envelope point')
        last=t
    if len(points)<2 or abs(float(points[0]['time']))>1e-9 or abs(float(points[-1]['time'])-duration)>1e-6:
        raise ValueError('Gain envelope must cover the full cut from time zero to its duration')
    expression=str(float(points[-1]['gain_db']))
    for left,right in reversed(list(zip(points,points[1:]))):
        t0,t1=float(left['time']),float(right['time']);g0,g1=float(left['gain_db']),float(right['gain_db'])
        part=f'({g0}+({g1-g0})*(t-{t0})/{t1-t0})'
        expression=f'if(lt(t,{t1}),{part},{expression})'
    return f"volume='pow(10,({base}+({expression}))/20)':eval=frame"


def no_narration_companion(a, data, audios, picture, work, logs, records):
    """Reuse the encoded picture stream and mix only explicitly mapped music.

    No voice input or subtitle stream is opened. Voice-ducking envelopes are
    removed, while source clocks, cut lengths, fades and base gains are retained.
    An optional per-cut no_narration_gain_db overrides its base gain.
    """
    output=a.no_narration_output
    if not audios:raise ValueError('A no-narration companion requires actual mapped audio')
    args=[a.ffmpeg,'-y','-v','error','-i',picture]
    for _,src in audios:args+=['-i',src]
    filters=[];labels=[];used=[]
    for i,(item,src) in enumerate(audios,1):
        clean=dict(item);clean.pop('gain_envelope',None)
        clean['gain_db']=float(item.get('no_narration_gain_db',item.get('gain_db',0)))
        if not -60<=clean['gain_db']<=12:raise ValueError('Invalid no-narration gain')
        d=float(item['duration']);off=float(item.get('source_in',0));delay=round(item['timeline_start']*1000)
        fi=min(float(item.get('fade_in',.02)),d/2);fo=min(float(item.get('fade_out',.02)),d/2);label=f'music{i}'
        filters.append(f'[{i}:a]atrim=start={off}:duration={d},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{audio_volume(clean)},afade=t=in:st=0:d={fi},afade=t=out:st={d-fo}:d={fo},adelay={delay}|{delay}[{label}]')
        labels.append('['+label+']');used.append({'media':str(src),'sha256':digest(src),'timeline_start':item['timeline_start'],'source_in':off,'duration':d,'gain_db':clean['gain_db']})
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95:level=0,apad,atrim=duration=240[mix]')
    output.parent.mkdir(parents=True,exist_ok=True)
    args+=['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[mix]','-c:v','copy','-c:a','aac','-b:a','320k','-t','240','-movflags','+faststart',output]
    start=len(records);execute(args,logs/'no-narration-mix.log',records)
    p=probe(a.ffprobe,output);assert abs(float(p['format']['duration'])-240)<.05
    v=next(s for s in p['streams'] if s['codec_type']=='video')
    assert int(v.get('nb_frames',0))==7200,'No-narration video must contain all 7200 frames'
    assert not any(s['codec_type']=='subtitle' for s in p['streams'])
    execute([a.ffmpeg,'-v','error','-i',output,'-f','null','-'],logs/'no-narration-decode.log',records)
    # Packet hash confirms the companion copied the same picture, not a new edit.
    hashes=[]
    for name,path in [('picture',picture),('no-narration',output)]:
        target=work/f'{name}-video-stream.sha256'
        execute([a.ffmpeg,'-y','-v','error','-i',path,'-map','0:v:0','-c','copy','-f','hash','-hash','sha256',target],logs/f'{name}-video-hash.log',records)
        hashes.append(target.read_text().strip())
    assert hashes[0]==hashes[1],'Companion picture packets must match the primary picture'
    result={'status':'passed','output':str(output),'sha256':digest(output),'source_map':str(a.map),'narration_included':False,'subtitles_included':False,'voice_ducking_removed':True,'source_clock_retained':True,'picture_reencoded':False,'video_stream_hash':hashes[0],'technical_probe':p,'audio_sources':used,'records':records[start:],'note':'Music-only editorial companion. Same real audio cuts and picture; no replacement inference or physical recording.'}
    write(work/'NO-NARRATION-RESULT.json',result)
    print(f'Assembled music-only companion without picture re-render: {output}',flush=True)
    return {'output':str(output),'sha256':result['sha256'],'result':str(work/'NO-NARRATION-RESULT.json')}


def template(path,kit):
    rows=[]
    transitions=dict(zip(('G01','S01','C01','W01','T01','D401'),('generation','separation','harmony','timing','transcription','workspace')))
    narration_manifest=kit/'narration/NARRATION-MANIFEST.json'
    spoken={e['id']:e for e in json.loads(narration_manifest.read_text())['entries']} if narration_manifest.exists() else {}
    for r in SHOTS:
        name='opener' if r[0]=='O01' else 'closer' if r[0]=='E01' else None
        rows.append({'id':r[0],'start':r[1],'end':r[2],
            'media':str(kit/'motion'/f'{name}-1080p30.mp4') if name else None,
            'kind':'video' if name else 'image','source_in':0,'playback_rate':1,
            'crop':None,'zoom':[1,1] if name else [1,1.035],
            'focus_start':[.5,.5],'focus_end':[.5,.5],
            'allow_last_frame_hold':False,'chapter_title':None,
            'background_intro':({'media':str(kit/'motion'/f'chapter-{list(transitions).index(r[0])+1:02}-{transitions[r[0]]}-1080p30.mp4'),'duration':.6} if r[0] in transitions else None),
            'planned_picture':r[5],'voiceover_clip':str(kit/'narration/clips'/f'{r[0]}.wav') if r[3] else None,
            'voice_window':([spoken[r[0]]['start'],spoken[r[0]]['end']] if r[0] in spoken else None),
            'available_silence_after_voice':(round(r[2]-spoken[r[0]]['end'],3) if r[0] in spoken else r[2]-r[1]),
            'narration_text':r[3],'audition_only':not bool(r[3])})
    data={'schema_version':1,'width':1920,'height':1080,'fps':30,'duration':240,
          'narration':str(kit/'narration/voice-en-240s-48k.wav'),
          'subtitles':str(kit/'narration/voice-en.srt'),
          'narration_gain_db':0,'shots':rows,'audio':[],
          'notes':'Replace every null media with a real local screenshot/video. Insert chapter backgrounds as recorded-edit footage, or add an optional title. Audio entries: media, timeline_start, source_in, duration, gain_db, fade_in, fade_out. Add actual audition sound separately; no source audio is implicitly copied from screen captures. Do not replace MIDI playback with the original piano recording.'}
    write(path,data)
    print(f'Template written: {path}; missing captures are intentionally not filled')


def assemble(a):
    data=json.loads(a.map.read_text(encoding='utf-8-sig'));base=a.map.parent
    assert [data.get(k) for k in ('width','height','fps','duration')]==[1920,1080,30,240]
    actual=data['shots'];assert len(actual)==len(SHOTS),'The 31-shot map must be complete'
    checked=[];sources={};missing=[]
    for item,ref in zip(actual,SHOTS):
        if (item['id'],item['start'],item['end'])!=(ref[0],ref[1],ref[2]):raise ValueError(f"Timeline differs at {ref[0]}")
        try:src=local(base,item.get('media'))
        except (FileNotFoundError,ValueError) as e:missing.append(f"{item['id']}: {e}");continue
        if src==a.output.resolve():raise ValueError('Output must not overwrite a source')
        p=probe(a.ffprobe,src);v=next((s for s in p['streams'] if s['codec_type']=='video'),None)
        if not v:raise ValueError(f'No picture stream: {src}')
        kind=item.get('kind','video');assert kind in ('image','video')
        if kind=='image' and src.suffix.lower() not in ('.png','.jpg','.jpeg','.bmp','.webp'):raise ValueError('Image source must be a still-image file')
        duration=item['end']-item['start'];rate=float(item.get('playback_rate',1));assert .25<=rate<=16
        offset=float(item.get('source_in',0));assert offset>=0
        available=float(p.get('format',{}).get('duration',duration))-offset
        if kind=='video' and available+.04<duration*rate and not item.get('allow_last_frame_hold',False):raise ValueError(f"{item['id']} video is shorter than mapped time; choose an adequate take or explicitly allow last-frame hold")
        crop=item.get('crop')
        if crop:
            assert len(crop)==4 and all(isinstance(n,int) for n in crop)
            x,y,w,h=crop;assert x>=0 and y>=0 and w>0 and h>0 and x+w<=v['width'] and y+h<=v['height']
        zoom=item.get('zoom',[1,1]);assert len(zoom)==2 and all(1<=z<=1.5 for z in zoom)
        for key in ('focus_start','focus_end'):assert len(item.get(key,[.5,.5]))==2 and all(0<=z<=1 for z in item.get(key,[.5,.5]))
        transition=None
        if item.get('background_intro'):
            transition=local(base,item['background_intro'].get('media'))
            td=float(item['background_intro']['duration']);assert 0<td<=min(2,duration-1)
            tp=probe(a.ffprobe,transition);assert float(tp['format']['duration'])>=td
            sources[str(transition)]={'sha256':digest(transition),'kind':'chapter background'}
        checked.append((item,src,v,transition));sources[str(src)]={'sha256':digest(src),'kind':kind}
    voice=local(base,data['narration']);vp=probe(a.ffprobe,voice)
    assert abs(float(vp['format']['duration'])-240)<.05,'Narration must retain its complete 240-second timeline'
    sources[str(voice)]={'sha256':digest(voice),'kind':'narration'}
    subtitles=local(base,data['subtitles']) if data.get('subtitles') else None
    if subtitles:sources[str(subtitles)]={'sha256':digest(subtitles),'kind':'English captions'}
    audios=[]
    for item in data.get('audio',[]):
        src=local(base,item.get('media'));p=probe(a.ffprobe,src)
        if not any(s['codec_type']=='audio' for s in p['streams']):raise ValueError(f'No audio stream: {src}')
        lo=float(item['timeline_start']);duration=float(item['duration']);offset=float(item.get('source_in',0))
        assert 0<=lo<240 and duration>0 and lo+duration<=240.01 and offset>=0
        assert offset+duration<=float(p['format']['duration'])+.04
        assert -60<=float(item.get('gain_db',0))<=12
        audio_volume(item)  # Validate optional envelope before any expensive render.
        audios.append((item,src));sources[str(src)]={'sha256':digest(src),'kind':'audio'}
    for pending in data.get('missing_audio',[]):
        missing.append(f"Audio {pending.get('shot','unknown')}: {pending.get('requirement','unresolved source')}")
    if missing:raise ValueError('Media preflight failed:\n'+'\n'.join(missing))
    if not audios and not a.allow_voice_only:raise ValueError('No music/audio mapped. Add the real audition/production audio, or explicitly use --allow-voice-only for an editorial review')
    companion=getattr(a,'no_narration_output',None)
    if companion:
        if not audios:raise ValueError('No-narration output requires at least one actual audio item')
        if companion.resolve()==a.output.resolve() or str(companion.resolve()) in sources:raise ValueError('No-narration output must be separate from primary output and all sources')
        if companion.exists() and not a.overwrite:raise FileExistsError(f'{companion}: use a new file or --overwrite')
        for item,_ in audios:
            if not -60<=float(item.get('no_narration_gain_db',item.get('gain_db',0)))<=12:raise ValueError('Invalid no-narration gain')
    work=a.output.parent/(a.output.stem+'-work');logs=work/'logs';logs.mkdir(parents=True,exist_ok=True)
    write(work/'PREFLIGHT.json',{'status':'passed','sources':sources,'map_sha256':digest(a.map),'note':'Mapped stills remain stills; this is an edit, not new DAW interaction evidence.'})
    if a.check_only:print('Preflight passed; no video rendered');return
    if a.output.exists() and not a.overwrite:raise FileExistsError(f'{a.output}: use a new file or --overwrite')
    previous_shots={};previous_sources={}
    if getattr(a,'reuse_unchanged_segments',False):
        if not a.previous_map:raise ValueError('Segment reuse requires the saved previous map')
        previous=json.loads(a.previous_map.read_text(encoding='utf-8-sig'))
        previous_shots={r['id']:r for r in previous['shots']}
        previous_result=json.loads((work/'RESULT.json').read_text())
        assert previous_result['status']=='passed'
        previous_sources=previous_result['sources']
    records=[];segments=[]
    for item,src,v,transition in checked:
        id=item['id'];duration=item['end']-item['start'];n=duration*30;kind=item.get('kind','video');rate=float(item.get('playback_rate',1));offset=item.get('source_in',0)
        dst=work/(id+'.mp4');args=[a.ffmpeg,'-y','-hide_banner','-loglevel','error']
        if previous_shots.get(id)==item and dst.is_file() and previous_sources.get(str(src),{}).get('sha256')==digest(src) and (not transition or previous_sources.get(str(transition),{}).get('sha256')==digest(transition)):
            cached=probe(a.ffprobe,dst);cv=next(s for s in cached['streams'] if s['codec_type']=='video')
            assert abs(float(cached['format']['duration'])-duration)<.01 and int(cv['nb_frames'])==n
            records.append({'action':'reuse-unchanged-segment','shot':id,'segment':str(dst),'sha256':digest(dst),'previous_map':str(a.previous_map),'source_content_and_complete_shot_mapping_match':True})
            segments.append(dst);print('Reused verified segment '+id,flush=True);continue
        if kind=='image':args+=['-loop','1','-framerate','30','-i',src]
        else:args+=['-ss',str(offset),'-i',src]
        if transition:args+=['-i',transition]
        filters=[]
        if item.get('crop'):
            x,y,w,h=item['crop'];filters+=[f'crop={w}:{h}:{x}:{y}']
        filters+=['scale=1920:1080:force_original_aspect_ratio=decrease','pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x10181c','setsar=1']
        if kind=='video':filters += [f'setpts=(PTS-STARTPTS)/{rate}','fps=30']
        z0,z1=item.get('zoom',[1,1]);f0=item.get('focus_start',[.5,.5]);f1=item.get('focus_end',[.5,.5]);den=max(1,n-1)
        if z0!=1 or z1!=1:
            z=f'{z0}+({z1-z0})*min(on/{den},1)'
            fx=f'{f0[0]}+({f1[0]-f0[0]})*min(on/{den},1)';fy=f'{f0[1]}+({f1[1]-f0[1]})*min(on/{den},1)'
            filters += [f"zoompan=z='{z}':x='max(0,min(iw-iw/zoom,({fx})*iw-iw/(2*zoom)))':y='max(0,min(ih-ih/zoom,({fy})*ih-ih/(2*zoom)))':d=1:s=1920x1080:fps=30"]
        if item.get('chapter_title'):
            title=work/(id+'-title.txt');title.write_text(item['chapter_title'],encoding='utf-8')
            path=str(title).replace('\\','/').replace(':','\\:').replace("'", "\\'")
            filters += [f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':textfile='{path}':fontcolor=white:fontsize=46:box=1:boxcolor=black@0.65:boxborderw=16:x=80:y=h-135:enable='lt(t,2.5)'"]
        filters+=['tpad=stop_mode=clone:stop_duration=240',f'trim=duration={duration}','setpts=PTS-STARTPTS','format=yuv420p']
        if transition:
            td=float(item['background_intro']['duration'])
            # Replace the first td seconds rather than shifting all picture/audio sync.
            graph='[0:v]'+','.join(filters)+f',trim=start={td}:duration={duration-td},setpts=PTS-STARTPTS[screen];[1:v]trim=duration={td},setpts=PTS-STARTPTS,fps=30,scale=1920:1080,setsar=1,format=yuv420p[bg];[bg][screen]concat=n=2:v=1:a=0[vout]'
            args += ['-filter_complex',graph,'-map','[vout]']
        else:args += ['-vf',','.join(filters)]
        args += ['-t',str(duration),'-an','-c:v','libx264','-preset','fast','-crf','18','-r','30','-video_track_timescale','15360','-movflags','+faststart',dst]
        execute(args,logs/(id+'.log'),records);segments.append(dst);print('Rendered '+id,flush=True)
    concat=work/'segments.txt';concat.write_text(''.join("file '"+p.resolve().as_posix().replace("'","'\\''")+"'\n" for p in segments),encoding='utf-8')
    silent=work/'picture.mp4';execute([a.ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i',concat,'-c','copy',silent],logs/'picture-concat.log',records)
    args=[a.ffmpeg,'-y','-v','error','-i',silent,'-i',voice]
    for _,src in audios:args+=['-i',src]
    if subtitles:args+=['-i',subtitles]
    filters=[f"[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={float(data.get('narration_gain_db',0))}dB[voice]"]
    labels=['[voice]']
    for i,(item,_) in enumerate(audios,2):
        d=float(item['duration']);off=float(item.get('source_in',0));delay=round(item['timeline_start']*1000);fi=min(float(item.get('fade_in',.02)),d/2);fo=min(float(item.get('fade_out',.02)),d/2);label=f'a{i}'
        filters += [f'[{i}:a]atrim=start={off}:duration={d},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{audio_volume(item)},afade=t=in:st=0:d={fi},afade=t=out:st={d-fo}:d={fo},adelay={delay}|{delay}[{label}]']
        labels.append('['+label+']')
    filters += [''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95:level=0,apad,atrim=duration=240[mix]']
    args+=['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[mix]','-c:v','copy','-c:a','aac','-b:a','320k']
    if subtitles:args+=['-map',f'{2+len(audios)}:s:0','-c:s','mov_text','-metadata:s:s:0','language=eng','-disposition:s:0','default']
    args+=['-t','240','-movflags','+faststart',a.output]
    execute(args,logs/'final-mix.log',records)
    result=probe(a.ffprobe,a.output);assert abs(float(result['format']['duration'])-240)<.05
    final_video=next(s for s in result['streams'] if s['codec_type']=='video')
    assert int(final_video.get('nb_frames',0))==7200,'Final picture must contain all 7200 frames, not merely a 240-second audio tail'
    execute([a.ffmpeg,'-v','error','-i',a.output,'-f','null','-'],logs/'final-decode.log',records)
    companion_result=no_narration_companion(a,data,audios,silent,work,logs,records) if companion else None
    write(work/'RESULT.json',{'status':'passed','output':str(a.output),'sha256':digest(a.output),'source_map':str(a.map),'sources':sources,'technical_probe':result,'records':records,'image_shots':[r['id'] for r in actual if r.get('kind')=='image'],'no_narration_companion':companion_result,'note':'Technical assembly validation only. Human audio balance, actual recording claims, reading pace and final picture review remain editorial acceptance.'})
    print(f'Assembled 240-second film: {a.output}')


def main():
    p=argparse.ArgumentParser();p.add_argument('--map',type=Path);p.add_argument('--output',type=Path);p.add_argument('--no-narration-output',type=Path);p.add_argument('--ffmpeg',type=Path);p.add_argument('--ffprobe',type=Path);p.add_argument('--template',type=Path);p.add_argument('--kit',type=Path);p.add_argument('--check-only',action='store_true');p.add_argument('--allow-voice-only',action='store_true');p.add_argument('--overwrite',action='store_true');p.add_argument('--reuse-unchanged-segments',action='store_true');p.add_argument('--previous-map',type=Path);a=p.parse_args()
    if a.template:
        if not a.kit:p.error('--template requires --kit')
        template(a.template,a.kit);return
    if not all((a.map,a.output,a.ffmpeg,a.ffprobe)):p.error('Assembly requires --map, --output, --ffmpeg and --ffprobe')
    assemble(a)


if __name__=='__main__':
    main()
