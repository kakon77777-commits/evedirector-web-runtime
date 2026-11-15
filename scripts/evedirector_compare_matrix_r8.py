#!/usr/bin/env python3
"""R8 isolated R7→R2 multi-platform review matrix. Offline, append-only, read-only.

Proof scope: cross-variant source + program + layout receipt + preview-byte binding.
No UI safe-zone certification, full-pixel equivalence, approval or publish action.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_platform_layout_r7 as r7
import evedirector_review_stage as stage
import evedirector_subtitle_layout_r6 as r6

SCHEMA = 'evedirector.compare_matrix.v0.1'
LINKS_SCHEMA = 'evedirector.compare_links.v0.1'
DIR_NAME = 'programmatic_compare_matrices'
FILE_LIMIT = 2_000_000
EXACT_FILES = {'manifest.json', 'base.json', 'request.json', 'links.json', 'source.md', 'matrix.json', 'styles'}

class MatrixReviewError(ValueError):
    pass


def _hash(value: bytes) -> str:
    return sha256(value).hexdigest()


def _keys(obj: Any, keys: set[str], desc: str) -> None:
    if type(obj) is not dict or set(obj) != keys:
        raise MatrixReviewError(desc + ' has unknown/missing keys')


def _load_links(payload: dict, report: dict) -> list[dict]:
    _keys(payload, {'schema', 'links'}, 'R8 links')
    if payload['schema'] != LINKS_SCHEMA:
        raise MatrixReviewError('unsupported links schema')
    links = payload['links']
    if not isinstance(links, list) or not 2 <= len(links) <= 6:
        raise MatrixReviewError('R8 requires 2–6 distinct rendered candidates')
    names = [x.get('profile') if type(x) is dict else None for x in links]
    ids = [x.get('candidate_id') if type(x) is dict else None for x in links]
    allowed = {x['profile'] for x in report['variants']}
    if names != sorted(set(names), key=str) or set(names) - allowed:
        raise MatrixReviewError('profiles must be R7-generated, sorted and unique')
    if any(type(x) is not dict or set(x) != {'profile', 'candidate_id'} for x in links):
        raise MatrixReviewError('R8 link object shape is not allowed')
    if any(not isinstance(n, str) or not stage.ID.fullmatch(n) for n in ids) or len(set(ids)) != len(ids):
        raise MatrixReviewError('candidate IDs must be safe and unique')
    return links


def _pinned_variants(projects_dir: Path, project_id: str, results: list[dict], links: list[dict], source: bytes) -> list[dict]:
    by_profile = {x['profile']: x for x in results}
    pinned = []
    for entry in links:
        profile, cid = entry['profile'], entry['candidate_id']
        variant = by_profile[profile]
        item = stage.load_package(projects_dir, project_id, cid)
        bundle = item['props']['bundle']
        report = r6.load_report(projects_dir, project_id, cid, item)
        if report is None or report['status'] != 'PASS_SAFE_LAYOUT_CONTRACT':
            raise MatrixReviewError('R6 staged layout evidence is missing or not PASS')
        if stage.canonical(report) != stage.canonical(variant['receipt']):
            raise MatrixReviewError('R7/R6 replayed receipt mismatch')
        if (stage.canonical(stage.bridge.read_strict_json(
                stage._file_under(projects_dir / project_id / stage.PACKAGE_DIR / cid,
                                  'plan.json', stage.bridge.MAX_PLAN_BYTES)))
                != stage.canonical(variant['plan'])):
            raise MatrixReviewError('R7 candidate scene program was changed')
        if (bundle['program_sha256'] != _hash(stage.canonical(variant['plan'])) or
            bundle['source_sha256'] != _hash(source) or
            bundle['fps'] != variant['plan']['fps'] or
            bundle['durationInFrames'] != variant['plan']['frames'] or
            bundle['width'] != variant['plan']['width'] or
            bundle['height'] != variant['plan']['height']):
            raise MatrixReviewError('R7 candidate metadata mismatch')
        video = item['manifest']['video']
        if video is None or item['video_path'] is None:
            raise MatrixReviewError('R8 comparison requires a staged video for every variant')
        pinned.append({
            'profile': profile, 'candidate_id': cid,
            'program_sha256': bundle['program_sha256'],
            'layout_receipt_sha256': _hash(stage.canonical(report)),
            'video_sha256': video['sha256'],
            'source_sha256': bundle['source_sha256'],
            'width': bundle['width'], 'height': bundle['height'],
            'fps': bundle['fps'], 'frames': bundle['durationInFrames'],
        })
    scene_fps = {x['fps'] for x in pinned}
    scene_frames = {x['frames'] for x in pinned}
    if len(scene_fps) != 1 or len(scene_frames) != 1:
        raise MatrixReviewError('timeline cannot be synchronized across variants')
    return pinned


def _build_manifest(projects_dir: Path, project_id: str,
                    matrix_id: str, base: dict, source: bytes,
                    request: dict, links_data: dict, styles_dir: Path) -> tuple[dict, dict]:
    stage.checked_id(matrix_id)
    matrix, results = r7.compile_matrix(base, source, styles_dir, request)
    links = _load_links(links_data, matrix)
    pins = _pinned_variants(projects_dir, project_id, results, links, source)
    manifest = {
        'schema': SCHEMA, 'matrix_id': matrix_id,
        'candidate_only': True, 'review_required': True,
        'approved_for_publish': False, 'official_platform_safe_area_certified': False,
        'source_sha256': _hash(source),
        'base_sha256': _hash(stage.canonical(base)),
        'request_sha256': _hash(stage.canonical(request)),
        'links_sha256': _hash(stage.canonical(links_data)),
        'r7_matrix_sha256': _hash(stage.canonical(matrix)),
        'variant_pins': pins,
        'scope': 'candidate-byte-source-program-layout-and-video-binding',
    }
    return manifest, matrix


def _safe_styles(folder: Path, base: dict) -> Path:
    name = base.get('style')
    if not isinstance(name, str) or not stage.ID.fullmatch(name):
        raise MatrixReviewError('unsafe style name')
    styles = folder / 'styles'
    stage._require_plain_dir(styles, folder)
    stage._file_under(styles, f'{name}.yaml', 512_000)
    return styles


def _read_files(folder: Path, matrix_id: str) -> dict:
    stage._require_plain_dir(folder)
    if {x.name for x in folder.iterdir()} != EXACT_FILES:
        raise MatrixReviewError('missing/extra staged matrix files')
    data = {key: stage.bridge.read_strict_json(stage._file_under(folder, key+'.json', FILE_LIMIT), FILE_LIMIT)
            for key in ('manifest', 'base', 'request', 'links', 'matrix')}
    data['source'] = stage.bridge.read_source(stage._file_under(folder, 'source.md', stage.bridge.MAX_SOURCE_BYTES))
    data['styles_dir'] = _safe_styles(folder, data['base'])
    return data


def load(projects_dir: Path, project_id: str, matrix_id: str) -> dict:
    stage.checked_id(matrix_id)
    project = stage._ensure_project(projects_dir, project_id)
    root = project / DIR_NAME
    stage._require_plain_dir(root, project)
    folder = root / matrix_id
    stage._require_plain_dir(folder, root)
    data = _read_files(folder, matrix_id)
    manifest, matrix = _build_manifest(projects_dir, project_id, matrix_id,
                                       data['base'], data['source'], data['request'],
                                       data['links'], data['styles_dir'])
    if stage.canonical(manifest) != stage.canonical(data['manifest']) or stage.canonical(matrix) != stage.canonical(data['matrix']):
        raise MatrixReviewError('R8 compare manifest/R7 matrix replay mismatch')
    return {'manifest': manifest, 'r7_matrix': matrix, 'links': data['links']['links']}


def store(projects_dir: Path, project_id: str, matrix_id: str,
          base_path: Path, source_path: Path, request_path: Path,
          links_path: Path, styles_dir: Path) -> dict:
    stage.checked_id(matrix_id)
    project = stage._ensure_project(projects_dir, project_id)
    root = project / DIR_NAME
    root.mkdir(exist_ok=True)
    stage._require_plain_dir(root, project)
    target = root / matrix_id
    if target.exists() or target.is_symlink():
        raise MatrixReviewError('R8 matrix is append-only; already exists')
    base = stage.bridge.read_strict_json(base_path)
    source = stage.bridge.read_source(source_path)
    request = stage.bridge.read_strict_json(request_path, 128_000)
    links_data = stage.bridge.read_strict_json(links_path, 128_000)
    style_name = base.get('style')
    if not isinstance(style_name, str) or not stage.ID.fullmatch(style_name):
        raise MatrixReviewError('unsafe style')
    style_raw = stage._file_under(styles_dir, style_name+'.yaml', 512_000).read_bytes()
    manifest, matrix = _build_manifest(projects_dir, project_id, matrix_id, base, source, request, links_data, styles_dir)
    temp = Path(tempfile.mkdtemp(prefix='.r8-stage-', dir=root))
    try:
        (temp / 'styles').mkdir()
        files = {'base.json': stage.canonical(base), 'source.md': source,
                 'request.json': stage.canonical(request), 'links.json': stage.canonical(links_data),
                 'matrix.json': stage.canonical(matrix), 'manifest.json': stage.canonical(manifest),
                 'styles/'+style_name+'.yaml': style_raw}
        for name, raw in files.items():
            (temp / name).write_bytes(raw)
        # Recompute all proofs from a temporary bundle before atomic publish.
        data = _read_files(temp, matrix_id)
        fresh, fresh_matrix = _build_manifest(projects_dir, project_id, matrix_id,
                                data['base'], data['source'], data['request'], data['links'], data['styles_dir'])
        if stage.canonical(fresh) != stage.canonical(manifest) or stage.canonical(fresh_matrix) != stage.canonical(matrix):
            raise MatrixReviewError('matrix changed during staging')
        if target.exists() or target.is_symlink():
            raise MatrixReviewError('concurrent staged matrix already exists')
        temp.rename(target)
    finally:
        if temp.exists(): shutil.rmtree(temp)
    return manifest


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description='R8 read-only multi-platform compare package')
    p.add_argument('action',choices=('stage','verify'))
    p.add_argument('--projects-dir',type=Path,default=Path(__file__).resolve().parents[1]/'projects')
    p.add_argument('--project-id',required=True)
    p.add_argument('--matrix-id',required=True)
    p.add_argument('--base',type=Path)
    p.add_argument('--source',type=Path)
    p.add_argument('--request',type=Path)
    p.add_argument('--links',type=Path)
    p.add_argument('--styles-dir',type=Path,default=Path(__file__).resolve().parents[1]/'styles')
    args=p.parse_args(argv)
    try:
        if args.action=='stage':
            if not all((args.base,args.source,args.request,args.links)):
                raise MatrixReviewError('stage needs --base --source --request --links')
            result=store(args.projects_dir,args.project_id,args.matrix_id,args.base,args.source,
                         args.request,args.links,args.styles_dir)
        else:
            result=load(args.projects_dir,args.project_id,args.matrix_id)['manifest']
        print(json.dumps({'status':'R8_REPLAY_PASS','matrix_id':args.matrix_id,
                          'candidate_only':True,'variants':len(result['variant_pins'])},ensure_ascii=False))
        return 0
    except (MatrixReviewError,r7.PlatformLayoutError,r6.SubtitleLayoutError,
            stage.ReviewPackageError,stage.bridge.r0.ProgramError,
            OSError,KeyError,TypeError,ValueError) as exc:
        print(f'R8_{args.action.upper()}_FAIL: {exc}', file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
