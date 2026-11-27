"""Numerical beat summaries are not model accuracy measurements."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.audio_analysis.beats import summarize, MAX_BEATS
from scripts.audio_analysis.common import AnalysisError, validate_request

class BeatSummaryTests(unittest.TestCase):
    def test_regular_three_and_four_are_candidates(self):
        for meter in (3,4):
            beats=[i*.5 for i in range(25)]
            value=summarize(beats,beats[::meter],13)
            self.assertEqual(value['tempo']['bpm'],120)
            self.assertEqual(value['tempo']['meter_numerator'],meter)
            self.assertEqual(value['tempo']['tempo_candidates'],[60,120,240])
            self.assertEqual(value['tempo']['first_downbeat_seconds'],0)
            self.assertFalse(value['tempo']['variable_tempo'])
    def test_empty_short_unknown_and_compound_do_not_invent_meter(self):
        for beats,down in (([],[]),([.1,.6],[.1]),([i*.5 for i in range(30)],[0,3,6,9,12])):
            tempo=summarize(beats,down,15)['tempo']
            self.assertEqual(tempo['meter_numerator'],0)
            self.assertFalse(tempo['meter_supported'])
        self.assertIsNone(summarize([],[],3)['tempo']['bpm'])
        self.assertIsNone(summarize([],[],3)['tempo']['first_downbeat_seconds'])
    def test_manual_meter_does_not_fabricate_downbeats(self):
        value=summarize([0,.5,1,1.5],[],2,'3/4')
        self.assertEqual(value['tempo']['meter_numerator'],3)
        self.assertTrue(all(not e['is_downbeat'] for e in value['beat_events']))
        self.assertIsNone(value['tempo']['first_downbeat_seconds'])
    def test_bounds_duplicates_nonfinite_and_limit(self):
        value=summarize([1,.5,.5,-.1,3],[.5],2)
        self.assertEqual(value['beat_events'],[{'time_seconds':.5,'is_downbeat':True},{'time_seconds':1.,'is_downbeat':False}])
        for values in ([float('nan')],list(range(MAX_BEATS+1))):
            with self.assertRaises(AnalysisError):summarize(values,[],600)
    def test_variable_pulse_is_reported_without_correction(self):
        beats=[0,.5,1.1,1.8,2.6,3.5,4.5,5.6]
        value=summarize(beats,[],6)
        self.assertTrue(value['tempo']['variable_tempo'])
        self.assertEqual([b['time_seconds'] for b in value['beat_events']],beats)
    def test_protocol_beats_default_and_explicit_meter(self):
        request={'schema_version':1,'job_id':'beats-test','kind':'beats','source_path':str(Path('tone.wav').resolve()),'analysis_root':str(Path('.').resolve()),'duration_seconds':5}
        self.assertEqual(validate_request(request)['preset'],'beat_this')
        self.assertEqual(validate_request(request)['parameters'],{'meter':'auto'})
        self.assertEqual(validate_request({**request,'parameters':{'meter':'4/4'}})['parameters']['meter'],'4/4')
        for value in ('6/8',[],{},None):
            with self.assertRaises(AnalysisError):validate_request({**request,'parameters':{'meter':value}})
        with self.assertRaises(AnalysisError):validate_request({**request,'parameters':{'stems':6}})

if __name__=='__main__':unittest.main()
