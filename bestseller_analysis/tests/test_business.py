import unittest
from pathlib import Path

from bestseller_analysis.business import build_content_segments, cluster_templates, analyze_cta
from bestseller_analysis.business_taxonomy import classify_business
from bestseller_analysis.review_server import ReviewData


def sample_analysis(asr):
    return {
        "video_id": "x", "basic_info": {"duration": 60.0}, "asr_segments": asr,
        "shots": [
            {"shot_index": 0, "start": 0.0, "end": 10.0, "duration": 10.0, "face_ratio": 1.0, "visual_category": "主播口播"},
            {"shot_index": 1, "start": 10.0, "end": 30.0, "duration": 20.0, "face_ratio": 0.8, "visual_category": "真人演示"},
            {"shot_index": 2, "start": 30.0, "end": 60.0, "duration": 30.0, "face_ratio": 0.6, "visual_category": "产品讲解"},
        ],
    }


class BusinessTests(unittest.TestCase):
    def test_direct_cta_wins_over_authority(self):
        result = classify_business("今天跟陶老师下单", 40, 43, 60)
        self.assertEqual(result["primary_role"], "CTA_DIRECT")
        self.assertEqual(result["cta_strength"], 2)
        self.assertIn("AUTHORITY", result["trust_mechanism"])

    def test_hook_allows_multiple_tags(self):
        result = classify_business("肩颈疼的姐妹看过来", 0, 3, 60)
        self.assertEqual(result["primary_role"], "HOOK")
        self.assertTrue(any(tag.startswith("HOOK_") for tag in result["function_tags"]))

    def test_build_content_segment_has_required_fields(self):
        analysis = sample_analysis([
            {"start": 0.0, "end": 4.0, "text": "肩颈疼的看过来"},
            {"start": 10.0, "end": 15.0, "text": "因为这个穴位就在这里"},
            {"start": 15.0, "end": 20.0, "text": "所以给你准备了这个工具"},
            {"start": 20.0, "end": 25.0, "text": "这个点穴棒有五个功能"},
            {"start": 50.0, "end": 55.0, "text": "现在直接下单"},
        ])
        segments = build_content_segments(analysis, {"frames": []})
        self.assertTrue(segments)
        required = {"segment_id", "primary_role", "function_tags", "visual_description",
                    "product_visible", "trust_mechanism", "pace_metadata", "evidence", "confidence"}
        self.assertTrue(required.issubset(segments[0]))
        self.assertTrue(any(item["primary_role"] == "PRODUCT_BRIDGE" for item in segments))
        self.assertTrue(any(item["primary_role"] == "CTA_END" for item in segments))

    def test_cta_context_detects_return_to_proof(self):
        segments = [
            {"segment_id": "1", "primary_role": "PROOF", "trust_mechanism": ["RESULT"], "start": 1},
            {"segment_id": "2", "primary_role": "CTA_DIRECT", "trust_mechanism": [], "start": 2, "cta_strength": 2},
            {"segment_id": "3", "primary_role": "TESTIMONIAL", "trust_mechanism": ["TESTIMONIAL"], "start": 3},
            {"segment_id": "4", "primary_role": "CTA_END", "trust_mechanism": [], "start": 4, "cta_strength": 4},
        ]
        result = analyze_cta(segments)
        self.assertEqual(result["cta_count"], 2)
        self.assertTrue(result["events"][0]["returns_to_proof"])
        self.assertTrue(result["proof_cta_proof_cta"])

    def test_template_cluster_uses_real_medoid(self):
        videos = [
            {"video_id": "1", "compressed_sequence": ["HOOK", "DEMO", "PROOF", "CTA_DIRECT"]},
            {"video_id": "2", "compressed_sequence": ["HOOK", "DEMO", "PROOF", "CTA_END"]},
            {"video_id": "3", "compressed_sequence": ["HOOK", "PRODUCT_INTRO", "CTA_DIRECT"]},
        ]
        clusters = cluster_templates(videos, threshold=0.5)
        ids = {item["video_id"] for item in videos}
        self.assertTrue(all(cluster["medoid_video_id"] in ids for cluster in clusters))

    def test_review_feedback_round_trip(self):
        root = Path(__file__).resolve().parent / "fixtures" / "review"
        store = ReviewData(root)
        store.save({
            "video_id": "1", "segment_id": "1-SEG-0001", "start": 0.1, "end": 2.1,
            "primary_role": "HOOK", "function_tags": ["HOOK_RESULT"],
            "product_visible": False, "product_display_type": None,
            "trust_mechanism": ["RESULT"], "error_reason": "", "notes": "ok", "approved": True,
        })
        saved = store.feedback()["segments"]["1-SEG-0001"]
        self.assertTrue(saved["approved"])
        self.assertEqual(saved["primary_role"], "HOOK")
        self.assertTrue((root / "human_gold_data.json").exists())


if __name__ == "__main__":
    unittest.main()
