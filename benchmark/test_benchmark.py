import json
from pathlib import Path
import unittest
from unittest.mock import patch

from benchmark.run import acceptable_ids, evaluate_case, load_cases, summarize


class MetricsTests(unittest.TestCase):
    def case(self):
        return dict(id="case", image="example.jpg", expected_video_id=11,
                    expected_timestamp=100.0, time_tolerance_seconds=2.0)

    def test_time_boundary_and_wrong_video(self):
        rows = [dict(video_id=12, timestamp=100), dict(video_id=11, timestamp=102)]
        row = evaluate_case(self.case(), rows)
        self.assertFalse(row["hits"]["1"])
        self.assertTrue(row["hits"]["5"])
        self.assertEqual(row["time_error_seconds"], 2)

    def test_time_error_uses_highest_ranked_correct_video(self):
        row = evaluate_case(self.case(), [dict(video_id=11, timestamp=120), dict(video_id=11, timestamp=100)])
        self.assertFalse(row["hits"]["1"])
        self.assertTrue(row["video_only_hits"]["1"])
        self.assertEqual(row["time_error_seconds"], 20)
        self.assertTrue(row["hits"]["5"])

    def test_empty_and_error_remain_in_denominator(self):
        hit = evaluate_case(self.case(), [dict(video_id=11, timestamp=101)])
        failed = evaluate_case(self.case(), [], error="decode error")
        summary = summarize([hit, failed])
        self.assertEqual(summary["top1_accuracy"], 0.5)
        self.assertEqual(summary["mean_time_error_seconds"], 1)
        self.assertEqual(summary["time_error_case_count"], 1)
        self.assertEqual(summary["error_cases"], 1)
        self.assertIsNone(summarize([failed])["mean_time_error_seconds"])

    def test_top10_cutoff(self):
        rows = [dict(video_id=12, timestamp=100)] * 10 + [dict(video_id=11, timestamp=100)]
        self.assertFalse(evaluate_case(self.case(), rows)["hits"]["10"])

    def test_example_resolves_relative_to_manifest(self):
        cases = load_cases(Path(__file__).parent / "cases/example.json")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["acceptable_video_ids"], [11])
        self.assertTrue(Path(cases[0]["image"]).is_file())

    def multi_case(self):
        case = self.case()
        del case["expected_video_id"]
        case["acceptable_video_ids"] = [181, 14]
        return case

    def test_any_acceptable_id_hits_without_choosing_smallest(self):
        for vid in (181, 14):
            with self.subTest(vid=vid):
                row = evaluate_case(self.multi_case(), [dict(video_id=vid, timestamp=102)])
                self.assertTrue(row["video_hits"]["1"])
                self.assertTrue(row["timestamp_hits"]["1"])
                self.assertEqual(row["acceptable_video_ids"], [181, 14])
                self.assertNotIn("expected_video_id", row)
                self.assertEqual(row["time_error_video_id"], vid)

    def test_multi_id_video_and_timestamp_metrics_are_separate(self):
        row = evaluate_case(self.multi_case(), [dict(video_id=181, timestamp=120),
                                               dict(video_id=14, timestamp=101)])
        self.assertTrue(row["video_hits"]["1"])
        self.assertFalse(row["timestamp_hits"]["1"])
        self.assertTrue(row["timestamp_hits"]["5"])
        self.assertEqual(row["time_error_seconds"], 20)
        self.assertEqual(row["time_error_video_id"], 181)
        summary = summarize([row, evaluate_case(self.multi_case(), [], error="failed")])
        self.assertEqual(summary["video_hit_rates"]["1"], 0.5)
        self.assertEqual(summary["timestamp_hit_rates"]["1"], 0)
        self.assertEqual(summary["timestamp_hit_rates"]["5"], 0.5)
        self.assertEqual(summary["mean_time_error_seconds"], 20)
        self.assertEqual(row["hits"], row["timestamp_hits"])
        self.assertEqual(row["video_only_hits"], row["video_hits"])

    def test_wrong_video_with_exact_timestamp_is_not_timestamp_hit(self):
        row = evaluate_case(self.multi_case(), [dict(video_id=99, timestamp=100)])
        self.assertFalse(row["video_hits"]["10"])
        self.assertFalse(row["timestamp_hits"]["10"])
        self.assertIsNone(row["time_error_seconds"])

    def test_multi_ids_at_top5_and_top10_boundaries(self):
        for rank in (5, 6, 10, 11):
            with self.subTest(rank=rank):
                results = [dict(video_id=99, timestamp=100)] * (rank - 1)
                results.append(dict(video_id=181, timestamp=100))
                row = evaluate_case(self.multi_case(), results)
                for key in ("video_hits", "timestamp_hits"):
                    self.assertEqual(row[key]["5"], rank <= 5)
                    self.assertEqual(row[key]["10"], rank <= 10)

    def test_invalid_acceptable_ids_and_conflicting_legacy_id(self):
        for values in (None, [], [True], [0], [-1], [1.0], ["14"], "14", [14, 14]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                acceptable_ids(dict(acceptable_video_ids=values))
        with self.assertRaises(ValueError):
            acceptable_ids(dict(expected_video_id=11, acceptable_video_ids=[14, 181]))
        with self.assertRaises(ValueError):
            acceptable_ids({})
        self.assertEqual(acceptable_ids(dict(expected_video_id=14, acceptable_video_ids=[181, 14])), [181, 14])

    def test_load_legacy_and_multi_id_manifests(self):
        manifest = Path(__file__).parent / "cases/example.json"
        for case, expected in ((self.case(), [11]), (self.multi_case(), [181, 14])):
            case["image"] = "../queries/example.jpg"
            with patch.object(Path, "read_text", return_value=json.dumps(dict(schema_version=1, cases=[case]))):
                self.assertEqual(load_cases(manifest)[0]["acceptable_video_ids"], expected)


if __name__ == "__main__":
    unittest.main()
