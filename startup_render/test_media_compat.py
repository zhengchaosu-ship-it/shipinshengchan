import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
from .media_compat import normalize_export


class MediaCompatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.output=self.root/'丙曜起号.mp4'
        self.output.write_bytes(b'original export'); (self.root/'ffmpeg.exe').write_bytes(b'fixture')
        self.config={'normalize_h264_output':True,'ffprobe':str(self.root/'ffprobe.exe')}
        self.logs=[]

    def run_codec(self,codec='hevc',fail=False):
        def runner(args,**kw):
            if args[0].endswith('ffprobe.exe'):
                data={'streams':[{'codec_type':'video','codec_name':codec},{'codec_type':'audio','codec_name':'aac'}],
                      'format':{'format_name':'mov,mp4'}}
                return subprocess.CompletedProcess(args,0,json.dumps(data).encode(),b'')
            self.assertIn('-n',args); self.assertIn('libx264',args); self.assertIn('-c:a',args)
            if fail: raise subprocess.CalledProcessError(1,args)
            Path(args[-1]).write_bytes(b'h264 normalized fixture')
            return subprocess.CompletedProcess(args,0,b'',b'')
        return normalize_export(self.config,self.output,self.root,runner=runner,
             emit=lambda status,**detail:self.logs.append((status,detail)))

    def test_hevc_normalizes_and_preserves_original_hash(self):
        result=self.run_codec()
        self.assertTrue(result['transcoded'])
        self.assertEqual(Path(result['original_path']).read_bytes(),b'original export')
        self.assertEqual(self.output.read_bytes(),b'h264 normalized fixture')

    def test_h264_no_second_copy_or_transcode(self):
        self.assertFalse(self.run_codec('h264')['transcoded'])
        self.assertEqual(self.output.read_bytes(),b'original export')

    def test_other_codec_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED'): self.run_codec('vp9')
        self.assertEqual(self.output.read_bytes(),b'original export')

    def test_failed_conversion_preserves_raw_without_fake_mp4(self):
        with self.assertRaises(subprocess.CalledProcessError): self.run_codec(fail=True)
        self.assertFalse(self.output.exists())
        self.assertEqual((self.root/'丙曜起号.jianying-original-hevc.mp4').read_bytes(),b'original export')

    def test_no_overwrite_existing_original(self):
        (self.root/'丙曜起号.jianying-original-hevc.mp4').write_bytes(b'older')
        with self.assertRaises(FileExistsError): self.run_codec()
        self.assertEqual(self.output.read_bytes(),b'original export')

    def test_default_disabled_keeps_old_behavior(self):
        runner=Mock(); self.config.pop('normalize_h264_output')
        self.assertIsNone(normalize_export(self.config,self.output,self.root,runner=runner))
        runner.assert_not_called()

    def test_missing_ffmpeg_fails_before_renaming(self):
        (self.root/'ffmpeg.exe').unlink()
        with self.assertRaisesRegex(RuntimeError,'UNAVAILABLE'): self.run_codec()
        self.assertTrue(self.output.exists())
