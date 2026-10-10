import unittest

from bestseller_analysis.autonomous_research import (
    analyze_sequences, choose_local_candidate, product_prior,
)


class AutonomousResearchTests(unittest.TestCase):
    def test_xiaomiaozhao_is_product_prior(self):
        role, evidence = product_prior("小妙招里面有130节视频课程")
        self.assertEqual(role, "PRODUCT_XIAOMIAOZHAO")
        self.assertIn("小妙招", evidence)

    def test_action_without_product_is_generic_tip(self):
        role, _ = product_prior("回家这样做，每天做几组")
        self.assertEqual(role, "TIP_GENERIC")

    def test_pairwise_first_occurrence(self):
        videos = [{
            "video_id": "1",
            "content_segments": [
                {"primary_role": "HOOK", "confidence": 0.9},
                {"primary_role": "PROOF", "confidence": 0.9},
                {"primary_role": "PRODUCT_INTRO", "confidence": 0.9},
            ],
        }]
        result = analyze_sequences(videos)
        self.assertEqual(result["pairwise_first_occurrence"]["PROOF_vs_PRODUCT"]["PROOF_before_PRODUCT"], 1)

    def test_cta_simulation_refuses_narrative_purchase(self):
        row = {
            "segment_id": "x", "asset_id": "a", "file_name": "x.mp4", "file_path": "x.mp4",
            "source_start": 1.0, "source_end": 8.0, "duration": 7.0,
            "transcript": "这本书是买小妙招的人", "function_tags": ["CTA_DIRECT", "PRODUCT_CTA"],
            "xiaomiaozhao_role": "PRODUCT_XIAOMIAOZHAO", "standalone_score": 0.9,
            "information_score": 0.9, "start_quality": 0.9, "end_quality": 0.9,
            "gold_example_score": 0.0,
        }
        self.assertIsNone(choose_local_candidate([row], "CTA", set()))


if __name__ == "__main__":
    unittest.main()
