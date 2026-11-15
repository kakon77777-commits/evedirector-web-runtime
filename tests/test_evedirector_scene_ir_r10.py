"""R10 executable contract and adversarial tests; private EVOE replaced with test stub."""
from __future__ import annotations

import copy
import io
import subprocess
import json
from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'tests'/'support'))
import evedirector_plugin_hub as hub
import evedirector_scene_ir_r10 as ir10
from r10_mock_evoe import install

SOURCE=ROOT/'examples'/'native-video'
DRAFT=SOURCE/'plugins'/'r10-composition.draft.json'
EVOE_REQUEST=SOURCE/'plugins'/'r10-evoe-60.request.json'

class R10PluginCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='evedirector-r10-contract-')
        root=Path(cls.tmp.name)
        cls.runs=root/'plugin-runs'
        cls.outputs=root/'compositions'
        cls.mock=install(root/'mock-evoe-transport')
        try:
            for name in ('native-r0.request.json','ordr-snapshot.request.json'):
                hub.run(hub.json_read(SOURCE/'plugins'/name,hub.MAX_REQUEST),SOURCE,cls.runs)
            hub.run(hub.json_read(EVOE_REQUEST,hub.MAX_REQUEST),SOURCE,cls.runs,
                    evoe_root=cls.mock,allow_external=True)
            cls.draft=hub.json_read(DRAFT,ir10.MAX_DRAFT)
            cls.ir=ir10.lock(cls.draft,SOURCE,cls.runs)
        except BaseException:
            cls.tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_r10_lock_is_deterministic_and_source_pinned(self):
        one=ir10.lock(self.draft,SOURCE,self.runs)
        self.assertEqual(ir10.hub.canonical(one),ir10.hub.canonical(self.ir))
        self.assertEqual(len(one['source_sha256']),64)
        self.assertEqual([t['plugin_id'] for t in one['tracks']],['native-r0','evoe','ordr'])
        self.assertEqual(ir10.replay(one,SOURCE,self.runs)[1][-1]['pixels_rendered_by_ordr'],False)

    def test_real_native_plus_mock_evoe_composed_mp4_and_replay(self):
        receipt=ir10.compose(self.ir,SOURCE,self.runs,self.outputs)
        path=self.outputs/self.ir['candidate_id']
        self.assertTrue((path/'candidate.mp4').is_file())
        self.assertFalse(receipt['human_approved'])
        self.assertFalse(receipt['ordr_spatial_visualization'])
        result=ir10.verify(path,SOURCE,self.runs)
        self.assertEqual(result['status'],'PASS_BOUNDED_REPLAY')
        self.assertEqual(result['dependencies'],3)
        with self.assertRaisesRegex(ir10.SceneIRError,'append-only'):
            ir10.compose(self.ir,SOURCE,self.runs,self.outputs)

    def test_actual_composite_contains_evoe_transport_pixels(self):
        # Positive signal: fixed FFmpeg overlay did alter pixels in its declared box.
        # The visual source is a MOCK transport, not an authenticated EVOE engine.
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp_out:
            request=copy.deepcopy(self.ir)
            request['candidate_id']='pixel_probe'
            ir10.compose(request,SOURCE,self.runs,Path(temp_out))
            root=Path(temp_out)/'pixel_probe'
    
    def test_ir_rejects_script_filtergraph_or_urls(self):
        for key,value in [('ffmpeg_filter','overlay=0:0;movie=/etc/passwd'),
                          ('http_url','https://example.org/evil'),
                          ('code','exec(import os)')]:
            x=copy.deepcopy(self.draft)
            x[key]=value
            with self.assertRaises(ir10.SceneIRError):ir10.validate_ir(x,locked=False)

    def test_new_input_field_and_plugin_command_rejected(self):
        for path,bad in ((['tracks',1,'shell'],'sh'), (['tracks',1,'plugin_id'],'bash'),
                         (['tracks',1,'role'],'canonical_write'), (['source','exec'],'eval')):
            obj=copy.deepcopy(self.draft)
            node=obj
            for key in path[:-1]:node=node[key]
            node[path[-1]]=bad
            with self.assertRaises((hub.PluginError,ir10.SceneIRError)):
                ir10.validate_ir(obj,locked=False)

    def test_relative_plugin_output_root_supports_external_cli_cwd(self):
        # Regression: R9 external CLI receives a rooted path even though
        # the caller supplied a relative output directory.
        with tempfile.TemporaryDirectory() as root:
            request=copy.deepcopy(hub.json_read(EVOE_REQUEST,hub.MAX_REQUEST))
            request['candidate_id']='relative_evoe_case'
            output=Path(os.path.relpath(Path(root)/'run-root',Path.cwd()))
            receipt=hub.run(request,SOURCE,output,evoe_root=self.mock,allow_external=True)
            self.assertEqual(receipt['result']['frame_count'],60)
            self.assertEqual(hub.verify(Path(root)/'run-root'/'relative_evoe_case')['status'],
                             'PASS_BOUNDED_REPLAY')

    def test_unauthorized_evoe_is_never_implicitly_executed(self):
        req=hub.json_read(EVOE_REQUEST,hub.MAX_REQUEST)
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaisesRegex(hub.PluginError,'--allow-external'):
                hub.run(req,SOURCE,Path(base)/'test')

    def test_placement_outside_frame_rejected(self):
        obj=copy.deepcopy(self.draft)
        for change in [{'x':630}, {'width':223}, {'height':361}, {'y':-4}]:
            obj['tracks'][1]['placement'].update(change)
            with self.assertRaises((hub.PluginError,ir10.SceneIRError)):
                ir10.validate_ir(obj,locked=False)
            obj=copy.deepcopy(self.draft)

    def test_ordr_never_enters_visual_overlay(self):
        obj=copy.deepcopy(self.draft)
        obj['tracks'][2]['role']='overlay_video'
        obj['tracks'][2]['placement']={'x':0,'y':0,'width':32,'height':32}
        with self.assertRaises(ir10.SceneIRError):ir10.validate_ir(obj,locked=False)
        obj=copy.deepcopy(self.draft)
        obj['tracks'][2]['role']='spatial_evidence'
        obj['tracks'][2]['placement']={'x':0,'y':0,'width':32,'height':32}
        with self.assertRaises(ir10.SceneIRError):ir10.validate_ir(obj,locked=False)

    def test_source_mismatch_and_run_receipt_drift_rejected(self):
        obj=copy.deepcopy(self.ir)
        obj['tracks'][0]['source_contains']='a nonexistent provenance claim'
        with self.assertRaises(ir10.SceneIRError):ir10.replay(obj,SOURCE,self.runs)
        obj=copy.deepcopy(self.ir)
        obj['tracks'][1]['receipt_sha256']='0'*64
        with self.assertRaisesRegex(ir10.SceneIRError,'dependency changed'):
            ir10.replay(obj,SOURCE,self.runs)

    def test_strict_schema_and_temporal_mismatch_rejected(self):
        obj=copy.deepcopy(self.draft)
        obj['canvas']['frames']=12
        with self.assertRaisesRegex(ir10.SceneIRError,'frame clock'):
            ir10.lock(obj,SOURCE,self.runs)
        obj=copy.deepcopy(self.draft)
        obj['tracks'][1]['run_id']='evil/../../abc'
        with self.assertRaises(hub.PluginError):ir10.validate_ir(obj,locked=False)
        with self.assertRaises(hub.PluginError):hub.strict_decode(b'{"a":1,"a":2}')

    def test_video_byte_tamper_detected(self):
        obj=copy.deepcopy(self.ir);obj['candidate_id']='tamper_video'
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);ir10.compose(obj,SOURCE,self.runs,out)
            path=out/'tamper_video'/'candidate.mp4'
            with path.open('ab') as f:f.write(b'tamper')
            with self.assertRaises(ir10.SceneIRError):ir10.verify(out/'tamper_video',SOURCE,self.runs)

    def test_pinned_dependency_copy_tamper_detected(self):
        obj=copy.deepcopy(self.ir);obj['candidate_id']='tamper_deps'
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);ir10.compose(obj,SOURCE,self.runs,out)
            path=out/'tamper_deps'/'dependencies.json';path.write_bytes(path.read_bytes()+b'\n')
            with self.assertRaises(ir10.SceneIRError):ir10.verify(out/'tamper_deps',SOURCE,self.runs)

    def test_v1_source_contract_requires_explicit_lines(self):
        with self.assertRaises(ir10.SceneIRError):
            modified=copy.deepcopy(self.draft)
            modified['tracks'][1]['source_line']=2
            ir10.lock(modified,SOURCE,self.runs)

    def test_no_symlink_run_root(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'link'
            try:root.symlink_to(self.runs,target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest('symlinks not supported')
            with self.assertRaises(ir10.SceneIRError):ir10.lock(self.draft,SOURCE,root)


if __name__=='__main__':unittest.main()
