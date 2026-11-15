"""Zero-key validation of EveDirector R0, independent of Backlot canonical state."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ed_native_r0", ROOT / "scripts" / "evedirector_programmatic.py")
assert spec and spec.loader
ed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ed)


class ProgrammaticR0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_path = ROOT / "examples" / "native-video" / "program.json"
        cls.source_path = ROOT / "examples" / "native-video" / "source" / "README.md"
        cls.plan = json.loads(cls.plan_path.read_text(encoding="utf-8"))
        cls.source = cls.source_path.read_bytes()
        cls.styles = ROOT / "styles"

    def checked(self, plan=None, source=None):
        return ed.validate(self.plan if plan is None else plan,
                           self.source if source is None else source, self.styles)

    def test_valid_source_anchors_and_hash(self):
        receipt = self.checked()
        self.assertTrue(receipt["candidate_only"])
        self.assertEqual([x["line_start"] for x in receipt["anchors"]], [3, 4])
        self.assertEqual(len(receipt["program_sha256"]), 64)
        self.assertEqual(receipt["external_assets"], 0)

    def test_repeated_validation_is_identical(self):
        self.assertEqual(ed._canonical_json(self.checked()), ed._canonical_json(self.checked()))

    def test_unanchored_claim_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["scenes"][0]["source_contains"] = "an invented unsupported conclusion"
        with self.assertRaisesRegex(ed.ProgramError, "no matching source"):
            self.checked(plan)

    def test_missing_or_bad_source_rejected(self):
        with self.assertRaises(ed.ProgramError):
            self.checked(source=b"not the original document")
        with self.assertRaises(ed.ProgramError):
            self.checked(source=b"\xff\xfe")

    def test_timeline_gap_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["scenes"][1]["start_frame"] = 31
        with self.assertRaisesRegex(ed.ProgramError, "gap"):
            self.checked(plan)

    def test_duplicate_scene_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["scenes"][1]["id"] = "intro"
        with self.assertRaisesRegex(ed.ProgramError, "duplicate"):
            self.checked(plan)

    def test_reject_code_injection_or_unknown_primitive(self):
        plan = copy.deepcopy(self.plan)
        plan["scenes"][0]["layers"][0]["kind"] = "python_eval"
        with self.assertRaisesRegex(ed.ProgramError, "unknown render primitive"):
            self.checked(plan)
        plan = copy.deepcopy(self.plan)
        plan["scenes"][0]["layers"][0]["script"] = "__import__('os').system('echo bad')"
        with self.assertRaisesRegex(ed.ProgramError, "unknown"):
            self.checked(plan)

    def test_external_asset_path_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["scenes"][0]["layers"][0]["src"] = "https://untrusted.invalid/image.png"
        with self.assertRaisesRegex(ed.ProgramError, "unknown"):
            self.checked(plan)

    def test_style_path_traversal_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["style"] = "../private"
        with self.assertRaisesRegex(ed.ProgramError, "safe slug"):
            self.checked(plan)

    def test_keyframe_out_of_bounds_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan["scenes"][1]["layers"][1]["keyframes"]["width"][1]["frame"] = 300
        with self.assertRaisesRegex(ed.ProgramError, "keyframe.frame"):
            self.checked(plan)

    def test_keyframe_math(self):
        track = {"x": 17, "keyframes": {"x": [
            {"frame": 0, "value": 10}, {"frame": 10, "value": 110}
        ]}}
        self.assertEqual(ed._value(track, "x", 0), 10)
        self.assertEqual(ed._value(track, "x", 5), 60)
        self.assertEqual(ed._value(track, "x", 11), 110)

    def test_frame_is_not_static(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow unavailable")
        receipt = self.checked()
        a = ed.draw_frame(self.plan, receipt, 0)
        b = ed.draw_frame(self.plan, receipt, 29)
        self.assertNotEqual(a.tobytes(), b.tobytes())
        self.assertEqual(a.size, (640, 360))

    def test_local_mp4_smoke_optional(self):
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            self.skipTest("FFmpeg/FFprobe unavailable")
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow unavailable")
        small = copy.deepcopy(self.plan)
        small["frames"] = 6
        small["scenes"] = [small["scenes"][0]]
        small["scenes"][0]["end_frame"] = 6
        for layer in small["scenes"][0]["layers"]:
            for points in layer.get("keyframes", {}).values():
                for point in points:
                    point["frame"] = min(point["frame"], 5)
                unique = {point["frame"]: point for point in points}
                points[:] = [unique[k] for k in sorted(unique)]
        receipt = self.checked(small)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "test.mp4"
            rendered = ed.render(small, receipt, out)
            self.assertEqual(rendered["render"]["status"], "VERIFIED_LOCAL")
            self.assertEqual(rendered["render"]["ffprobe_stream"]["codec_name"], "h264")
            self.assertTrue(out.is_file())
            with self.assertRaisesRegex(ed.ProgramError, "exists"):
                ed.render(small, receipt, out)


if __name__ == "__main__":
    unittest.main()
