import json
from pathlib import Path
import unittest

from bestseller_analysis.human_review import HumanReviewStore


class HumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "fixtures" / "human_review_runtime"
        generated = [
            "human_gold_data.json", "cta_review.json", "replication_review.json",
            "review_progress.json", "ROUND1_REVIEW_REPORT.md", "round1_review_statistics.json",
        ]
        for name in generated:
            path = self.root / name
            if path.exists():
                path.unlink()
        roles = ["HOOK", "PRODUCT_BRIDGE", "PRODUCT_VALUE", "PROOF", "CTA_DIRECT"]
        gold = []
        videos = {}
        for video_number in range(1, 21):
            video_id = str(video_number)
            role = roles[(video_number - 1) % len(roles)]
            segment = {
                "segment_id": f"{video_id}-SEG-0001", "video_id": video_id,
                "start": 0.0, "end": 5.0, "duration": 5.0, "transcript": f"视频{video_id}",
                "primary_role": role, "function_tags": [role], "product_entry_type": None,
                "product_visible": None, "product_display_type": None,
                "trust_mechanism": [], "sales_mechanism": [], "confidence": 0.8,
                "evidence": [], "pace_metadata": {}, "transition_in": None, "transition_out": None,
            }
            video = {
                "video_id": video_id, "file_name": f"{video_id}.mp4",
                "file_path": str(self.root / f"{video_id}.mp4"), "duration": 60.0,
                "content_segments": [segment], "compressed_sequence": [role],
                "template_skeleton": [role], "product_entry": {"first_time": None},
                "cta": {"cta_count": 0 if video_number <= 7 else 1, "events": []},
            }
            videos[video_id] = video
        for index in range(25):
            video_id = str(index % 20 + 1)
            role = roles[index % len(roles)]
            gold.append({
                "gold_role": role, "status": "candidate_needs_review", "video_id": video_id,
                "file_name": f"{video_id}.mp4", "file_path": str(self.root / f"{video_id}.mp4"),
                "segment_id": f"{video_id}-SEG-0001", "start": 0.0, "end": 5.0,
                "transcript": "示例", "role": role, "function_tags": [role],
                "why_good_candidate": "测试", "previous_role": None, "next_role": None, "score": 0.8,
            })
        replication = [{"video_id": str(i), "file_name": f"{i}.mp4", "reason": "测试", "score": 1.0} for i in (9, 7, 8, 3, 19)]
        self.store = HumanReviewStore.__new__(HumanReviewStore)
        self.store.root = self.root
        self.store.human_root = self.root
        self.store.gold_path = self.root / "human_gold_data.json"
        self.store.cta_path = self.root / "cta_review.json"
        self.store.replication_path = self.root / "replication_review.json"
        self.store.progress_path = self.root / "review_progress.json"
        self.store.report_path = self.root / "ROUND1_REVIEW_REPORT.md"
        self.store.report_stats_path = self.root / "round1_review_statistics.json"
        self.store.videos = videos
        self.store.gold_machine = gold
        self.store.replication_machine = replication
        self.store.no_cta_ids = [str(i) for i in range(1, 8)]
        self.store.replication_ids = ["9", "7", "8", "3", "19"]
        self.store._ensure_files()

    def tearDown(self):
        for path in self.root.iterdir():
            if path.name != ".gitkeep":
                path.unlink()

    def test_three_queues_and_groups(self):
        self.assertEqual(len(self.store.gold_queue()), 25)
        self.assertEqual(len(self.store.cta_queue()), 7)
        self.assertEqual(len(self.store.replication_queue()), 5)
        self.assertEqual(len(self.store.gold_queue("A")), 15)
        self.assertEqual(len(self.store.gold_queue("B")), 5)
        self.assertEqual(len(self.store.gold_queue("C")), 5)

    def test_review_files_do_not_touch_machine_files(self):
        before = json.dumps(self.store.gold_machine, ensure_ascii=False)
        candidate = self.store.gold_queue()[0]
        self.store.save_gold({
            "candidate_id": candidate["candidate_id"], "material_grade": "GOLD",
            "boundary_result": "正确", "start": 0, "end": 5,
            "primary_role": "HOOK", "function_tags": ["HOOK"], "error_reasons": [],
            "editing_use": "会直接用", "notes": "ok",
        })
        self.assertEqual(before, json.dumps(self.store.gold_machine, ensure_ascii=False))
        self.assertTrue((self.root / "human_gold_data.json").exists())
        self.assertEqual(self.store.progress()["gold"]["reviewed"], 1)

    def test_report_only_after_all_reviews(self):
        with self.assertRaisesRegex(ValueError, "审核未完成"):
            self.store.generate_report()
        for candidate in self.store.gold_queue():
            machine = candidate["machine"]
            self.store.save_gold({
                "candidate_id": candidate["candidate_id"], "material_grade": "USABLE",
                "boundary_result": "正确", "start": candidate["start"], "end": candidate["end"],
                "primary_role": machine["primary_role"], "function_tags": machine["function_tags"],
                "error_reasons": [], "editing_use": "修改后可用", "notes": "",
            })
        for video in self.store.cta_queue():
            self.store.save_cta({"video_id": video["video_id"], "review_result": "确实无CTA", "cta_ranges": [], "notes": ""})
        for video in self.store.replication_queue():
            self.store.save_replication({
                "video_id": video["video_id"], "structure_clarity": 4,
                "local_material_replaceability": 3, "original_product_dependency": "中",
                "original_person_case_dependency": "低", "suitable_for_first_replication": "是", "notes": "",
            })
        result = self.store.generate_report()
        self.assertTrue(Path(result["report"]).exists())
        self.assertTrue(self.store.progress()["report_ready"])
        self.assertFalse(result["stats"]["automatic_best_replication_selected"])


if __name__ == "__main__":
    unittest.main()
