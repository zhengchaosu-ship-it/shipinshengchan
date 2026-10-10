import unittest

from bestseller_analysis.taxonomy import classify_hook, classify_phase, extract_prices
from bestseller_analysis.pipeline import build_sales_timeline, editing_rhythm


class RuleTests(unittest.TestCase):
    def test_price_requires_real_transaction_evidence(self):
        self.assertNotEqual(classify_phase("只要眼睛里面舒服", 20)[0], "PRICE_OFFER")
        self.assertEqual(classify_phase("今天到手只要99元", 20)[0], "PRICE_OFFER")

    def test_hook_can_have_multiple_types(self):
        labels = classify_hook("肩颈疼的姐妹看过来，今天到手只要99元")
        self.assertIn("痛点型", labels)
        self.assertIn("价格型", labels)
        self.assertIn("人群精准筛选型", labels)

    def test_price_extraction(self):
        self.assertEqual(extract_prices("原价199元，今天99块钱")[1]["value"], 99.0)

    def test_timeline_merges_neighboring_same_phase(self):
        asr = [
            {"start": 0.0, "end": 1.0, "text": "肩颈疼", "sales_phase": "PAIN", "confidence": 0.7},
            {"start": 1.2, "end": 2.0, "text": "还发酸", "sales_phase": "PAIN", "confidence": 0.7},
        ]
        shots = [{"start": 0.0, "end": 2.0, "visual_category": "主播口播（初标）"}]
        timeline = build_sales_timeline(asr, shots)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["sales_phase"], "PAIN")

    def test_editing_rhythm(self):
        shots = [
            {"start": 0.0, "end": 2.0, "duration": 2.0},
            {"start": 2.0, "end": 5.0, "duration": 3.0},
            {"start": 5.0, "end": 10.0, "duration": 5.0},
        ]
        result = editing_rhythm(shots, 10.0, 8.0)
        self.assertEqual(result["shot_count"], 3)
        self.assertEqual(result["first_10s_cuts_per_10s"], 2.0)


if __name__ == "__main__":
    unittest.main()

