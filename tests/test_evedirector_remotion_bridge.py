"""R1 source-linked Remotion bridge contract and negative tests. No external keys."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evedirector_remotion_bridge as bridge
import evedirector_r1_vectors as vectors


class RemotionBridgeR1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan_path = ROOT / "examples/native-video/program.json"
        cls.source_path = ROOT / "examples/native-video/source/README.md"
        cls.styles = ROOT / "styles"
        cls.plan = json.loads(cls.plan_path.read_text(encoding="utf-8"))
        cls.source = cls.source_path.read_bytes()

    def export(self, plan=None, source=None, styles=None):
        return bridge.build_props(self.plan if plan is None else plan,
                                  self.source if source is None else source,
                                  self.styles if styles is None else styles)

    def test_export_grounding_and_timeline(self):
        b = self.export()["bundle"]
        self.assertEqual(b["schema"], bridge.BUNDLE_SCHEMA)
        self.assertTrue(b["candidate_only"] and b["review_required"])
        self.assertFalse(b["canonical_spec_mutated"])
        self.assertFalse(b["source_approval_verified"])
        self.assertEqual(b["durationInFrames"], 60)
        self.assertEqual([(c["id"], c["from"], c["durationInFrames"]) for c in b["clips"]],
                         [("intro", 0, 30), ("outro", 30, 30)])
        lines = self.source.decode("utf-8").splitlines()
        for c in b["clips"]:
            a = c["source"]
            self.assertIn(a["source_contains"], lines[a["line_start"] - 1])
            self.assertEqual(a["logical_line_sha256"], hashlib.sha256(
                lines[a["line_start"] - 1].encode("utf-8")).hexdigest())

    def test_deterministic_export(self):
        self.assertEqual(bridge.r0._canonical_json(self.export()), bridge.r0._canonical_json(self.export()))
        self.assertEqual(bridge.build_receipt(self.export()), bridge.build_receipt(self.export()))

    def test_reference_vectors(self):
        result = vectors.generate(self.plan, self.source, self.styles)
        self.assertEqual(len(result["vectors"]), 175)
        self.assertEqual(result["r0_program_sha256"], self.export()["bundle"]["program_sha256"])
        for v in result["vectors"]:
            scene = next(s for s in self.plan["scenes"] if s["id"] == v["scene"])
            layer = next(l for l in scene["layers"] if l["id"] == v["layer"])
            self.assertAlmostEqual(bridge.r0._value(layer, v["field"], v["frame"]), v["value"], places=9)

    def test_replay_receipt(self):
        props = self.export()
        receipt = bridge.build_receipt(props)
        self.assertEqual(receipt, bridge.verify(props, self.plan, self.source, self.styles, receipt))
        self.assertEqual(receipt["render_status"], "NOT_RENDERED_BY_REMOTION")

    def test_tampered_geometry_rejected(self):
        props = self.export()
        props["bundle"]["clips"][0]["layers"][0]["x"] += 1
        with self.assertRaisesRegex(bridge.r0.ProgramError, "props differ"):
            bridge.verify(props, self.plan, self.source, self.styles)

    def test_tampered_source_line_rejected(self):
        props = self.export()
        props["bundle"]["clips"][0]["source"]["line_start"] = 1
        with self.assertRaisesRegex(bridge.r0.ProgramError, "props differ"):
            bridge.verify(props, self.plan, self.source, self.styles)

    def test_mutated_document_rejected(self):
        with self.assertRaises(bridge.r0.ProgramError):
            bridge.verify(self.export(), self.plan, self.source.replace(b"motion", b"motion!", 1), self.styles)

    def test_changed_plan_rejected(self):
        props = self.export()
        plan = copy.deepcopy(self.plan)
        plan["title"] = "Unreviewed"
        with self.assertRaisesRegex(bridge.r0.ProgramError, "props differ"):
            bridge.verify(props, plan, self.source, self.styles)

    def test_style_drift_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            style = (self.styles / "evemiss-native-demo.yaml").read_text(encoding="utf-8")
            (folder / "evemiss-native-demo.yaml").write_text(style.replace("#59DBE5", "#59DBE6"), encoding="utf-8")
            with self.assertRaisesRegex(bridge.r0.ProgramError, "props differ"):
                bridge.verify(self.export(), self.plan, self.source, folder)

    def test_wrong_receipt_rejected(self):
        props = self.export()
        receipt = bridge.build_receipt(props)
        receipt["clip_count"] = 99
        with self.assertRaisesRegex(bridge.r0.ProgramError, "receipt differs"):
            bridge.verify(props, self.plan, self.source, self.styles, receipt)

    def test_unsafe_layer_rejected_by_r0(self):
        plan = copy.deepcopy(self.plan)
        plan["scenes"][0]["layers"][0]["command"] = "rm -rf /"
        with self.assertRaisesRegex(bridge.r0.ProgramError, "unknown"):
            self.export(plan=plan)

    def test_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(bridge.r0.ProgramError, "duplicate JSON key"):
                bridge.read_strict_json(path)

    def test_nan_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nan.json"
            path.write_text('{"x": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(bridge.r0.ProgramError, "invalid JSON constant"):
                bridge.read_strict_json(path)

    def test_large_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "too-large.md"
            path.write_bytes(b"A" * (bridge.MAX_SOURCE_BYTES + 1))
            with self.assertRaisesRegex(bridge.r0.ProgramError, "source exceeds"):
                bridge.read_source(path)

    def test_overwrite_requires_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "props.json"
            path.write_bytes(b"old")
            with self.assertRaisesRegex(bridge.r0.ProgramError, "exists"):
                bridge.write_new_atomic(path, b"new", False)
            self.assertEqual(path.read_bytes(), b"old")
            bridge.write_new_atomic(path, b"new", True)
            self.assertEqual(path.read_bytes(), b"new")

    def test_roundtrip_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            props, receipt = Path(tmp) / "props.json", Path(tmp) / "receipt.json"
            args = ["--plan", str(self.plan_path), "--source", str(self.source_path),
                    "--props", str(props), "--receipt", str(receipt)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bridge.main(["export", *args]), 0)
                self.assertEqual(bridge.main(["verify", *args]), 0)
                self.assertEqual(bridge.main(["export", *args]), 2)
            bad = bridge.read_strict_json(props)
            bad["bundle"]["clips"][0]["durationInFrames"] -= 1
            props.write_text(json.dumps(bad), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bridge.main(["verify", *args]), 2)


if __name__ == "__main__":
    unittest.main()
