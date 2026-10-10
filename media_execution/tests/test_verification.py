import json
from pathlib import Path
import subprocess
import unittest

from media_execution.tests import test_execution as fixtures
from media_execution.verification import verify_local_output
from yixiaoer_adapter.cli_runner import run_hidden


class VerificationTests(unittest.TestCase):
    def test_synthetic_mp4_probe_and_full_decode(self):
        root = Path(__file__).resolve().parents[2]
        config_path = root/'yixiaoer_adapter'/'worker.config.json'
        if not config_path.exists():
            self.skipTest('Local FFmpeg/ffprobe configuration unavailable')
        config = json.loads(config_path.read_text('utf-8-sig'))
        config = {key:config[key] for key in ('ffmpeg','ffprobe')}
        if not all(Path(path).is_file() for path in config.values()):
            self.skipTest('Local FFmpeg/ffprobe unavailable')
        fixture = fixtures.ExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        output = fixture.root/'synthetic.mp4'
        run_hidden([config['ffmpeg'],'-v','error','-f','lavfi','-i','color=c=black:s=108x192:r=30',
                    '-f','lavfi','-i','anullsrc=r=44100:cl=stereo','-t','1','-c:v','libx264',
                    '-c:a','aac','-movflags','+faststart',str(output)],check=True,timeout=30)
        result = verify_local_output(config,output,1)
        self.assertTrue(result['media']['full_decode_verified'])
        self.assertEqual((result['media']['codec'],result['media']['width'],result['media']['height']),('h264',108,192))
        self.assertEqual(result['media']['fps'],'30/1')
        broken = fixture.root/'broken.mp4'
        content = output.read_bytes()
        broken.write_bytes(content[:len(content)*3//4])
        with self.assertRaises((ValueError,subprocess.CalledProcessError)):
            verify_local_output(config,broken,1)


if __name__=='__main__':
    unittest.main()
