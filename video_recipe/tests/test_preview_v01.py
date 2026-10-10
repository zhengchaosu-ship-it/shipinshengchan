from __future__ import annotations

import json
from pathlib import Path
import threading
import unittest
from urllib.request import Request, urlopen

from video_recipe.preview_review_server import create_server
from video_recipe.preview_v01 import PREVIEW_PATH, QUALITY_PATH, TIMELINE_PATH


class PreviewArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timeline = json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))
        cls.quality = json.loads(QUALITY_PATH.read_text(encoding="utf-8"))

    def test_preview_exists_and_all_checks_pass(self):
        self.assertTrue(PREVIEW_PATH.is_file())
        self.assertGreater(PREVIEW_PATH.stat().st_size, 100_000)
        self.assertTrue(self.quality["all_checks_passed"])
        self.assertEqual(self.quality["decision"], "PREVIEW_READY_FOR_VISUAL_CHECK")

    def test_recipe_order_and_status_boundaries(self):
        nodes = self.timeline["timeline_nodes"]
        self.assertEqual([node["role"] for node in nodes], ["HOOK", "CONTENT", "PROOF", "DEMO", "PRODUCT", "CTA", "PROOF"])
        self.assertEqual(nodes[3]["satisfy_status"], "PARTIAL_DEMO")
        self.assertEqual(nodes[3]["recipe_satisfy_status"], "PARTIAL")
        self.assertEqual(nodes[5]["satisfy_status"], "UNRESOLVED")
        self.assertFalse(nodes[5]["included"])
        self.assertIsNone(nodes[5]["candidate_id"])

    def test_only_six_nodes_are_in_preview(self):
        self.assertEqual(self.timeline["included_node_count"], 6)
        self.assertEqual([node["role"] for node in self.timeline["timeline_nodes"] if node["included"]],
                         ["HOOK", "CONTENT", "PROOF", "DEMO", "PRODUCT", "PROOF"])

    def test_review_page_and_preview_range(self):
        server = create_server(port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base + "/", timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("3.mp4 单条可播放复刻预览 V0.1", response.read().decode("utf-8"))
            request = Request(base + "/media/preview", headers={"Range": "bytes=0-2047"})
            with urlopen(request, timeout=10) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 2048)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
