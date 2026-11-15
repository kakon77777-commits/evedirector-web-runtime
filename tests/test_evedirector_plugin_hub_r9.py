"""R9 plugin host contracts: no arbitrary execution and exact candidate receipts."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evedirector_plugin_hub as hub

INPUTS = ROOT / "examples" / "native-video"
REQUESTS = INPUTS / "plugins"


class PluginHostR9Tests(unittest.TestCase):
    def test_catalog_and_capability_contract(self):
        entries=hub.catalog()
        self.assertEqual({p['plugin_id'] for p in entries},{'native-r0','evoe','ordr'})
        for entry in entries:
            self.assertFalse(entry['authority']['canonical_write'])
            self.assertFalse(entry['authority']['network'])
            self.assertFalse(entry['authority']['publish'])
        self.assertEqual(hub.doctor('ordr')['ordr_core_connected'],False)

    def test_request_validation(self):
        for file in REQUESTS.glob('*.request.json'):
            obj=hub.json_read(file,hub.MAX_REQUEST)
            self.assertEqual(hub.resolve_request(obj),obj)

    def test_unknown_plugin_operation_rejected(self):
        obj=hub.json_read(REQUESTS/'evoe-animation.request.json')
        for value in ('shell','eval','canonical_write','python'):
            altered=copy.deepcopy(obj);altered['operation']=value
            with self.assertRaises(hub.PluginError):hub.resolve_request(altered)

    def test_hidden_shell_key_rejected(self):
        obj=hub.json_read(REQUESTS/'evoe-animation.request.json')
        obj['inputs']['command']='python -c "print(1)"'
        with self.assertRaises(hub.PluginError):hub.resolve_request(obj)

    def test_evoe_no_implicit_execution(self):
        req=hub.json_read(REQUESTS/'evoe-animation.request.json')
        with tempfile.TemporaryDirectory() as base:
            out=Path(base)/'out'
            with self.assertRaisesRegex(hub.PluginError,'--allow-external'):
                hub.run(req,INPUTS,out)
            self.assertFalse((out/req['candidate_id']).exists())

    def test_evoe_invalid_params(self):
        obj=hub.json_read(REQUESTS/'evoe-animation.request.json')
        for key,bad in [('size',63),('size',1024),('frame_count',101),('fps',0),('samples',0),('frame_count',True)]:
            modified=copy.deepcopy(obj);modified['inputs'][key]=bad
            with self.assertRaises(hub.PluginError):hub.resolve_request(modified)

    def test_duplicate_keys_and_nonfinite_json_rejected(self):
        for bad in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
            with self.assertRaises(hub.PluginError):hub.strict_decode(bad)

    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as base:
            for name in ('../secret.json','/etc/passwd','..\\secret.json','C:/Windows/system.ini'):
                with self.assertRaises(hub.PluginError):hub.safe_relative(INPUTS,name)
            symlink=Path(base)/'in'
            try:symlink.symlink_to(INPUTS,target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
            with self.assertRaises(hub.PluginError):hub.safe_relative(symlink,'program.json')

    def test_ordr_projection_success_and_replay(self):
        req=hub.json_read(REQUESTS/'ordr-snapshot.request.json')
        with tempfile.TemporaryDirectory() as base:
            out=Path(base)
            report=hub.run(req,INPUTS,out)
            self.assertEqual(report['result']['region_count'],2)
            self.assertFalse(report['canonical_write'])
            self.assertFalse(report['result']['origin_verified_by_ordr_core'])
            self.assertEqual(hub.verify(out/req['candidate_id'])['status'],'PASS_BOUNDED_REPLAY')
            with self.assertRaisesRegex(hub.PluginError,'already exists'):
                hub.run(req,INPUTS,out)

    def test_ordr_read_only_rejects_conflict_and_semantic(self):
        src=hub.json_read(REQUESTS/'ordr-synthetic-snapshot.json')
        for key,value in [('demand',{'region':'unknown'}),('pending_request',{}),('conflicts',[{}])]:
            modified=copy.deepcopy(src);modified['regions'][0][key]=value
            with self.assertRaises(hub.PluginError):hub.inspect_ordr(modified)
        modified=copy.deepcopy(src);modified['regions'][0]['layers']=[{'component':'semantic_structure'}]
        with self.assertRaises(hub.PluginError):hub.inspect_ordr(modified)

    def test_ordr_duplicate_and_stale_contract(self):
        src=hub.json_read(REQUESTS/'ordr-synthetic-snapshot.json')
        bad=copy.deepcopy(src);bad['regions'].append(bad['regions'][0]);
        with self.assertRaises(hub.PluginError):hub.inspect_ordr(bad)
        bad=copy.deepcopy(src);bad['cursor']['contract_version']='1.1.0';
        with self.assertRaises(hub.PluginError):hub.inspect_ordr(bad)
        bad=copy.deepcopy(src);bad['cursor']['state_fingerprint']=-1
        with self.assertRaises(hub.PluginError):hub.inspect_ordr(bad)

    def test_tampered_report_rejected(self):
        req=hub.json_read(REQUESTS/'ordr-snapshot.request.json')
        with tempfile.TemporaryDirectory() as base:
            out=Path(base);hub.run(req,INPUTS,out)
            path=out/req['candidate_id']/'ordr_projection.json'
            path.write_text(path.read_text(encoding='utf-8')+'\n',encoding='utf-8')
            with self.assertRaises(hub.PluginError):hub.verify(out/req['candidate_id'])

    def test_native_real_mp4_and_replay(self):
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('FFmpeg not installed')
        try:import PIL,yaml  # noqa: F401
        except ImportError:self.skipTest('Pillow or PyYAML missing')
        req=hub.json_read(REQUESTS/'native-r0.request.json')
        with tempfile.TemporaryDirectory() as base:
            dest=Path(base)/'out';r=hub.run(req,INPUTS,dest)
            self.assertTrue((dest/req['candidate_id']/'candidate.mp4').is_file())
            self.assertEqual(r['result']['frames'],60)
            self.assertEqual(hub.verify(dest/req['candidate_id'])['status'],'PASS_BOUNDED_REPLAY')
            self.assertTrue((dest/req['candidate_id']/'styles'/'evemiss-native-demo.yaml').exists())
            c=dest/req['candidate_id']/'source.md';c.write_bytes(c.read_bytes()+b'\n')
            with self.assertRaises(hub.PluginError):hub.verify(dest/req['candidate_id'])

    def test_external_engine_no_secret_environment(self):
        # A deliberately fake local CLI tests ONLY the subprocess boundary, not EVOE's renderer.
        req=hub.json_read(REQUESTS/'evoe-animation.request.json')
        with tempfile.TemporaryDirectory() as base:
            root=Path(base);engine=root/'mock-evoe';(engine/'src/evoe').mkdir(parents=True)
            (engine/'src/evoe/__init__.py').write_text('',encoding='utf-8')
            (engine/'src/evoe/cli.py').write_text('''
import argparse,os,sys,json,struct,zlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('cmd');p.add_argument('--scene');p.add_argument('--times');p.add_argument('--size',type=int);p.add_argument('--samples');p.add_argument('--output');a=p.parse_args()
assert a.cmd=='animate'
assert 'SECRET_GITHUB_TOKEN' not in os.environ
out=Path(a.output);out.mkdir()
times=[float(x) for x in a.times.split(',')]
def png(size,color):
    def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    row=b'\\x00'+bytes(color)*size
    return b'\\x89PNG\\r\\n\\x1a\\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(row*size))+chunk(b'IEND',b'')
for i,t in enumerate(times):
    (out/f'frame_{i:03d}.png').write_bytes(png(a.size,(i*13%255,120,80)))
(out/'frames.json').write_text(json.dumps({'schema':'evoe.anim-sequence.v0.1','frame_times':times,'receipts':[{} for _ in times]}),encoding='utf-8')
''',encoding='utf-8')
            os.environ['SECRET_GITHUB_TOKEN']='TEST_DO_NOT_TRANSMIT'
            try:
                receipt=hub.run(req,INPUTS,root/'out',evoe_root=engine,allow_external=True)
            finally:os.environ.pop('SECRET_GITHUB_TOKEN',None)
            self.assertEqual(receipt['result']['frame_count'],12)
            self.assertEqual(hub.verify(root/'out'/req['candidate_id'])['status'],'PASS_BOUNDED_REPLAY')
            self.assertEqual(hub.doctor('evoe',engine)['available'],True)


if __name__=='__main__':unittest.main()
