"""Decode finished local films, inspect their actual frames and measure sound."""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from showcase_firstcut import KIT,FFMPEG,FFPROBE
from showcase_assemble import probe,digest,execute,write


def main():
    out=KIT/'exports';qa=out/'qa';qa.mkdir(exist_ok=True);logs=qa/'logs';logs.mkdir(exist_ok=True);records=[]
    map_path=KIT/'scripts/shot-map-final-2026-11-22.json';m=json.loads(map_path.read_text())
    paths={'english':out/'E-musician-Showcase-240s-English.mp4','music_only':out/'E-musician-Showcase-240s-Music-Only.mp4'}
    results={};audio={}
    for role,path in paths.items():
        info=probe(FFPROBE,path);v=next(s for s in info['streams'] if s['codec_type']=='video')
        assert (v['width'],v['height'],v['avg_frame_rate'],int(v['nb_frames']))==(1920,1080,'30/1',7200)
        assert abs(float(info['format']['duration'])-240)<.05
        execute([FFMPEG,'-v','error','-i',path,'-f','null','-'],logs/f'{role}-decode.log',records)
        command=[str(FFMPEG),'-v','error','-i',str(path),'-map','0:a:0','-ar','48000','-ac','2','-f','f32le','-']
        raw=subprocess.check_output(command);samples=np.frombuffer(raw,dtype='<f4').reshape(-1,2)
        assert len(samples)==240*48000 and np.isfinite(samples).all()
        peak=float(np.max(np.abs(samples)));rms=float(np.sqrt(np.mean(samples.astype(np.float64)**2)))
        metrics={'sample_rate':48000,'channels':2,'frames':len(samples),'peak':peak,'peak_dbfs':20*np.log10(max(peak,1e-12)),'rms':rms,'rms_dbfs':20*np.log10(max(rms,1e-12)),'samples_at_or_above_full_scale':int(np.count_nonzero(np.abs(samples)>=1.0))}
        loudness=subprocess.run([str(FFMPEG),'-v','info','-i',str(path),'-map','0:a:0','-af','loudnorm=I=-16:TP=-1:LRA=11:print_format=json','-f','null','-'],capture_output=True)
        assert loudness.returncode==0
        (logs/f'{role}-loudness.log').write_bytes(loudness.stderr)
        match=re.search(rb'\{\s*"input_i"[\s\S]+?\}',loudness.stderr)
        assert match;ld=json.loads(match.group());metrics['loudness']={k:ld[k] for k in ('input_i','input_tp','input_lra','input_thresh')}
        results[role]={'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path),'probe':info,'audio':metrics};audio[role]=samples
    intervals=[('YuE2 preview',31,37),('ACE preview',49,55),('drums',80,83.5),('drums+bass',83.5,87),('drums+bass+other',87,90.5),('all stems',90.5,94),('New Light source',94,99),('Warp output',135,142),('MIDI piano',161,168),('continuous Demo4',168,228)]
    for role,samples in audio.items():
        results[role]['audition_intervals']=[]
        for name,start,end in intervals:
            clip=samples[round(start*48000):round(end*48000)]
            peak=float(np.max(np.abs(clip)));rms=float(np.sqrt(np.mean(clip.astype(np.float64)**2)))
            assert rms>1e-5,f'{role} {name} was silent'
            results[role]['audition_intervals'].append({'name':name,'start':start,'end':end,'peak':peak,'rms':rms})
    quiet=audio['music_only'][20*48000:24*48000]
    voiced=audio['english'][20*48000:24*48000]
    assert float(np.max(np.abs(quiet)))<1e-6 and float(np.sqrt(np.mean(voiced**2)))>.005
    # Extract from the actual final MP4 rather than recycling source screenshots.
    stills=[]
    for shot in m['shots']:
        t=(shot['start']+shot['end'])/2
        png=qa/f"{shot['id']}-{t:g}s.png"
        execute([FFMPEG,'-y','-v','error','-ss',t,'-i',paths['english'],'-frames:v','1',png],logs/f"{shot['id']}-frame.log",records)
        stills.append((shot,png,t))
    columns=5;tw,th=384,216;rowh=250
    sheet=Image.new('RGB',(columns*tw,((len(stills)+columns-1)//columns)*rowh),'#dfe4e5');draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',18)
    for i,(shot,png,t) in enumerate(stills):
        x=(i%columns)*tw;y=(i//columns)*rowh
        im=Image.open(png).convert('RGB');assert im.size==(1920,1080);im=im.resize((tw,th),Image.Resampling.LANCZOS)
        sheet.paste(im,(x,y));draw.text((x+8,y+220),f"{shot['id']}  {shot['start']:03d}-{shot['end']:03d}s",font=font,fill='#17272b')
    contact=qa/'final-film-contact-sheet.png';sheet.save(contact)
    work=out/'E-musician-Showcase-240s-English-work'
    companion=json.loads((work/'NO-NARRATION-RESULT.json').read_text());assert companion['status']=='passed' and companion['picture_reencoded'] is False
    report={'created':datetime.now(timezone.utc).isoformat(),'status':'technical-checks-passed','map':str(map_path),'map_sha256':digest(map_path),'films':results,'same_picture_stream_hash':companion['video_stream_hash'],'voice_absent_in_music_only_test':True,'all_required_auditions_nonzero':True,'contact_sheet':str(contact),'records':records,'perceptual_listening_acceptance':'not performed by this measurement script','real_mic_and_sax_footage_pending':True,'fixed_historical_results':True,'new_inference':False,'visual_acceptance':'contact sheet and selected full-size final frames require reviewer inspection after this command'}
    sync=KIT/'captures/final-edit/NATIVE-TIME-ALIGNMENT.json'
    if sync.is_file():
        timing=json.loads(sync.read_text());assert timing['status']=='passed'
        for entry in timing['entries']:assert digest(entry['output'])==entry['sha256']
        report['native_timing_alignment']={'path':str(sync),'sha256':digest(sync),'status':'actual frame wall timestamps restored','not_sample_accurate':True,'audio_not_time_stretched':True,'anchor_errors':{e['id']:e['max_observed_anchor_deviation_seconds'] for e in timing['entries'] if 'max_observed_anchor_deviation_seconds' in e}}
    write(out/'FINAL-TECHNICAL-QA.json',report)
    print(json.dumps({'status':report['status'],'films':{k:{'path':v['path'],'bytes':v['bytes'],'audio':v['audio']} for k,v in results.items()},'contact_sheet':str(contact)},indent=2),flush=True)

if __name__=='__main__':main()
