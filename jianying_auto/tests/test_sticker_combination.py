import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jianying_auto as target


class StickerCombinationTests(unittest.TestCase):
    def setUp(self):
        self.output = Path(__file__).resolve().parent / ("_tmp_combo_" + uuid.uuid4().hex)
        self.output.mkdir()

    def tearDown(self):
        resolved = self.output.resolve()
        tests_root = Path(__file__).resolve().parent
        if resolved.parent != tests_root or not resolved.name.startswith("_tmp_combo_"):
            raise RuntimeError("拒绝清理非测试目录: %s" % resolved)
        shutil.rmtree(resolved, ignore_errors=True)

    def fixture(self):
        stickers = []
        tracks = [{"id": "main-track", "type": "video", "name": "主视频", "segments": []}]
        effects = []
        for index in range(2):
            material_id = "sticker-material-%d" % index
            effect_id = "old-mix-%d" % index
            stickers.append({"id": material_id, "type": "sticker"})
            effects.append({"id": effect_id, "type": "mix_mode"})
            tracks.append({
                "id": "sticker-track-%d" % index,
                "type": "sticker",
                "name": "贴纸-%d" % index,
                "segments": [{
                    "id": "sticker-segment-%d" % index,
                    "material_id": material_id,
                    "extra_material_refs": [effect_id],
                    "clip": {"alpha": 0.01},
                    "target_timerange": {"start": 0, "duration": 3_000_000},
                }],
            })
        return {
            "id": "parent-draft",
            "duration": 3_000_000,
            "materials": {
                "stickers": stickers,
                "effects": effects,
                "drafts": [],
                "videos": [],
            },
            "tracks": tracks,
        }

    def test_wraps_all_stickers_with_outer_mix_and_alpha(self):
        draft = self.fixture()
        result = target.wrap_stickers_as_combination(draft, 3_000_000, str(self.output))

        sticker_tracks = [track for track in draft["tracks"] if track["type"] == "sticker"]
        combination_tracks = [track for track in draft["tracks"]
                              if track.get("name") == "贴纸复合片段"]
        self.assertEqual(sticker_tracks, [])
        self.assertEqual(len(combination_tracks), 1)

        segment = combination_tracks[0]["segments"][0]
        self.assertEqual(segment["clip"]["alpha"], 0.01)
        self.assertEqual(segment["material_id"], result["video_material_id"])
        self.assertEqual(segment["extra_material_refs"][0], result["draft_material_id"])

        video_ids = {item["id"] for item in draft["materials"]["videos"]}
        draft_ids = {item["id"] for item in draft["materials"]["drafts"]}
        effect_ids = {item["id"] for item in draft["materials"]["effects"]}
        self.assertIn(result["video_material_id"], video_ids)
        self.assertIn(result["draft_material_id"], draft_ids)
        self.assertTrue(effect_ids.intersection(segment["extra_material_refs"]))
        self.assertFalse({"old-mix-0", "old-mix-1"}.intersection(effect_ids))

        embedded = draft["materials"]["drafts"][0]["draft"]
        self.assertEqual(len(embedded["tracks"]), 2)
        self.assertTrue(all(track["type"] == "sticker" for track in embedded["tracks"]))
        for track in embedded["tracks"]:
            inner = track["segments"][0]
            self.assertEqual(inner["clip"]["alpha"], 1.0)
            self.assertEqual(inner["extra_material_refs"], [])

        subdraft = self.output / "subdraft" / result["subdraft_id"]
        saved = json.loads((subdraft / "draft_content.json").read_text(encoding="utf-8"))
        config = json.loads((subdraft / "sub_draft_config.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["id"], result["subdraft_id"])
        self.assertEqual(config["id"], result["subdraft_id"])
        self.assertEqual(config["rough_cut_duration"], 3_000_000)

    def test_no_sticker_tracks_is_a_noop(self):
        draft = self.fixture()
        draft["tracks"] = [draft["tracks"][0]]
        self.assertIsNone(target.wrap_stickers_as_combination(
            draft, 3_000_000, str(self.output)))
        self.assertFalse((self.output / "subdraft").exists())


if __name__ == "__main__":
    unittest.main()
