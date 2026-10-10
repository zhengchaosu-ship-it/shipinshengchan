"""只测人工GT格式与独立HTTP服务；不测试/修改检索算法。"""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from auto_remake.gt_review_server import make_handler, validate_annotations, DEFAULT_ROOT


class GTReviewTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((DEFAULT_ROOT/'manifest.json').read_text('utf-8'))
        self.gt=json.loads((DEFAULT_ROOT/'ground_truth.json').read_text('utf-8'))
        self.case=self.manifest['cases'][0]
        self.rows=[copy.deepcopy(r) for r in self.gt['annotations'] if r['case_id']==self.case['case_id']]

    def test_no_prefilled_gt_and_coverage(self):
        self.assertEqual(len(self.gt['annotations']),12)
        for r in self.gt['annotations']:
            self.assertEqual(r['status'],'UNKNOWN');self.assertIsNone(r['correct_asset_id']);self.assertIsNone(r['correct_source_start'])
        for c in self.manifest['cases']:
            self.assertLessEqual(len(c['candidates']),10)
            self.assertEqual({e['channel'] for a in c['candidates'] for e in a['evidence']} & {'DINO','Speech','Audio','Transcript','Multimodal'}, {'DINO','Speech','Audio','Transcript','Multimodal'})
            for b in c['blocks']:self.assertLessEqual(len(b['candidate_ids']),10)

    def test_validate_status_and_times(self):
        validate_annotations(self.rows,self.case)
        r=self.rows[0];r.update(status='CONFIRMED',correct_asset_id='test',correct_video_id=1)
        with self.assertRaises(ValueError):validate_annotations(self.rows,self.case)
        r.update(correct_source_start=3,correct_source_end=2)
        with self.assertRaises(ValueError):validate_annotations(self.rows,self.case)
        r.update(correct_source_end=5);validate_annotations(self.rows,self.case)
        r['reference_end']=float('nan')
        with self.assertRaises(ValueError):validate_annotations(self.rows,self.case)

    def test_temporary_save_range_conflict_and_origin(self):
        qa=DEFAULT_ROOT/'qa';qa.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=qa) as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(qa.resolve()))
            root=Path(tmp);(root/'manifest.json').write_text(json.dumps(self.manifest),'utf-8')
            gt=root/'ground_truth.json';gt.write_text(json.dumps(self.gt),'utf-8');(root/'clip.mp4').write_bytes(b'0123456789')
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root,gt))
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            url=f'http://127.0.0.1:{server.server_port}'
            try:
                request=urllib.request.Request(url+'/clip.mp4',headers={'Range':'bytes=2-5'})
                with urllib.request.urlopen(request) as response:self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345')
                self.rows[0]['note']='TEST_ONLY';payload=json.dumps(dict(case_id=self.case['case_id'],revision=0,annotations=self.rows)).encode()
                request=urllib.request.Request(url+'/api/gt',data=payload,headers={'Origin':url,'Content-Type':'application/json'})
                with urllib.request.urlopen(request) as response:saved=json.load(response)
                self.assertEqual(saved['revision'],1)
                self.assertEqual([r for r in saved['annotations'] if r['case_id']!='case_01'],[r for r in self.gt['annotations'] if r['case_id']!='case_01'])
                with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(request)
                self.assertEqual(e.exception.code,409)
                bad=urllib.request.Request(url+'/api/gt',data=payload,headers={'Origin':'http://external.invalid'})
                with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(bad)
                self.assertEqual(e.exception.code,403)
                self.assertEqual(len(list((root/'gt_history').glob('*.json'))),1)
            finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
