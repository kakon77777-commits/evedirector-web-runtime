#!/usr/bin/env python3
"""R6 deterministic, source-grounded CJK subtitle layout compiler + L4 replay.

Compile a bounded auto-wrapping request into *existing* R5 explicit text layers.
No browser automatic wrapping, arbitrary font files/URLs, Apply, or publication.
A PASS certifies a pinned font metric/safe-area contract, not rendered pixels.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any

from PIL import ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_programmatic as r0
import evedirector_review_stage as stage
import evedirector_multilang_probe_r5 as r5

SCHEMA = 'evedirector.subtitle_layout_request.v0.1'
REPORT_SCHEMA = 'evedirector.subtitle_layout_report.v0.1'
RECORD_DIR = 'programmatic_layout_checks'
MAX_REQUEST_BYTES = 128_000
MAX_REPORT_BYTES = 256_000
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*| +|.", re.DOTALL)
INVALID_LINE_START = set('，。！？、；：,.!?;:)]}」』')
INVALID_LINE_END = set('([{「『')
ALLOWED_CJK_MARKS = set('，。！？、；：「」『』（）·')


class SubtitleLayoutError(ValueError):
    pass


def _check_keys(data: Any, required: set[str], label: str) -> None:
    if not isinstance(data, dict) or set(data) != required:
        raise SubtitleLayoutError(f'{label}: unknown or missing keys')


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data: Any) -> bytes:
    return stage.canonical(data)


def _check_text(text: Any) -> str:
    if not isinstance(text, str) or not 8 <= len(text) <= 240 or text != text.strip():
        raise SubtitleLayoutError('subtitle must be a bounded, nonempty exact source quote')
    if unicodedata.normalize('NFC', text) != text or '  ' in text:
        raise SubtitleLayoutError('subtitle must be NFC and use single ASCII spaces')
    for ch in text:
        cp = ord(ch)
        if not ((ch == ' ') or ('!' <= ch <= '~') or
                (0x3400 <= cp <= 0x4DBF) or (0x4E00 <= cp <= 0x9FFF) or
                (ch in ALLOWED_CJK_MARKS)):
            raise SubtitleLayoutError('unsupported subtitle character/format')
    return text


def _face(env: dict[str, Any], size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(env['file'], size, index=env['face_index'])
    except (OSError, ValueError) as exc:
        raise SubtitleLayoutError('font cannot be loaded') from exc


def _split_lines(text: str, face: ImageFont.FreeTypeFont, usable: float) -> list[str]:
    tokens = TOKEN_RE.findall(text)
    if ''.join(tokens) != text:
        raise SubtitleLayoutError('unrecognized subtitle tokens')
    def fits(line: str) -> bool:
        return (0 < len(line) <= 28 and line == line.strip() and
                line[0] not in INVALID_LINE_START and line[-1] not in INVALID_LINE_END and
                face.getlength(line) <= usable)
    if fits(text):
        return [text]
    choices: list[tuple[float, int, list[str]]] = []
    for i in range(1, len(tokens)):
        left = ''.join(tokens[:i]).rstrip(' ')
        right = ''.join(tokens[i:]).lstrip(' ')
        if not (fits(left) and fits(right)):
            continue
        widths = face.getlength(left), face.getlength(right)
        # Favor balanced two-line blocks without cutting English words.
        boundary_preferred = (tokens[i-1].isspace() or tokens[i].isspace() or tokens[i-1][-1] in '，。！？、；：,.!?;:')
        imbalance = abs(widths[0]-widths[1]) + 3 * abs(len(left)-len(right))
        choices.append((imbalance + (0 if boundary_preferred else 400), 0 if boundary_preferred else 1, [left, right]))
    if not choices:
        raise SubtitleLayoutError('subtitle cannot fit within two 28-character safe lines')
    return min(choices, key=lambda pair: (pair[0], pair[1], pair[2]))[2]


def compile_layout(base: dict[str, Any], source: bytes, styles_dir: Path,
                   request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (R5-compatible scene program, reproducible non-approval receipt)."""
    _check_keys(request, {'schema', 'font', 'safe_area', 'cues'}, 'layout request')
    if request['schema'] != SCHEMA:
        raise SubtitleLayoutError('unsupported layout request schema')
    _check_keys(request['font'], {'profile', 'sha256', 'face_index'}, 'font contract')
    pin = request['font']
    if (pin['profile'] != 'noto-cjk-tc-v1' or
            not isinstance(pin['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', pin['sha256']) or
            type(pin['face_index']) is not int or not 0 <= pin['face_index'] <= 31):
        raise SubtitleLayoutError('invalid pinned font contract')
    try:
        env = r5.font_environment()
    except r5.MultilangProbeError as exc:
        raise SubtitleLayoutError('pinned font unavailable; no fallback allowed') from exc
    if pin['sha256'] != env['font_sha256'] or pin['face_index'] != env['face_index']:
        raise SubtitleLayoutError('pinned font SHA/index differs from current platform')
    _check_keys(request['safe_area'], {'left','right','top','bottom'}, 'safe area')
    margins = request['safe_area']
    if any(type(x) is not int or not 16 <= x <= 220 for x in margins.values()):
        raise SubtitleLayoutError('safe margins must be 16..220 integer pixels')
    width, height = base.get('width'), base.get('height')
    if type(width) is not int or type(height) is not int:
        raise SubtitleLayoutError('invalid base resolution')
    left,right,top,bottom=(margins[k] for k in ('left','right','top','bottom'))
    safe_width, safe_height = width-left-right, height-top-bottom
    if safe_width < 160 or safe_height < 96:
        raise SubtitleLayoutError('safe zone has inadequate dimensions')
    if not isinstance(request['cues'], list) or not 1 <= len(request['cues']) <= 24:
        raise SubtitleLayoutError('expected 1..24 cues')
    # All base layers and source anchors must already pass the R0/R5 contract.
    r0.validate(base,source,styles_dir)
    lines = source.decode('utf-8').splitlines()
    result = copy.deepcopy(base)
    scene_map = {s['id']: s for s in result['scenes']}
    seen = set()
    measures: list[dict[str, Any]] = []
    coverage = r5.supported_characters()
    for cue in request['cues']:
        _check_keys(cue, {'scene_id','layer_id','text','placement'}, 'cue')
        sid,lid=cue['scene_id'],cue['layer_id']
        if not isinstance(sid,str) or not isinstance(lid,str) or (sid,lid) in seen:
            raise SubtitleLayoutError('duplicate/invalid cue identity')
        seen.add((sid,lid))
        text = _check_text(cue['text'])
        if cue['placement'] not in ('middle','lower_third'):
            raise SubtitleLayoutError('placement must be middle/lower_third')
        if any(ord(ch) not in coverage for ch in text if ch != ' '):
            raise SubtitleLayoutError('pinned face lacks subtitle glyph coverage')
        if sid not in scene_map:
            raise SubtitleLayoutError('cue refers to unknown scene')
        scene=scene_map[sid]
        matching = next((line for line in lines if scene['source_contains'] in line), '')
        if text not in matching:
            raise SubtitleLayoutError('cue text not contained in its exact scene source anchor')
        index=next((i for i,lay in enumerate(scene['layers']) if lay['id']==lid), None)
        if index is None:
            raise SubtitleLayoutError('cue target layer missing')
        layer=scene['layers'][index]
        if (layer['kind']!='text' or layer.get('font_profile')!='noto-cjk-tc-v1' or
                'keyframes' in layer or layer.get('opacity',1)<.9 or
                not 36 <= layer['font_size'] <= 64):
            raise SubtitleLayoutError('cue target must be a static opaque 36..64px CJK text layer')
        face = _face(env,layer['font_size'])
        guard = max(10, round(layer['font_size']*.2))
        splits = _split_lines(text, face, safe_width-2*guard)
        step=round(layer['font_size']*1.2)
        first_y=(top+round((safe_height-len(splits)*step)/2)
                 if cue['placement']=='middle' else height-bottom-len(splits)*step-4)
        if first_y < top:
            raise SubtitleLayoutError('text block would overflow top safe boundary')
        prior_ids={lay['id'] for lay in scene['layers'] if lay['id']!=lid}
        replacements=[]
        for j,row in enumerate(splits):
            new_id=lid+'_r6_'+str(j+1)
            if not r0.ID.fullmatch(new_id) or new_id in prior_ids:
                raise SubtitleLayoutError('generated layer identity conflict/length')
            prior_ids.add(new_id)
            measured_width=face.getlength(row)
            box=face.getbbox(row)
            x=round(left+(safe_width-measured_width)/2)
            y=first_y+j*step
            if (x+box[0]<left+guard or x+max(measured_width,box[2])>width-right-guard or
                    y+box[1]<top or y+box[3]>height-bottom):
                raise SubtitleLayoutError('text glyph bounds overflow protected safe area')
            lay={key:copy.deepcopy(value) for key,value in layer.items() if key not in ('text','x','y')}
            lay.update({'id':new_id,'text':row,'x':x,'y':y})
            replacements.append(lay)
            measures.append({'scene_id':sid,'layer_id':new_id,'line':j,'text':row,
                             'x':x,'y':y,'width_px':round(measured_width,3),
                             'glyph_bbox':list(box),'placement':cue['placement'],
                             'source_line_sha256':_hash(matching.encode('utf-8'))})
        if len(scene['layers'])-1+len(replacements)>48:
            raise SubtitleLayoutError('too many generated layer primitives')
        scene['layers'][index:index+1]=replacements
    receipt=r0.validate(result,source,styles_dir)
    report={'schema':REPORT_SCHEMA,'status':'PASS_SAFE_LAYOUT_CONTRACT',
            'candidate_only':True,'approved_for_publish':False,
            'visual_equivalence_attested':False,
            'source_sha256':receipt['source_sha256'],
            'base_plan_sha256':_hash(_canonical(base)),
            'layout_request_sha256':_hash(_canonical(request)),
            'compiled_program_sha256':receipt['program_sha256'],
            'font':{'profile':pin['profile'],'family':env['family'],
                    'sha256':env['font_sha256'],'face_index':env['face_index'],
                    'bytes':env['font_bytes'],'font_file_embedded':False},
            'safe_area':copy.deepcopy(margins),'line_count':len(measures),
            'lines':measures,
            'scope':'pinned-font-metrics-and-source-grounded-explicit-lines',
            'excluded':['browser-font-face-attestation','pixel-perfect-typography',
                        'complex-shaping','bidi','emoji','cross-platform-pass',
                        'actual-video-pixels','release-approval']}
    return result,report


def _report_dir(projects_dir: Path, project_id: str, candidate_id: str) -> Path:
    stage.checked_id(candidate_id)
    project=stage._ensure_project(projects_dir,project_id)
    return project / RECORD_DIR / candidate_id


def store(projects_dir: Path, project_id: str, candidate_id: str,
          item: dict[str, Any], base_plan: dict, request: dict) -> Path:
    """Append-only untrusted local evidence; API always replays before displaying."""
    root=_report_dir(projects_dir,project_id,candidate_id)
    if root.exists() or root.is_symlink():
        raise SubtitleLayoutError('R6 layout record already exists')
    project=stage._ensure_project(projects_dir,project_id)
    root.parent.mkdir(exist_ok=True)
    stage._require_plain_dir(root.parent,project)
    candidate_root=project/stage.PACKAGE_DIR/candidate_id
    source=stage._file_under(candidate_root,'source.md',stage.bridge.MAX_SOURCE_BYTES).read_bytes()
    generated,receipt=compile_layout(base_plan,source,candidate_root/'styles',request)
    if _canonical(generated)!=_canonical(stage.bridge.read_strict_json(
            stage._file_under(candidate_root,'plan.json',stage.bridge.MAX_PLAN_BYTES))):
        raise SubtitleLayoutError('generated plan differs from staged candidate')
    video_hash=item['manifest']['video']['sha256'] if item['manifest']['video'] else None
    record={'candidate_id':candidate_id,'receipt':receipt,'video_sha256':video_hash}
    files={'base_plan.json':_canonical(base_plan),'layout_request.json':_canonical(request),
           'layout_report.json':_canonical(record)}
    if any(len(v)>MAX_REPORT_BYTES for v in files.values()):
        raise SubtitleLayoutError('R6 layout record too large')
    root.mkdir()
    for name,raw in files.items():
        (root/name).write_bytes(raw)
    return root/'layout_report.json'


def load_report(projects_dir: Path, project_id: str, candidate_id: str,
                item: dict[str, Any]) -> dict[str, Any] | None:
    root=_report_dir(projects_dir,project_id,candidate_id)
    project=stage._ensure_project(projects_dir,project_id)
    if not root.parent.exists():
        return None
    stage._require_plain_dir(root.parent,project)
    if not root.exists():
        return None
    stage._require_plain_dir(root,root.parent)
    if set(p.name for p in root.iterdir())!={'base_plan.json','layout_request.json','layout_report.json'}:
        raise SubtitleLayoutError('R6 record has missing or unexpected files')
    base=stage.bridge.read_strict_json(stage._file_under(root,'base_plan.json',MAX_REPORT_BYTES),MAX_REPORT_BYTES)
    request=stage.bridge.read_strict_json(stage._file_under(root,'layout_request.json',MAX_REPORT_BYTES),MAX_REPORT_BYTES)
    record=stage.bridge.read_strict_json(stage._file_under(root,'layout_report.json',MAX_REPORT_BYTES),MAX_REPORT_BYTES)
    _check_keys(record,{'candidate_id','receipt','video_sha256'},'staged R6 report')
    if record['candidate_id']!=candidate_id:
        raise SubtitleLayoutError('R6 report candidate id mismatch')
    candidate_root=project/stage.PACKAGE_DIR/candidate_id
    source=stage._file_under(candidate_root,'source.md',stage.bridge.MAX_SOURCE_BYTES).read_bytes()
    generated,expected=compile_layout(base,source,candidate_root/'styles',request)
    plan=stage.bridge.read_strict_json(stage._file_under(candidate_root,'plan.json',stage.bridge.MAX_PLAN_BYTES))
    if _canonical(generated)!=_canonical(plan) or _canonical(expected)!=_canonical(record['receipt']):
        raise SubtitleLayoutError('R6 report no longer matches staged source/plan/font')
    video_hash=item['manifest']['video']['sha256'] if item['manifest']['video'] else None
    if record['video_sha256']!=video_hash:
        raise SubtitleLayoutError('R6 report video binding changed')
    return expected


def main(argv: list[str] | None=None) -> int:
    ap=argparse.ArgumentParser(description='R6 bounded CJK subtitle compiler and layout evidence')
    ap.add_argument('action',choices=('compile','verify','stage','replay'))
    ap.add_argument('--base',type=Path)
    ap.add_argument('--layout',type=Path)
    ap.add_argument('--source',type=Path)
    ap.add_argument('--styles-dir',type=Path,default=Path(__file__).resolve().parents[1]/'styles')
    ap.add_argument('--output',type=Path)
    ap.add_argument('--receipt',type=Path)
    ap.add_argument('--projects-dir',type=Path,default=Path(__file__).resolve().parents[1]/'projects')
    ap.add_argument('--project-id')
    ap.add_argument('--candidate-id')
    args=ap.parse_args(argv)
    try:
        if args.action in ('compile','verify'):
            if not all((args.base,args.layout,args.source,args.output,args.receipt)):
                raise SubtitleLayoutError('compile/verify requires --base --layout --source --output --receipt')
            base=stage.bridge.read_strict_json(args.base)
            layout=stage.bridge.read_strict_json(args.layout,MAX_REQUEST_BYTES)
            plan,receipt=compile_layout(base,stage.bridge.read_source(args.source),args.styles_dir,layout)
            if args.action=='compile':
                if args.output.resolve() == args.receipt.resolve():
                    raise SubtitleLayoutError('plan and receipt must use distinct output paths')
                for path in (args.output,args.receipt):
                    if path.exists():
                        raise SubtitleLayoutError('refusing to overwrite existing output')
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.receipt.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_bytes(_canonical(plan))
                args.receipt.write_bytes(_canonical(receipt))
            elif (_canonical(stage.bridge.read_strict_json(args.output))!=_canonical(plan) or
                  _canonical(stage.bridge.read_strict_json(args.receipt))!=_canonical(receipt)):
                raise SubtitleLayoutError('R6 compiled plan or receipt differs on replay')
        else:
            if not args.project_id or not args.candidate_id:
                raise SubtitleLayoutError('stage/replay requires --project-id --candidate-id')
            item=stage.load_package(args.projects_dir,args.project_id,args.candidate_id)
            if args.action=='stage':
                if not args.base or not args.layout:
                    raise SubtitleLayoutError('stage requires --base --layout')
                base=stage.bridge.read_strict_json(args.base)
                layout=stage.bridge.read_strict_json(args.layout,MAX_REQUEST_BYTES)
                store(args.projects_dir,args.project_id,args.candidate_id,item,base,layout)
            else:
                if load_report(args.projects_dir,args.project_id,args.candidate_id,item) is None:
                    raise SubtitleLayoutError('no R6 evidence staged')
        print('R6:',args.action,'PASS (candidate only; NOT publication approval)')
        return 0
    except (SubtitleLayoutError,r0.ProgramError,stage.ReviewPackageError,r5.MultilangProbeError,
            OSError,ValueError,KeyError,TypeError) as exc:
        print('R6 ERROR:',exc,file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
