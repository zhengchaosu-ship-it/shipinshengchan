from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from auto_remake.aggregation import aggregate_shot
from auto_remake.confidence import assess_confidence
from auto_remake.dino_adapter import DinoBackend
from auto_remake.dino_matcher import DinoMatcher
from auto_remake.evaluation import evaluate, make_template
from auto_remake.match import match_analysis
from auto_remake.report import render_report
from auto_remake.storage import MODULE_ROOT, result_file


def hit(asset, rank, timestamp, similarity=0.8):
    return dict(asset_id=asset, video_id=ord(asset[0]), file_name=f'{asset} <中文>.mp4',
                file_path=f'D:/本地素材/{asset}.mp4', rank=rank, timestamp=timestamp,
                similarity=similarity, frame_id=f'{asset}-{timestamp}', frame_number=round(timestamp * 24))


def shot_fixture():
    return dict(shot_id=1, start=10.0, end=15.0, duration=5.0, matches=[],
                selection_status="ok", rejected_frames={}, requested_frames=3,
                query_frames=[dict(timestamp=10.5 + 2 * i, image_path=f'frames/query_{i}.jpg', frame_index=252 + i * 48) for i in range(3)])


def evidence(shot, hits):
    return [dict(query_frame_index=frame["frame_index"], query_timestamp=frame["timestamp"],
                 query_image_path=frame["image_path"], hits=rows) for frame, rows in zip(shot["query_frames"], hits)]


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.root = MODULE_ROOT / "tests" / ("run_" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.clean)
        self.shot = shot_fixture()

    def clean(self):
        target = self.root.resolve()
        if target.parent != (MODULE_ROOT / "tests").resolve() or not target.name.startswith("run_"):
            raise ValueError("不允许清理测试范围外路径")
        shutil.rmtree(target)

    def test_consensus_beats_one_top1_and_no_duplicate_votes(self):
        rows = evidence(self.shot, [[hit('B', 1, 500), hit('A', 3, 100.5), hit('A', 4, 900)],
                                   [hit('A', 3, 102.5)], [hit('A', 4, 104.5)]])
        candidates = aggregate_shot(self.shot, rows)
        self.assertEqual([c['asset_id'] for c in candidates], ['A', 'B'])
        top = candidates[0]
        self.assertEqual(top['support_frames'], 3)
        self.assertEqual(top['temporal_consistency'], 'high')
        self.assertAlmostEqual(top['source_start_estimate'], 100)
        self.assertAlmostEqual(top['source_end_estimate'], 105)
        self.assertEqual(top['best_ranks'], [3, 3, 4])

    def test_reversed_and_stationary_timestamps_not_confident(self):
        for times in ([104, 102, 100], [100, 100, 100]):
            rows = evidence(self.shot, [[hit('A', 1, t)] for t in times])
            result = aggregate_shot(self.shot, rows)[0]
            self.assertEqual(result['temporal_consistency'], 'low')
            self.assertIsNone(result['source_start_estimate'])
            self.assertIsNone(result['source_end_estimate'])

    def test_two_observations_medium_one_low(self):
        rows = evidence(self.shot, [[hit('A', 1, 100.5)], [hit('A', 2, 102.5)], [hit('B', 1, 400)]])
        results = aggregate_shot(self.shot, rows)
        self.assertEqual(results[0]['temporal_consistency'], 'medium')
        self.assertEqual(results[1]['temporal_consistency'], 'low')
        self.assertIsNone(results[1]['source_start_estimate'])

    def test_confidence_is_explicit_not_ground_truth(self):
        rows = evidence(self.shot, [[hit('A', 1, 100.5), hit('B', 2, 800)],
                                   [hit('A', 1, 102.5)], [hit('A', 1, 104.5)]])
        self.shot['matches'] = aggregate_shot(self.shot, rows)
        assessment = assess_confidence(self.shot)
        self.assertEqual(assessment['status'], 'HIGH_CONFIDENCE')
        self.assertFalse(assessment['is_ground_truth'])
        self.shot['matches'][0]['best_similarities'] = [.4, .4, .4]
        self.assertEqual(assess_confidence(self.shot)['status'], 'LOW_CONFIDENCE')
        self.shot['matches'] = []
        self.assertEqual(assess_confidence(self.shot)['status'], 'LOW_CONFIDENCE')

    def test_top5_assets_and_empty_query(self):
        rows = evidence(self.shot, [[hit(chr(65 + i), i + 1, 100 + i) for i in range(8)], [], []])
        self.assertEqual(len(aggregate_shot(self.shot, rows)), 5)
        empty = dict(self.shot, query_frames=[])
        self.assertEqual(aggregate_shot(empty, []), [])

    def test_invalid_candidate_and_identity_mismatch(self):
        for bad in (dict(hit('A', 1, 20), timestamp=float('nan')), hit('A', 1, 20, float('inf'))):
            with self.assertRaises(ValueError):
                aggregate_shot(self.shot, evidence(self.shot, [[bad], [], []]))
        other = dict(hit('A', 2, 21), video_id=999)
        with self.assertRaises(ValueError):
            aggregate_shot(self.shot, evidence(self.shot, [[hit('A', 1, 20), other], [], []]))

    def test_duplicate_query_cannot_inflate_support(self):
        rows = evidence(self.shot, [[hit('A', 1, 20)], [], []])
        rows[1] = rows[0]
        with self.assertRaises(ValueError):
            aggregate_shot(self.shot, rows)

    def test_secondary_hits_can_supply_temporal_evidence(self):
        rows = evidence(self.shot, [[hit('A', 1, 900), hit('A', 2, 100.5)],
                                   [hit('A', 1, 700), hit('A', 2, 102.5)],
                                   [hit('A', 1, 500), hit('A', 2, 104.5)]])
        match = aggregate_shot(self.shot, rows)[0]
        self.assertEqual(match['temporal_consistency'], 'high')
        self.assertEqual(match['source_timestamps'], [100.5, 102.5, 104.5])
        self.assertEqual(match['best_hit_source_timestamps'], [900, 700, 500])

    def backend(self, fail=False):
        buf = io.BytesIO()
        Image.new('RGB', (90, 60), 'green').save(buf, format='JPEG')
        thumbnail = buf.getvalue()

        class Backend:
            device, load_seconds, calls = 'mock', 0.0, 0

            def search_with_timings(self, image, k):
                if fail:
                    raise RuntimeError('模拟 DINO 故障')
                self.calls += 1
                assert k == 100
                row = hit('A', 1, 100.5 + 2 * (self.calls - 1))
                row['thumbnail'] = thumbnail
                timing = dict(candidate_dedup=True, orb_enabled=False, candidate_count=500,
                              result_count=1, embedding_seconds=.01, faiss_seconds=.02,
                              metadata_seconds=.003, dedup_seconds=.001, thumbnail_seconds=.001,
                              total_seconds=.035)
                return [row], timing

        return Backend()

    def make_analysis(self):
        (self.root / 'frames').mkdir()
        for frame in self.shot['query_frames']:
            Image.new('RGB', (90, 60), 'blue').save(self.root / frame['image_path'])
        data = dict(schema_version='1.0', reference_video='D:/真实参考路径待提供.mp4',
                    duration=15, input_description='仅 mock 管道单测，不是真实验收',
                    analysis_seconds=.1, query_frame_count=3, decoded_frame_count=360,
                    status='completed', warnings=[], shots=[self.shot])
        path = self.root / 'analysis.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        (self.root / 'report.html').write_text(render_report(data), encoding='utf-8')
        return path

    def test_matcher_independent_queries_and_thumbnails(self):
        self.make_analysis()
        backend = self.backend()
        matcher = DinoMatcher(self.root, backend=backend)
        matches = matcher.match_shot(self.shot)
        self.assertEqual(backend.calls, 3)
        self.assertEqual(len(matcher.frame_results), 3)
        self.assertEqual(matches[0]['support_frames'], 3)
        self.assertTrue((self.root / matches[0]['thumbnail_path']).is_file())
        self.assertAlmostEqual(matcher.timings['embedding_seconds'], .03)
        self.assertAlmostEqual(matcher.timings['faiss_seconds'], .06)
        self.assertNotIn('thumbnail', matcher.frame_results[0]['hits'][0])

    def test_path_escape_rejected(self):
        self.make_analysis()
        self.shot['query_frames'][0]['image_path'] = '../test_matching.py'
        with self.assertRaisesRegex(ValueError, '超出'):
            DinoMatcher(self.root, backend=self.backend()).match_shot(self.shot)
        with self.assertRaises(ValueError):
            result_file(MODULE_ROOT.parent / 'config.json')

    def test_pipeline_backup_report_and_unlabelled_evaluation(self):
        path = self.make_analysis()
        original = path.read_bytes()
        data = match_analysis(path, backend=self.backend())
        self.assertEqual(data['schema_version'], '1.1')
        self.assertEqual((self.root / 'analysis_only.json').read_bytes(), original)
        self.assertTrue(list(self.root.glob('analysis.json.*.bak')))
        self.assertIsNone(data['evaluation']['top1_shot_hit_rate'])
        self.assertEqual(data['evaluation']['evaluated_shots'], 0)
        html = (self.root / 'report.html').read_text(encoding='utf-8')
        self.assertEqual(html.count('<img '), 4)
        self.assertIn('原素材 Top5', html)
        self.assertIn('A &lt;中文&gt;.mp4', html)
        self.assertIn('待人工标注', html)
        self.assertNotIn('<script', html)
        with self.assertRaises(ValueError):
            match_analysis(path, backend=self.backend())

    def test_failed_match_preserves_parse_result(self):
        path = self.make_analysis()
        original = path.read_bytes()
        with self.assertRaises(RuntimeError):
            match_analysis(path, backend=self.backend(fail=True))
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue((self.root / 'matching_error.json').exists())

    def test_gt_rates_and_temporal_errors(self):
        path = self.make_analysis()
        data = match_analysis(path, backend=self.backend())
        labels = make_template(data)
        labels['reviewer'] = 'test reviewer'
        labels['shots'][0].update(judgement='top1_correct', correct_candidate_rank=1,
                                  shot_segmentation='reasonable', time_alignment='inaccurate', failure_categories=['C'])
        result = evaluate(data, labels)
        self.assertEqual(result['top1_shot_hit_rate'], 1)
        self.assertEqual(result['top5_shot_hit_rate'], 1)
        self.assertEqual(result['correct_asset_wrong_time_shots'], 1)
        labels['shots'][0]['correct_candidate_rank'] = 2
        with self.assertRaises(ValueError):
            evaluate(data, labels)
        labels['analysis_fingerprint'] = 'wrong'
        with self.assertRaises(ValueError):
            evaluate(data, labels)

    def test_gt_unknown_excluded_and_contradictions_rejected(self):
        path = self.make_analysis()
        data = match_analysis(path, backend=self.backend())
        labels = make_template(data)
        labels['reviewer'] = 'test reviewer'
        labels['shots'][0]['judgement'] = 'unable_to_judge'
        result = evaluate(data, labels)
        self.assertIsNone(result['top5_shot_hit_rate'])
        self.assertEqual(result['unable_to_judge_shots'], 1)
        labels['shots'][0]['time_alignment'] = 'inaccurate'
        with self.assertRaises(ValueError):
            evaluate(data, labels)

    def test_official_adapter_forwarding_and_device_restore(self):
        @dataclass
        class Catalog:
            key: str = 'formal_v1_repaired'

        backend = self.backend()

        class Adapter:
            candidate_dedup = False

            def summary(self):
                return Catalog()

            def image_engine(self):
                assert self.candidate_dedup is True
                assert os.environ['JULY_SEARCH_DEVICE'] == 'cpu'
                return backend

        class Module:
            FormalV1RepairedAdapter = Adapter

        with patch('auto_remake.dino_adapter.load_official_adapter', return_value=Module), patch.dict(os.environ, {'JULY_SEARCH_DEVICE': 'cuda'}):
            adapter = DinoBackend(device='cpu')
            self.assertEqual(os.environ['JULY_SEARCH_DEVICE'], 'cuda')
            rows, timing = adapter.search_with_timings(Image.new('RGB', (8, 8)), k=100)
            self.assertEqual(backend.calls, 1)
            self.assertEqual(rows[0]['asset_id'], 'A')
            self.assertTrue(timing['candidate_dedup'])


if __name__ == '__main__':
    unittest.main()
