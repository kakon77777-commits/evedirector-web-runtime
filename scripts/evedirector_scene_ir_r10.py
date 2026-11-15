#!/usr/bin/env python3
"""EveDirector R10: versioned scene IR & bounded, provenance-linked plugin composition.

Does NOT execute arbitrary AI code, clone repositories, modify ORDR Core, or
publish. Consumes existing R9 plugin run receipts. EVOE must be explicitly run
on a locally authorized installation before consumption (a fake CLI used in
unit tests is *not* an EVOE engine acceptance).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_plugin_hub as hub

DRAFT_SCHEMA = 'evedirector.scene_ir_draft.v1'
IR_SCHEMA = 'evedirector.scene_ir.v1'
RECEIPT_SCHEMA = 'evedirector.scene_ir_render_receipt.v1'
MAX_DRAFT = 64_000
MAX_SOURCE = 2_000_000
MAX_OUTPUT = 128 * 1024 * 1024
MAX_LAYERS = 5  # one base, up to three overlays, optional ORDR sidecar
HEX = re.compile(r'^[0-9a-f]{64}$')
COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')
ROLES = {'background_video': 'native-r0', 'overlay_video': 'evoe', 'spatial_evidence': 'ordr'}

class SceneIRError(ValueError):
    pass


def exact(v: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(v, dict) or set(v) - required - optional or required - set(v):
        raise SceneIRError('unknown or missing scene IR fields')
    return v


def safe_slug(v: Any) -> str:
    return hub.ident(v, 'scene IR slug')


def iint(v: Any, minimum: int, maximum: int, name: str) -> int:
    return hub.uint(v, minimum, maximum, name)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_file(input_root: Path, name: Any) -> tuple[Path, bytes]:
    file = hub.safe_relative(input_root, name, MAX_SOURCE)
    if file.suffix not in ('.md', '.markdown'):
        raise SceneIRError('source must be UTF-8 Markdown')
    raw = file.read_bytes()
    raw.decode('utf-8')
    return file, raw


def _track(t: dict, canvas: dict, locked: bool) -> None:
    fields = {'track_id','plugin_id','role','run_id','source_line','source_contains'}
    optional = {'placement'}
    if locked:
        fields.add('receipt_sha256')
    exact(t, fields, optional)
    for key in ('track_id', 'plugin_id', 'run_id'):
        safe_slug(t[key])
    role = t['role']
    if role not in ROLES or t['plugin_id'] != ROLES[role]:
        raise SceneIRError('role requires its reviewed plugin implementation')
    if locked and (not isinstance(t['receipt_sha256'],str) or not HEX.fullmatch(t['receipt_sha256'])):
        raise SceneIRError('run receipt pin missing')
    iint(t['source_line'],1,100000,'source_line')
    if not isinstance(t['source_contains'],str) or not 8<=len(t['source_contains'])<=240 or '\n' in t['source_contains']:
        raise SceneIRError('invalid source quote')
    if role == 'overlay_video':
        p = exact(t.get('placement'), {'x','y','width','height'})
        w,h = canvas['width'],canvas['height']
        for k in ('x','y'):
            iint(p[k],0,w if k=='x' else h,k)
        for k in ('width','height'):
            iint(p[k],4, w if k=='width' else h,k)
        if p['x']+p['width']>w or p['y']+p['height']>h:
            raise SceneIRError('overlay must fit entire output canvas')
        if p['width']%2 or p['height']%2 or p['x']%2 or p['y']%2:
            raise SceneIRError('YUV420 overlay requires even coordinates and dimensions')
    elif 'placement' in t:
        raise SceneIRError('only overlay_video may position pixels')


def validate_ir(ir: Any, *, locked: bool) -> dict:
    ir = exact(ir,{'schema','candidate_id','source','canvas','tracks'} | ({'source_sha256'} if locked else set()))
    if ir['schema'] != (IR_SCHEMA if locked else DRAFT_SCHEMA):
        raise SceneIRError('scene IR version not supported')
    safe_slug(ir['candidate_id'])
    s = exact(ir['source'],{'path'})
    if not isinstance(s['path'],str) or not s['path'] or len(s['path'])>240:
        raise SceneIRError('invalid source path')
    if locked and (not isinstance(ir['source_sha256'],str) or not HEX.fullmatch(ir['source_sha256'])):
        raise SceneIRError('source hash pin missing')
    c = exact(ir['canvas'],{'width','height','fps','frames'})
    iint(c['width'],160,1920,'width'); iint(c['height'],90,1080,'height')
    iint(c['fps'],1,60,'fps'); iint(c['frames'],2,1800,'frames')
    if c['width']%2 or c['height']%2:
        raise SceneIRError('canvas must be YUV420-compatible even dimensions')
    if c['width']*c['height']*c['frames']>250_000_000:
        raise SceneIRError('total pixel budget exceeded')
    tracks=ir['tracks']
    if not isinstance(tracks,list) or not 2<=len(tracks)<=MAX_LAYERS:
        raise SceneIRError('expected base, overlay(s), optional ORDR evidence')
    roles=[x.get('role') if isinstance(x,dict) else None for x in tracks]
    if roles[0]!='background_video' or roles.count('background_video')!=1 or roles.count('overlay_video')<1 or roles.count('spatial_evidence')>1:
        raise SceneIRError('single Native base followed by EVOE overlay and optional ORDR')
    if 'spatial_evidence' in roles and roles[-1]!='spatial_evidence':
        raise SceneIRError('ORDR metadata must be a nonvisual final evidence track')
    ids=set(); runs=set()
    for t in tracks:
        _track(t,c,locked)
        if t['track_id'] in ids or t['run_id'] in runs:
            raise SceneIRError('duplicate track ID or run ID')
        ids.add(t['track_id']);runs.add(t['run_id'])
    return ir


def _safe_run(run_root:Path,run_id:str)->Path:
    safe_slug(run_id)
    if run_root.is_symlink() or not run_root.is_dir():
        raise SceneIRError('run root missing or linked')
    p=run_root/run_id
    if p.is_symlink() or not p.is_dir() or p.resolve().parent!=run_root.resolve():
        raise SceneIRError('plugin run missing or symlinked')
    return p


def _source_anchors(ir: dict, input_root: Path) -> bytes:
    _, raw=source_file(input_root,ir['source']['path'])
    lines=raw.decode('utf-8').splitlines()
    for track in ir['tracks']:
        line=track['source_line']
        if line>len(lines) or track['source_contains'] not in lines[line-1]:
            raise SceneIRError('track source anchor is absent or changed')
    return raw


def _dependency(track:dict,run_root:Path,canvas:dict)->dict:
    directory=_safe_run(run_root,track['run_id'])
    run_receipt=hub.json_read(directory/'run-receipt.json',hub.MAX_REQUEST)
    # R9 checks each file digest and known output; it does not assert external EVOE authenticity.
    hub.verify(directory)
    if (run_receipt.get('plugin_id')!=track['plugin_id'] or
        run_receipt.get('operation')!={'native-r0':'render_video','evoe':'animate_frames','ordr':'inspect_snapshot'}[track['plugin_id']] or
        run_receipt.get('candidate_only') is not True or run_receipt.get('canonical_write') is not False or
        run_receipt.get('published') is not False):
        raise SceneIRError('R9 dependency authority/type mismatch')
    digest=sha((directory/'run-receipt.json').read_bytes())
    if 'receipt_sha256' in track and digest!=track['receipt_sha256']:
        raise SceneIRError('dependency changed after source lock')
    result=run_receipt.get('result',{})
    if track['role']!='spatial_evidence':
        if (result.get('fps')!=canvas['fps'] or
            result.get('frames',result.get('frame_count'))!=canvas['frames'] or
            not isinstance(result.get('resolution'),list) or len(result['resolution'])!=2):
            raise SceneIRError('all video plugins must match exact frame clock')
        video=directory/'candidate.mp4'
        # In addition to R9 verification, pin a decoded-video timing check.
        hub._ffprobe(video,frames=canvas['frames'],fps=canvas['fps'],width=result['resolution'][0],height=result['resolution'][1])
        if track['role']=='background_video' and result['resolution']!=[canvas['width'],canvas['height']]:
            raise SceneIRError('Native background must cover the target canvas')
    else:
        if result.get('origin_verified_by_ordr_core') is not False:
            raise SceneIRError('ORDR source authenticity must not be inferred from an offline JSON')
    return {'track_id':track['track_id'],'run_id':track['run_id'],'plugin_id':track['plugin_id'],
            'role':track['role'],'receipt_sha256':digest,'original_run_status':'PASS_BOUNDED_REPLAY',
            'source_authenticity':'NOT_ESTABLISHED_BY_THIS_HOST' if track['plugin_id']!='native-r0' else 'SOURCE_ANCHOR_REPLAYED',
            'pixels_rendered_by_ordr':False}


def lock(draft:dict,input_root:Path,run_root:Path)->dict:
    validate_ir(draft,locked=False)
    raw=_source_anchors(draft,input_root)
    pinned=json.loads(json.dumps(draft))
    pinned['schema']=IR_SCHEMA
    pinned['source_sha256']=sha(raw)
    for track in pinned['tracks']:
        track['receipt_sha256']=_dependency(track,run_root,pinned['canvas'])['receipt_sha256']
    validate_ir(pinned,locked=True)
    return pinned


def replay(ir:dict,input_root:Path,run_root:Path)->tuple[bytes,list[dict]]:
    validate_ir(ir,locked=True)
    raw=_source_anchors(ir,input_root)
    if sha(raw)!=ir['source_sha256']:
        raise SceneIRError('source Markdown changed after lock')
    return raw,[_dependency(t,run_root,ir['canvas']) for t in ir['tracks']]


def _compose_media(ir:dict,run_root:Path,out:Path)->None:
    tracks=[t for t in ir['tracks'] if t['role']!='spatial_evidence']
    sources=[_safe_run(run_root,t['run_id'])/'candidate.mp4' for t in tracks]
    fps=ir['canvas']['fps'];frames=ir['canvas']['frames']
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y']
    for p in sources:
        cmd+=['-i',str(p)]
    parts=[];base='[0:v]'
    for idx,t in enumerate(tracks[1:],1):
        p=t['placement']
        parts.append(f'[{idx}:v]scale={p["width"]}:{p["height"]}:flags=bicubic,setsar=1[ov{idx}]')
        last=f'[v{idx}]'
        parts.append(f'{base}[ov{idx}]overlay=x={p["x"]}:y={p["y"]}:shortest=1:format=yuv420{last}')
        base=last
    cmd+=['-filter_complex',';'.join(parts),'-map',base,'-an','-r',str(fps),
          '-frames:v',str(frames),'-c:v','libx264','-pix_fmt','yuv420p',
          '-movflags','+faststart',str(out)]
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise SceneIRError('FFmpeg/FFprobe missing')
    try:
        process=subprocess.run(cmd,capture_output=True,timeout=180,check=False)
    except subprocess.TimeoutExpired as exc:
        raise SceneIRError('composition exceeded execution budget') from exc
    if process.returncode:
        raise SceneIRError('bounded composition command failed (see local FFmpeg diagnostics)')
    if not out.is_file() or not 0<out.stat().st_size<=MAX_OUTPUT:
        raise SceneIRError('composition MP4 output missing or oversized')
    hub._ffprobe(out,frames=frames,fps=fps,width=ir['canvas']['width'],height=ir['canvas']['height'])


def compose(ir:dict,input_root:Path,run_root:Path,output_root:Path)->dict:
    raw,deps=replay(ir,input_root,run_root)
    if output_root.is_symlink():
        raise SceneIRError('output root cannot be a symlink')
    output_root.mkdir(parents=True,exist_ok=True)
    candidate=output_root/ir['candidate_id']
    if candidate.exists() or candidate.is_symlink():
        raise SceneIRError('append-only composition cannot overwrite a candidate')
    staging=Path(tempfile.mkdtemp(prefix='.staging-scene-ir-',dir=output_root))
    try:
        (staging/'scene-ir.json').write_bytes(hub.canonical(ir))
        (staging/'source.md').write_bytes(raw)
        (staging/'dependencies.json').write_bytes(hub.canonical({'schema':'evedirector.scene_ir_dependencies.v1','items':deps}))
        _compose_media(ir,run_root,staging/'candidate.mp4')
        receipt={'schema':RECEIPT_SCHEMA,'candidate_id':ir['candidate_id'],
                 'scene_ir_sha256':sha(hub.canonical(ir)),'source_sha256':sha(raw),
                 'dependencies_sha256':sha((staging/'dependencies.json').read_bytes()),
                 'mp4_sha256':sha((staging/'candidate.mp4').read_bytes()),
                 'canvas':ir['canvas'],'candidate_only':True,'review_required':True,
                 'canonical_write':False,'human_approved':False,'published':False,
                 'ordr_spatial_visualization':False,
                 'scope':'source-and-R9-dependency-replay; combined fixed-operator video; no EVOE authenticity, 3D visualization or human approval'}
        (staging/'compose-receipt.json').write_bytes(hub.canonical(receipt))
        if candidate.exists() or candidate.is_symlink():
            raise SceneIRError('candidate appeared during staging')
        staging.rename(candidate)
        return receipt
    finally:
        if staging.exists():shutil.rmtree(staging)


def verify(output:Path,input_root:Path,run_root:Path)->dict:
    if output.is_symlink() or not output.is_dir():
        raise SceneIRError('composition directory unavailable or linked')
    ir=hub.json_read(output/'scene-ir.json',MAX_DRAFT)
    receipt=hub.json_read(output/'compose-receipt.json',MAX_DRAFT)
    exact(receipt,{'schema','candidate_id','scene_ir_sha256','source_sha256','dependencies_sha256',
         'mp4_sha256','canvas','candidate_only','review_required','canonical_write','human_approved',
         'published','ordr_spatial_visualization','scope'})
    if (receipt['schema']!=RECEIPT_SCHEMA or ir['candidate_id']!=output.name or
            receipt['candidate_id']!=ir['candidate_id'] or
            receipt['candidate_only'] is not True or receipt['review_required'] is not True or
            receipt['canonical_write'] is not False or receipt['published'] is not False or
            receipt['human_approved'] is not False or receipt['ordr_spatial_visualization'] is not False):
        raise SceneIRError('invalid composition authority receipt')
    raw,deps=replay(ir,input_root,run_root)
    if ((output/'source.md').is_symlink() or (output/'dependencies.json').is_symlink() or
          (output/'candidate.mp4').is_symlink()):
        raise SceneIRError('symlinked composition artifact')
    if (output/'source.md').read_bytes()!=raw:
        raise SceneIRError('staged source Markdown has changed')
    deps_raw=hub.canonical({'schema':'evedirector.scene_ir_dependencies.v1','items':deps})
    if (output/'dependencies.json').read_bytes()!=deps_raw:
        raise SceneIRError('dependency evidence no longer matches R9 runs')
    video=output/'candidate.mp4'
    if not video.is_file() or video.stat().st_size>MAX_OUTPUT:
        raise SceneIRError('candidate video missing or oversized')
    checks={
        'scene_ir_sha256':sha(hub.canonical(ir)),'source_sha256':sha(raw),
        'dependencies_sha256':sha(deps_raw),'mp4_sha256':sha(video.read_bytes()),
        'canvas':ir['canvas'],
    }
    if any(receipt[k]!=v for k,v in checks.items()):
        raise SceneIRError('composition receipt drifted')
    c=ir['canvas']
    hub._ffprobe(video,frames=c['frames'],fps=c['fps'],width=c['width'],height=c['height'])
    return {'schema':'evedirector.scene_ir_verification.v1','status':'PASS_BOUNDED_REPLAY',
            'candidate_id':output.name,'dependencies':len(deps),'composition_sha256':receipt['mp4_sha256'],
            'scene_ir_sha256':receipt['scene_ir_sha256'],
            'ordr_spatial_visualization':False,'human_approved':False,
            'scope':'pinned sources, plugin receipts, output MP4 and timebase; no independent pixel equivalence proof'}


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description='EveDirector R10 bounded plugin-to-scene IR compositor')
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('lock','compose','verify'):
        s=sub.add_parser(name)
        s.add_argument('--input-root',required=True,type=Path)
        s.add_argument('--runs-root',required=True,type=Path)
        if name=='lock':
            s.add_argument('--draft',required=True,type=Path)
            s.add_argument('--out',required=True,type=Path)
        elif name=='compose':
            s.add_argument('--ir',required=True,type=Path)
            s.add_argument('--output-root',required=True,type=Path)
        else:
            s.add_argument('--candidate-dir',required=True,type=Path)
    args=p.parse_args(argv)
    try:
        if args.action=='lock':
            ir=lock(hub.json_read(args.draft,MAX_DRAFT),args.input_root,args.runs_root)
            if args.out.exists() or args.out.is_symlink():raise SceneIRError('locked IR cannot overwrite existing file')
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_bytes(hub.canonical(ir))
            result={'status':'LOCKED','scene_ir_sha256':sha(hub.canonical(ir)),
                    'path':str(args.out),'human_approved':False}
        elif args.action=='compose':
            result=compose(hub.json_read(args.ir,MAX_DRAFT),args.input_root,args.runs_root,args.output_root)
        else:
            result=verify(args.candidate_dir,args.input_root,args.runs_root)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
        return 0
    except (SceneIRError,hub.PluginError,OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
        print('R10_REJECTED: '+str(exc),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
