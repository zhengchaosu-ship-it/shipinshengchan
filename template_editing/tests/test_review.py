from contextlib import contextmanager
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from config import PATHS
from content_pool.schema import ContentSegment
from template_editing.feedback import save_feedback
from template_editing.gold_extract import MAPPINGS, chunks, neutralize
from template_editing.models import ROOT
from template_editing.preview import prepare_preview, preview_path
from template_editing.serve import create_server


def fixture_report():
    candidate = dict(segment_id='SEG-a', rank=1, segment=dict(asset_id='a', video_id=1, source_start=0, source_end=5))
    return dict(report_id='test-report', template=dict(id='test-template'), slots=[
        dict(id='slot_5', type='CALL_RESULT', selected=[candidate]),
        dict(id='slot_7', type='CALL_RESULT', selected=[candidate])])


class ReviewTests(unittest.TestCase):
    def test_feedback_update_and_repeated_slots(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'template_editing/tests') as temp:
            path = Path(temp) / 'template_feedback.json'
            report = fixture_report()
            payload = dict(report_id=report['report_id'], slot_id='slot_5', segment_id='SEG-a', rating='use', note='会用')
            save_feedback(path, report, payload)
            save_feedback(path, report, dict(payload, rating='maybe', note='需要改剪点'))
            save_feedback(path, report, dict(payload, slot_id='slot_7', rating='reject'))
            data = json.loads(path.read_text('utf-8'))
            self.assertEqual(len(data['records']), 2)
            self.assertEqual(data['records']['test-report|slot_5|SEG-a']['rating'], 'maybe')
            with self.assertRaises(ValueError):
                save_feedback(path, report, dict(payload, report_id='stale'))
            with self.assertRaises(ValueError):
                save_feedback(path, report, dict(payload, segment_id='unlisted'))

    def test_preview_path_guard(self):
        with self.assertRaises(ValueError):
            preview_path(ROOT, 'SEG-../../video_index_fixed.db')

    def test_gold_entity_mapping_and_function_remap(self):
        self.assertEqual(neutralize('苗老师的小灵招'), neutralize('陶老师的小妙招'))
        self.assertNotIn('CTA_DIRECT', MAPPINGS[7][0])
        self.assertIn('PRODUCT_VALUE', MAPPINGS[7][0])
        self.assertNotIn('CALL_RESULT', MAPPINGS[8][0])
        self.assertIn('PRODUCT_INTRO', MAPPINGS[15][0])
        text = '苗老师的小灵招。' * 60
        values = chunks(text)
        self.assertEqual(''.join(values), neutralize(text))
        self.assertLessEqual(max(map(len, values)), 160)

    def test_http_range_and_feedback(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'template_editing/tests') as temp:
            root = Path(temp)
            report = fixture_report()
            (root / 'report_data.json').write_text(json.dumps(report), 'utf-8')
            (root / 'clip.mp4').write_bytes(bytes(range(100)))
            server = create_server(root, port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            port = server.server_port
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            try:
                connection.request('GET', '/clip.mp4', headers={'Range': 'bytes=10-19'})
                result = connection.getresponse()
                self.assertEqual(result.status, 206)
                self.assertEqual(result.read(), bytes(range(10,20)))
                payload = dict(report_id='test-report', slot_id='slot_5', segment_id='SEG-a', rating='use', note='测试保存')
                connection.request('POST', '/api/feedback', json.dumps(payload), {'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'})
                result = connection.getresponse()
                self.assertEqual(result.status, 200)
                self.assertTrue(json.loads(result.read())['saved'])
                connection.request('GET', '/api/feedback')
                self.assertEqual(len(json.loads(connection.getresponse().read())['records']), 1)
                connection.request('POST', '/api/feedback', json.dumps(payload), {'Content-Type':'application/json','Origin':'http://example.com'})
                result = connection.getresponse()
                self.assertEqual(result.status, 403)
                result.read()
                connection.request('GET', '/../run.py')
                result = connection.getresponse()
                self.assertEqual(result.status, 404)
                result.read()
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                worker.join()

    def test_three_short_real_previews(self):
        video_root = ROOT / 'test_videos'
        video_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='template_v01_', dir=video_root) as temp:
            root = Path(temp)
            for number in range(3):
                source = root / f'synthetic_{number}.mp4'
                command = [str(PATHS.ffmpeg_executable),'-hide_banner','-loglevel','error','-nostdin','-y',
                    '-f','lavfi','-i',f'color=c={"red" if number == 0 else "blue" if number == 1 else "green"}:s=160x120:r=12',
                    '-f','lavfi','-i',f'sine=frequency={400+number*100}:sample_rate=24000',
                    '-t','8','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',str(source)]
                subprocess.run(command,check=True,capture_output=True,timeout=30)
                before = hashlib.sha256(source.read_bytes()).hexdigest()
                s = ContentSegment(f'SEG-test{number}', 'a', 1, source.name, str(source), 1, 6, 5, '测试完整原声预览')
                preview = prepare_preview(s, root / 'results')
                self.assertTrue(preview['decode_verified'])
                self.assertGreater(preview['audio_frames'], 0)
                self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(preview, prepare_preview(s, root / 'results'))


if __name__ == '__main__':
    unittest.main()
