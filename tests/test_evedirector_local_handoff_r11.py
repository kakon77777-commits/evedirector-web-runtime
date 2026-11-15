"""R11 isolated tests. EVOE is a TRANSPORT STUB, never the private engine."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests' / 'support'))
import evedirector_local_handoff_r11 as r11
import evedirector_plugin_hub as hub
import evedirector_scene_ir_r10 as r10
from r10_mock_evoe import install


class R11LocalHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='evedirector-r11-')
        cls.root = Path(cls.temp.name)
        cls.mock = install(cls.root / 'test-only-evoe-mock')
        for f in ('spec.py', 'render.py'):
            (cls.mock / 'src' / 'evoe' / f).write_text('# MOCK ONLY: test suite\n', encoding='utf-8')
        cls.inputs = ROOT / 'examples' / 'native-video'
        cls.outputs = cls.root / 'handoffs'
        cls.core = cls.root / 'ordr-core-fixture'
        (cls.core / 'src').mkdir(parents=True)
        (cls.core / 'Cargo.toml').write_text('ordr-core test fixture\n', encoding='utf-8')
        (cls.core / 'src/adapter.rs').write_text('// test only\n', encoding='utf-8')
        cls.adapters = cls.root / 'ordr-adapters-fixture'
        (cls.adapters / 'src').mkdir(parents=True)
        (cls.adapters / 'Cargo.toml').write_text('ordr-adapters test fixture\n', encoding='utf-8')
        (cls.adapters / 'src/lib.rs').write_text('// test only\n', encoding='utf-8')
        cls.output = None
        if shutil.which('ffmpeg') and shutil.which('ffprobe'):
            cls.receipt = r11.stage(
                input_root=cls.inputs, output_root=cls.outputs, candidate_id='r11_mock_test',
                evoe_root=cls.mock, allow_local_engines=True,
                ordr_core=cls.core, ordr_adapters=cls.adapters)
            cls.output = cls.outputs / 'r11_mock_test'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def require_video(self):
        if self.output is None:
            self.skipTest('ffmpeg/ffprobe unavailable')

    def test_doctor_missing_is_read_only(self):
        result = r11.doctor()
        self.assertFalse(result['evoe_cli_ready'])
        self.assertFalse(result['external_code_executed'])
        self.assertFalse(result['ordr_core_executed'])

    def test_doctor_private_source_fingerprints_not_raw_source(self):
        result = r11.doctor(self.mock, self.core, self.adapters)
        self.assertTrue(result['evoe_cli_ready'])
        self.assertTrue(result['ordr_v1_contract_inspectable'])
        self.assertEqual([i['engine'] for i in result['engines']], ['EVOE', 'ORDR-Core', 'ORDR-Adapters'])
        for engine in result['engines']:
            self.assertFalse(engine['private_source_embedded'])
            self.assertFalse(engine['source_identity_verified'])
        self.assertNotIn(str(self.mock), json.dumps(result))

    def test_adapters_without_core_rejected(self):
        with self.assertRaises(r11.HandoffError):
            r11.doctor(self.mock, None, self.adapters)

    def test_bad_engine_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'src/evoe').mkdir(parents=True)
            (Path(td) / 'src/evoe/cli.py').write_text('# stub\n', encoding='utf-8')
            with self.assertRaises(r11.HandoffError):
                r11.doctor(Path(td))

    def test_explicit_consent_required(self):
        target = self.root / 'blocked'
        with self.assertRaisesRegex(r11.HandoffError, 'explicit'):
            r11.stage(input_root=self.inputs, output_root=target, candidate_id='blocked',
                      evoe_root=self.mock, allow_local_engines=False)
        self.assertFalse(target.exists())

    def test_missing_engine_root_denied(self):
        with self.assertRaisesRegex(r11.HandoffError, 'explicit'):
            r11.stage(input_root=self.inputs, output_root=self.root/'none', candidate_id='none',
                      evoe_root=None, allow_local_engines=True)

    def test_private_checkout_is_not_an_output_directory(self):
        with self.assertRaisesRegex(r11.HandoffError, 'outside protected'):
            r11.stage(input_root=self.inputs, output_root=self.mock/'output',
                      candidate_id='blocked', evoe_root=self.mock, allow_local_engines=True)
        self.assertFalse((self.mock/'output').exists())

    def test_input_corpus_is_not_an_output_directory(self):
        with self.assertRaisesRegex(r11.HandoffError, 'outside protected'):
            r11.stage(input_root=self.inputs, output_root=self.inputs/'handoff-output',
                      candidate_id='blocked', evoe_root=self.mock, allow_local_engines=True)

    def test_mock_pipeline_source_receipts_and_authority(self):
        self.require_video()
        r = self.receipt
        self.assertEqual(r['schema'], r11.SCHEMA)
        self.assertTrue(r['evoe_subprocess_executed'])
        for field in ('evoe_engine_authenticity_independently_verified', 'ordr_core_executed',
                      'ordr_source_authenticity_verified', 'canonical_write', 'published', 'human_approved'):
            self.assertFalse(r[field])
        self.assertEqual(set(r['runs_sha256']), set(r11.RUN_IDS))
        self.assertEqual(set(r['input_sha256']), set(r11.INPUT_FILES))
        self.assertTrue((self.output/'composition/r10_native_evoe_ordr_composite/candidate.mp4').is_file())

    def test_offline_replay_does_not_rerun_private_engine(self):
        self.require_video()
        result = r11.verify(self.output)
        self.assertEqual(result['status'], 'PASS_BOUNDED_OFFLINE_REPLAY')
        self.assertFalse(result['engine_rerun_performed'])
        self.assertFalse(result['real_evoe_authenticity_attested'])

    def test_candidate_never_overwrites(self):
        self.require_video()
        with self.assertRaisesRegex(r11.HandoffError, 'append-only'):
            r11.stage(input_root=self.inputs, output_root=self.outputs,
                      candidate_id='r11_mock_test', evoe_root=self.mock, allow_local_engines=True)

    def test_bad_candidate_ids_denied(self):
        for candidate in ('../unsafe', 'A', 'abc/../x', 'a:b'):
            with self.subTest(candidate=candidate), self.assertRaises(hub.PluginError):
                r11.stage(input_root=self.inputs, output_root=self.outputs,
                          candidate_id=candidate, evoe_root=self.mock, allow_local_engines=True)

    def _tampered_copy(self):
        self.require_video()
        td = tempfile.TemporaryDirectory()
        folder = Path(td.name) / 'candidate'
        shutil.copytree(self.output, folder)
        return td, folder

    def test_tampered_source_rejected(self):
        td, p = self._tampered_copy()
        try:
            path = p / 'inputs/source/r10-plugin-composition.md'
            path.write_bytes(path.read_bytes() + b' tampered\n')
            with self.assertRaises(r11.HandoffError):
                r11.verify(p)
        finally:
            td.cleanup()

    def test_tampered_video_rejected(self):
        td, p = self._tampered_copy()
        try:
            path = p / 'composition/r10_native_evoe_ordr_composite/candidate.mp4'
            with path.open('ab') as f:
                f.write(b'altered')
            with self.assertRaises((r11.HandoffError, r10.SceneIRError, hub.PluginError)):
                r11.verify(p)
        finally:
            td.cleanup()

    def test_tampered_plugin_receipt_rejected(self):
        td, p = self._tampered_copy()
        try:
            path = p / 'runs/evoe_geometry_demo_r10/run-receipt.json'
            path.write_bytes(path.read_bytes() + b'\n')
            with self.assertRaises(r11.HandoffError):
                r11.verify(p)
        finally:
            td.cleanup()

    def test_permission_forgery_rejected(self):
        td, p = self._tampered_copy()
        try:
            path = p / 'handoff-receipt.json'
            data = hub.json_read(path)
            data['canonical_write'] = True
            path.write_bytes(hub.canonical(data))
            with self.assertRaisesRegex(r11.HandoffError, 'authority'):
                r11.verify(p)
        finally:
            td.cleanup()

    def test_linked_artifact_rejected(self):
        td, p = self._tampered_copy()
        try:
            path = p / 'inputs/program.json'
            spare = p / 'replacement.json'
            shutil.copyfile(path, spare)
            path.unlink()
            try:
                path.symlink_to(spare)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unsupported')
            with self.assertRaises(r11.HandoffError):
                r11.verify(p)
        finally:
            td.cleanup()


if __name__ == '__main__':
    unittest.main()
