"""Restore native capture timing from recorded frame timestamps, without UI synthesis."""
from __future__ import annotations
import json
import shutil
import bisect
from pathlib import Path
from showcase_firstcut import KIT, FFMPEG, FFPROBE
from showcase_assemble import execute, probe, digest, write


def seconds(position):
    bar,beat,tick=[int(s) for s in position.split(':')]
    return ((bar-1)*4+beat-1+tick/960)*.5  # Actual captured project: 120 BPM, 4/4.


def main():
    out=KIT/'captures/final-edit';records=[];entries=[]
    tasks=[('C01','workflow-final','24-new-light-play.mp4',5,0,
        ['1:1:768','2:1:173','2:4:499','3:4:134']),
        ('W03','workflow-d2','09-warp-play.mp4',7,0,
        ['1:1:499','2:1:922','3:2:077','4:1:499']),
        ('G03','workflow-final','03-yue-preview.mp4',6,5,None)]
    for id,folder,name,duration,start_frame,readouts in tasks:
        source=KIT/'captures'/folder/name;receipt=source.parent/'capture-receipt.json'
        event=next(e for e in json.loads(receipt.read_text())['events'] if e.get('path','').endswith(name) and e['action']=='video')
        assert digest(source)==event['sha256'],'Native capture must match its receipt'
        info=probe(FFPROBE,source);v=next(s for s in info['streams'] if s['codec_type']=='video')
        all_times=event['frame_times_seconds'];assert len(all_times)==event['frames']==int(v['nb_frames'])
        relative=[t-all_times[start_frame] for t in all_times[start_frame:]]
        assert all(b>a for a,b in zip(relative,relative[1:])) and relative[-1]>=duration
        # The edit needs only this scene duration, avoiding ffmpeg's expression
        # nesting limit on frames that would be discarded after the cut anyway.
        relative=relative[:bisect.bisect_right(relative,duration)+2]
        # Lookup is per actual captured frame, not an interpolation of invented UI.
        expression=f'{relative[-1]:.9f}'
        for n,t in reversed(list(enumerate(relative[:-1]))):expression=f'if(eq(N,{n}),{t:.9f},{expression})'
        filters=f"trim=start_frame={start_frame},settb=expr=1/90000,setpts='({expression})/TB',fps=30,setsar=1,format=yuv420p"
        target=out/f'{id}-native-time-aligned.mp4'
        execute([FFMPEG,'-y','-v','error','-i',source,'-vf',filters,'-t',duration,'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','18','-r','30','-video_track_timescale','15360',target],out/'logs'/f'{id}-native-time-aligned.log',records)
        p=probe(FFPROBE,target);vv=next(s for s in p['streams'] if s['codec_type']=='video')
        assert abs(float(p['format']['duration'])-duration)<.01 and int(vv['nb_frames'])==duration*30
        execute([FFMPEG,'-v','error','-i',target,'-f','null','-'],out/'logs'/f'{id}-native-time-aligned-decode.log',records)
        entry={'id':id,'source':str(source),'source_sha256':digest(source),'receipt':str(receipt),'receipt_sha256':digest(receipt),
            'output':str(target),'sha256':digest(target),'duration':duration,'source_start_frame':start_frame,
            'frame_times_seconds':relative,'no_interpolated_ui':True,'audio_speed_changed':False}
        if readouts:
            initial=seconds(readouts[0]);checks=[]
            for n,value in enumerate(readouts):
                real_elapsed=all_times[n*15]-all_times[0]
                checks.append({'source_video_seconds':n,'source_frame':n*15,'readout':value,'project_seconds':seconds(value),
                    'capture_elapsed_seconds':real_elapsed,'deviation_seconds':seconds(value)-(initial+real_elapsed)})
            bound=max(abs(c['deviation_seconds']) for c in checks);assert bound<.08
            entry.update(audio_source_in=initial,readout_checks=checks,max_observed_anchor_deviation_seconds=bound,
                method='Actual per-frame capture wall clock; first-frame musical readout sets source offset. 960 ticks/beat from core/time/MusicalPosition.hpp. Four observed readouts at original video seconds 0/1/2/3 cross-check timestamps. Visual alignment, not sample-accurate.')
        else:
            entry.update(audio_source_in=0,method='Preview card has no running playhead. First visible Previewing state is native frame 5; frame 4 still says Preparing preview. Start this editorial audition from the real candidate beginning and the first Previewing frame.',
                preview_start_bracket_seconds=[all_times[4],all_times[5]],preview_onset_uncertainty_seconds=all_times[5]-all_times[4],
                preview_code='EngineSessionGeneration.inc: preview_generation_result -> AnalysisPreview::prepareAndPlay; fresh AudioFormatReaderSource begins at sample zero; no transport seek.')
        entries.append(entry)
    manifest={'status':'passed','entries':entries,'records':records,
        'ace_preview':{'shot':'G06','picture':'actual static ACE result card','audio_source_in':4,'note':'Editorial excerpt of the real candidate. No moving transport is shown; does not claim a captured playback clock or first sample.'},
        'limits':'Native captures carried accurate frame wall times but were originally encoded at a fixed requested rate. Re-timing restores those recorded timestamps with ordinary frame holds. No optical-flow interpolation, recreated playhead, GUI/model calls, or audio time stretching.'}
    write(out/'NATIVE-TIME-ALIGNMENT.json',manifest)
    shutil.copy2(__file__,KIT/'motion/source/showcase_sync.py')
    print(json.dumps({'status':'passed','entries':[{k:e[k] for k in ('id','output','audio_source_in')} for e in entries]},indent=2))


if __name__=='__main__':main()
