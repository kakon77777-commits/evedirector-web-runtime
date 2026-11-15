"""R10 CI transport-only integration: real Native R0 MP4 + MOCK EVOE video + ORDR DTO.

The mock does not validate or demonstrate the actual privately licensed EVOE
renderer. A real EVOE installation may be used separately with R9's CLI.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'tests'/'support'))
import evedirector_plugin_hub as hub
import evedirector_scene_ir_r10 as r10
from r10_mock_evoe import install


def main(argv=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    root=args.output
    if root.exists():raise ValueError('CI example output must be new')
    root.mkdir(parents=True)
    input_root=ROOT/'examples/native-video'
    runs=root/'runs'
    mock=install(root/'mock-only-evoe-transport')
    for name in ('native-r0.request.json','ordr-snapshot.request.json'):
        req=hub.json_read(input_root/'plugins'/name,hub.MAX_REQUEST)
        hub.run(req,input_root,runs)
    evoe=hub.json_read(input_root/'plugins/r10-evoe-60.request.json',hub.MAX_REQUEST)
    hub.run(evoe,input_root,runs,evoe_root=mock,allow_external=True)
    draft=hub.json_read(input_root/'plugins/r10-composition.draft.json',r10.MAX_DRAFT)
    ir=r10.lock(draft,input_root,runs)
    (root/'scene-ir.locked.json').write_bytes(hub.canonical(ir))
    receipt=r10.compose(ir,input_root,runs,root/'composition')
    checked=r10.verify(root/'composition'/ir['candidate_id'],input_root,runs)
    assert checked['status']=='PASS_BOUNDED_REPLAY' and receipt['ordr_spatial_visualization'] is False
    state={'schema':'evedirector.r10_ci_evidence.v1','status':'PASS_CANDIDATE_ONLY',
           'mock_evoe_not_real_engine':True,'native_r0_real_video':True,
           'ordr_core_not_executed':True,'ordr_spatial_visualization':False,
           'composition_sha256':checked['composition_sha256'],
           'human_approved':False,'published':False}
    (root/'CI_R10_EVIDENCE.json').write_bytes(hub.canonical(state))
    print(json.dumps(state,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
