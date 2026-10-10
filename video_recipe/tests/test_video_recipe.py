from __future__ import annotations

import json
from pathlib import Path
import threading
import unittest
from urllib.request import Request, urlopen

from video_recipe.build_v01 import OUTPUT_ROOT, build
from video_recipe.rules import evaluate_candidate
from video_recipe.review_server import create_server


class RuleTests(unittest.TestCase):
    def test_cta_rejects_generic_action_without_course(self):
        status, gates, _ = evaluate_candidate("CTA", {
            "transcript": "需要的直接拍",
            "function_tags": ["CTA_DIRECT"],
            "speech_score": 0.9,
            "visual_score": None,
        })
        self.assertEqual(status.value, "PARTIAL")
        self.assertTrue(gates["explicit_action_verb"]["passed"])
        self.assertFalse(gates["explicit_xiaomiaozhao_course"]["passed"])

    def test_cta_accepts_all_three_hard_gates(self):
        status, gates, _ = evaluate_candidate("CTA", {
            "transcript": "需要小妙招课程的，直接拍下购买",
            "function_tags": ["CTA_DIRECT", "PRODUCT_CTA"],
            "speech_score": 0.9,
            "visual_score": None,
        })
        self.assertEqual(status.value, "SATISFIED")
        self.assertTrue(all(item["passed"] for item in gates.values()))

    def test_demo_requires_visual_evidence(self):
        status, _, _ = evaluate_candidate("DEMO", {
            "transcript": "大椎往上推到颈椎",
            "function_tags": ["TIP"],
            "speech_score": 0.8,
            "visual_score": None,
            "scene_verified": False,
        })
        self.assertEqual(status.value, "PARTIAL")


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build()
        cls.recipe = json.loads((OUTPUT_ROOT / "video_recipe_3_v01.json").read_text(encoding="utf-8"))

    def test_only_three_mp4_and_seven_nodes(self):
        self.assertEqual(Path(self.recipe["reference_video"]).name, "3.mp4")
        self.assertEqual(len(self.recipe["nodes"]), 7)
        self.assertEqual(self.recipe["business_structure"], ["HOOK", "CONTENT", "PROOF", "DEMO", "PRODUCT", "CTA", "PROOF"])

    def test_all_anchor_types_are_represented(self):
        types = {anchor["anchor_type"] for node in self.recipe["nodes"] for anchor in node["anchors"]}
        self.assertEqual(types, {"WORD", "PHRASE", "SEMANTIC_INTENT", "VISUAL_EVENT"})

    def test_demo_and_cta_are_not_force_filled(self):
        by_role = {}
        for node in self.recipe["nodes"]:
            by_role.setdefault(node["role"], []).append(node)
        self.assertEqual(by_role["DEMO"][0]["satisfy_status"], "PARTIAL")
        self.assertIsNone(by_role["DEMO"][0]["selected_candidate"])
        self.assertEqual(by_role["CTA"][0]["satisfy_status"], "UNRESOLVED")
        self.assertIsNone(by_role["CTA"][0]["selected_candidate"])

    def test_variant_is_interface_only(self):
        interface = self.recipe["variant_interface"]
        self.assertEqual(interface["mode"], "INTERFACE_ONLY_NO_VARIANTS_GENERATED")
        self.assertIn("variant_id", interface["variant_template"])
        self.assertIn("candidate_selection", interface["variant_template"])

    def test_review_page_and_range_media(self):
        server = create_server(port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base + "/", timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("Video Recipe V0.1", response.read().decode("utf-8"))
            candidate_id = self.result["node_results"][0]["top_candidates"][0]["candidate_id"]
            request = Request(base + "/media/candidate/" + candidate_id, headers={"Range": "bytes=0-1023"})
            with urlopen(request, timeout=10) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 1024)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
