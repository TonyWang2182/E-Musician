"""Build the final edit map from explicitly accepted, real local captures.

Prepared UI montages are static screenshots, never repainted controls. Failed
captures are excluded by an explicit allowlist. Native workflows are captured
and accepted separately; this script does not open or operate the DAW.
"""
from __future__ import annotations
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from showcase_assemble import execute, digest, probe, write
from showcase_firstcut import FFMPEG,FFPROBE,KIT


def montage(kit,name,segments):
    out=kit/'captures/final-edit';out.mkdir(exist_ok=True)
    logs=out/'logs';logs.mkdir(exist_ok=True);parts=[];records=[];inputs=[]
    existing=out/f'{name}-manifest.json'
    if existing.is_file():
        old=json.loads(existing.read_text())
        wanted=[(str(Path(s[0])),digest(s[0]),s[1],s[2] if len(s)>2 else 0,s[3] if len(s)>3 else None) for s in segments]
        previous=[(x['path'],x['sha256'],x['duration'],x.get('source_in',0),x.get('crop')) for x in old['inputs']]
        target=Path(old['output'])
        if previous==wanted and target.is_file() and digest(target)==old['sha256']:
            print(f'Reused verified montage {name}',flush=True)
            return target
    for i,segment in enumerate(segments):
        src,seconds=segment[:2];source_in=segment[2] if len(segment)>2 else 0
        crop=segment[3] if len(segment)>3 else None
        src=Path(src);assert src.is_file()
        target=out/f'{name}-{i+1:02}.mp4'
        info=probe(FFPROBE,src);v=next(s for s in info['streams'] if s['codec_type']=='video')
        kind='image' if src.suffix.lower()=='.png' else 'video'
        if kind=='video':assert float(info['format']['duration'])+.01>=source_in+seconds
        filters='setpts=PTS-STARTPTS,fps=30,'
        if crop:
            x,y,w,h=crop
            assert min(x,y)>=0 and min(w,h)>0 and x+w<=v['width'] and y+h<=v['height']
            filters+=f'crop={w}:{h}:{x}:{y},'
        filters+='scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xe5e9e9,setsar=1,format=yuv420p'
        options=['-loop','1','-framerate','30'] if kind=='image' else ['-ss',source_in]
        execute([FFMPEG,'-y','-v','error',*options,'-i',src,'-vf',filters,'-t',seconds,'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','18','-r','30','-video_track_timescale','15360',target],logs/f'{name}-{i+1:02}.log',records)
        parts.append(target);inputs.append({'path':str(src),'sha256':digest(src),'duration':seconds,'source_in':source_in,'crop':crop,'kind':kind,'dimensions':[v['width'],v['height']]})
    listing=out/f'{name}-concat.txt';listing.write_text(''.join("file '"+p.as_posix()+"'\n" for p in parts))
    target=out/f'{name}-1080p30.mp4'
    execute([FFMPEG,'-y','-v','error','-f','concat','-safe','0','-i',listing,'-c','copy','-movflags','+faststart',target],logs/f'{name}-concat.log',records)
    duration=sum(s[1] for s in segments);p=probe(FFPROBE,target);v=next(s for s in p['streams'] if s['codec_type']=='video')
    assert abs(float(p['format']['duration'])-duration)<.01 and int(v['nb_frames'])==round(duration*30)
    execute([FFMPEG,'-v','error','-i',target,'-f','null','-'],logs/f'{name}-decode.log',records)
    for second in (1,duration-1):
        execute([FFMPEG,'-y','-v','error','-ss',second,'-i',target,'-frames:v','1',out/f'{name}-{second:g}s.png'],logs/f'{name}-{second:g}s.log',records)
    write(out/f'{name}-manifest.json',{'status':'technical-verification-passed','capture_kind':'editorial montage of actual native captures','source_ui_pixels_modified':False,'fake_interaction':False,'inputs':inputs,'output':str(target),'sha256':digest(target),'duration':duration,'records':records})
    return target


def prepare(kit):
    data=json.loads((kit/'scripts/shot-map-firstcut-draft.json').read_text());rows={x['id']:x for x in data['shots']}
    d1=kit/'captures/workflow-final';d2=kit/'captures/workflow-d2';d3=kit/'captures/d3-piano';d4=kit/'captures/demo4'
    def use(id,path,kind='image',**extra):
        path=Path(path);assert path.is_file(),path
        rows[id].update(media=str(path),kind=kind,source_in=0,playback_rate=1,crop=None,zoom=[1,1] if kind=='video' else [1,1.025],picture_status='available',capture_kind='actual native video' if kind=='video' else 'actual native still')
        rows[id].update(extra)
    # Only these D1 sources were accepted by the capture owner.
    for id,name,kind in [('G01','01-yue-working.mp4','video'),('G02','02-yue-result.png','image'),('G03','03-yue-preview.mp4','video'),('G04','05-yue-applied-ready.png','image'),('G05','08-ace-result.png','image'),('G06','08-ace-result.png','image'),('S01','12-scnet-working.mp4','video')]:use(id,d1/name,kind)
    use('G07',montage(kit,'G07-choose-ace',[(d1/'10-both-takes.png',4),(d1/'11-ace-chosen.png',7)]),'video',capture_kind='actual native still montage')
    use('S02',montage(kit,'S02-apply-stems',[(d1/'13-scnet-result.png',3),(d1/'19-drums-only.png',3)]),'video',capture_kind='actual native still montage')
    use('S03',montage(kit,'S03-layer-stems',[(d1/f,3.5) for f in ('19-drums-only.png','20-drums-bass.png','21-drums-bass-other.png','22-four-stems-final.png')]),'video',capture_kind='actual native still montage')
    for a in data['audio']:
        if a['label']=='yue preview':a['source_in']=0;a['alignment_note']='Source0 matches accepted six-second native Preview capture; no fake transport is drawn.'
    use('C01',d1/'24-new-light-play.mp4','video',crop=[0,0,1394,784],editorial_note='Focus actual arrangement; exclude unrelated prior Agent reply.')
    use('C02',d2/'02-chords-review.png')
    use('C03',montage(kit,'C03-apply-chords',[(d2/'02-chords-review.png',3),(d2/'04-chord-track.png',4)]),'video',capture_kind='actual native still montage')
    use('C04',d2/'04-chord-track.png')
    use('W01',d2/'05-warp-working.mp4','video')
    use('W02',montage(kit,'W02-apply-warp',[(d2/'07-warp-applying.mp4',3),(d2/'08-warp-source.png',2)]),'video',capture_kind='actual native video and still montage')
    use('W03',d2/'09-warp-play.mp4','video')
    for a in data['audio']:
        if a['label']=='Actual New Light Warp output, project 120 BPM':
            a['source_in']=0
            a['alignment_note']='Accepted actual playback capture starts at project zero; preserve the same 0.25-second initial silence in the DAW render.'
    use('T01',d2/'10-tea-source.png',crop=[0,128,1394,830],editorial_note='Focus actual source waveform and track; exclude unrelated prior Warp conversation.')
    use('T02',montage(kit,'T02-transcribe-result',[(d2/'11-transcribe-working.mp4',4),(d2/'12-transcription-result.png',3)]),'video',capture_kind='actual native video and still montage')
    use('T03',montage(kit,'T03-midi-and-instrument',[(d2/'15-midi-piano.png',3),(d3/'07-keyscape-editor.png',3)]),'video',capture_kind='actual native still montage')
    piano_crop=[0,126,1776,808]
    use('T04',d3/'05-d3-full-piano-fit.png',crop=piano_crop,editorial_note='Focus actual full piano roll; omit internal capture-project header.')
    use('O02',montage(kit,'O02-product-preview',[(d1/'02-yue-result.png',2.5),(d2/'04-chord-track.png',2.5),(d3/'05-d3-full-piano-fit.png',2.5,0,piano_crop),(d4/'21-rack-final.png',2.5)]),'video',capture_kind='actual native still montage')
    data['pending_shots']=[x['id'] for x in data['shots'] if not x['media']]
    assert not data['pending_shots']
    data['status']='ready-for-technical-assembly'
    data['notes']='Actual native videos and actual screenshot montages. No controls, progress or recording waveforms are painted. Fixed historical inference results; this is an edited showcase, not a new inference or microphone test.'
    data['excluded_failed_captures']=['workflow-final/04-*','workflow-final/06-ace-working.mp4','workflow-final/07-ace-preview.mp4','workflow-final/25-chords-working.mp4','workflow-final/30-chords-working-clean.mp4','workflow-d2/01-chords-working.mp4']
    data['capture_notes']=['G03 audio uses source0 to match the real Preview capture.','G06 uses an actual ACE result still plus its historical audio audition; no animated playback state is fabricated.','S03 shows successive actual Solo states while authentic stems share one source clock.','C03 uses the latest successful Chords result, then clean chord lane. Close/reopen Recent analyses after a rerun; do not select stale results.','W03 video and real Warp output both start at project zero, including the 0.25-second lead-in.','D403 remains a real existing sax track crop plus an abstract graphic, not a genuine incoming recording.']
    sync_path=kit/'captures/final-edit/NATIVE-TIME-ALIGNMENT.json'
    if sync_path.is_file():
        sync=json.loads(sync_path.read_text());assert sync['status']=='passed'
        for entry in sync['entries']:
            assert digest(entry['output'])==entry['sha256']
            rows[entry['id']].update(media=entry['output'],kind='video',source_in=0,playback_rate=1,
                capture_kind='actual native video restored to recorded frame wall clock',timing_evidence=str(sync_path))
            label={'C01':'New Light source audition','W03':'Actual New Light Warp output, project 120 BPM','G03':'yue preview'}[entry['id']]
            item=next(a for a in data['audio'] if a['label']==label)
            item.update(source_in=entry['audio_source_in'],alignment_note=entry['method'])
        data['capture_notes']=[n for n in data['capture_notes'] if not n.startswith(('G03 audio','W03 video'))]
        data['capture_notes'] += ['C01/W03 picture timing is restored from native per-frame wall timestamps; audio starts at their actual first-frame musical position. Observed anchor deviation <80ms, not sample-accurate.', 'G03 begins on the first actual Previewing frame and auditions the candidate from source zero; no running transport is shown.']
    final=kit/'scripts/shot-map-final-2026-11-22.json';write(final,data)
    shutil.copy2(__file__,kit/'motion/source/showcase_finalcut.py')
    print(f'Complete final map prepared; pending {data["pending_shots"]}',flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,default=KIT);a=p.parse_args();prepare(a.kit)

if __name__=='__main__':main()
