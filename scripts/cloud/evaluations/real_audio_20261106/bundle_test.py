"""Synthetic small-file tests only; no real model, audio, SSH or GPU work."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from bundle import build_archive,safe_path


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=self.root/'scnet-test';self.data=self.source/'data'
        self.data.mkdir(parents=True)
        self.audio=self.data/'vocals.wav';self.audio.write_bytes(b'synthetic-not-real-audio')
        entry={'path':str(self.audio),'bytes':self.audio.stat().st_size,'sha256':hashlib.sha256(self.audio.read_bytes()).hexdigest()}
        (self.source/'attempt.json').write_text(json.dumps({'status':'passed','expected_input_sha256':'a'*64}))
        self.result=self.data/'result.json'
        self.result.write_text(json.dumps({'status':'passed','input':{'sha256':'a'*64},'outputs':[entry]}))
        self.output=self.root/'raw.zip'

    def build(self):return build_archive([self.source],self.output,root=self.root,reserve_bytes=0)

    def test_raw_archive_hashes_and_exclusions(self):
        (self.source/'worker.log').write_text('log');(self.data/'hidden_states.npy').write_bytes(b'excluded')
        receipt=self.build()
        with zipfile.ZipFile(self.output) as archive:
            manifest=json.loads(archive.read('MANIFEST.json'))
            self.assertEqual(len(manifest['files']),receipt['file_count'])
            for entry in manifest['files']:
                content=archive.read(entry['path'])
                self.assertEqual(len(content),entry['bytes'])
                self.assertEqual(hashlib.sha256(content).hexdigest(),entry['sha256'])
            self.assertNotIn('scnet-test/worker.log',archive.namelist())
            self.assertNotIn('scnet-test/data/hidden_states.npy',archive.namelist())

    def test_failed_receipt_refused(self):
        self.result.write_text(json.dumps({'status':'failed'}))
        with self.assertRaises(ValueError):self.build()
        self.assertFalse(self.output.exists())

    def test_changed_raw_artifact_refused(self):
        self.audio.write_bytes(b'tampered')
        with self.assertRaises(ValueError):self.build()
        self.assertFalse(self.output.exists())

    def test_overwrite_refused(self):
        self.output.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):self.build()
        self.assertEqual(self.output.read_bytes(),b'keep')

    def test_path_escape_refused(self):
        with self.assertRaises(ValueError):safe_path(self.root/'..'/'escape',self.root)

    def test_symlink_refused(self):
        link=self.data/'alias.wav'
        try:link.symlink_to(self.audio)
        except OSError:self.skipTest('OS does not permit test symlinks')
        with self.assertRaises(ValueError):self.build()

    def test_scores_receipts_supported(self):
        (self.source/'attempt.json').unlink();self.result.unlink()
        (self.source/'guard-receipt.json').write_text(json.dumps({'status':'passed','input_sha256':'b'*64}))
        entry={'path':str(self.audio),'bytes':self.audio.stat().st_size,'sha256':hashlib.sha256(self.audio.read_bytes()).hexdigest()}
        (self.source/'result-receipt.json').write_text(json.dumps({'status':'passed','input':{'sha256':'b'*64},'artifacts':[entry]}))
        self.assertEqual(self.build()['status'],'passed')


if __name__=='__main__':unittest.main()
