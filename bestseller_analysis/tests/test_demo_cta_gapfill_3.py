import unittest

from bestseller_analysis.demo_cta_gapfill_3 import classify_cta, reference_slots


class DemoCtaGapfillTests(unittest.TestCase):
    def test_strict_course_cta_is_reliable(self):
        result = classify_cta(
            "想学的现在去拍下来", ["小妙招是一套系统视频课程"], ["今天可以带回去"]
        )
        self.assertTrue(result["reliable"])
        self.assertIn("拍下来", result["action_evidence"])
        self.assertIn("小妙招", result["course_evidence"])

    def test_nearby_product_context_can_resolve_course_referent(self):
        result = classify_cta(
            "右下角赶快去拍", ["讲得非常清楚"], ["很多人在等"],
            product_context=["这是小妙招里面一百多节视频课程"],
        )
        self.assertTrue(result["reliable"])
        self.assertIn("小妙招", result["course_evidence"])

    def test_course_value_without_action_is_not_cta(self):
        result = classify_cta(
            "小妙招里面有一百三十节课", ["都是详细教学"], ["学员反馈很好"]
        )
        self.assertFalse(result["reliable"])
        self.assertEqual(result["action_evidence"], [])

    def test_price_without_action_is_not_cta(self):
        result = classify_cta("今天这个课程价格很优惠", [], [])
        self.assertFalse(result["reliable"])

    def test_past_purchase_is_not_cta(self):
        result = classify_cta("我买过很多小妙招课程", [], [])
        self.assertFalse(result["reliable"])
        self.assertTrue(result["past_narrative"])

    def test_sales_proof_is_not_direct_cta(self):
        result = classify_cta(
            "放出去一两百号人拍下来了", ["小妙招里面有一百多项技术"], []
        )
        self.assertFalse(result["reliable"])
        self.assertTrue(result["past_narrative"])

    def test_action_without_course_referent_is_not_cta(self):
        result = classify_cta("需要的去拿走", ["今天讲肩膀疼"], ["回家按这里"])
        self.assertFalse(result["reliable"])

    def test_negated_purchase_action_is_not_cta(self):
        result = classify_cta("不用去拍", ["这是小妙招视频课"], [])
        self.assertFalse(result["reliable"])
        self.assertTrue(result["negated_action"])

    def test_reference_slots_support_repeated_role(self):
        video = {
            "template_skeleton": ["HOOK", "PROOF", "CTA", "PROOF"],
            "content_segments": [
                {"segment_id": "1", "primary_role": "HOOK", "start": 0, "end": 1, "duration": 1, "transcript": "a"},
                {"segment_id": "2", "primary_role": "PROOF", "start": 1, "end": 2, "duration": 1, "transcript": "b"},
                {"segment_id": "3", "primary_role": "CTA_DIRECT", "start": 2, "end": 3, "duration": 1, "transcript": "c"},
                {"segment_id": "4", "primary_role": "CALL_RESULT", "start": 3, "end": 4, "duration": 1, "transcript": "d"},
            ],
        }
        rows = reference_slots(video)
        self.assertEqual([row["segment_id"] for row in rows], ["1", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
