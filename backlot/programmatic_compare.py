"""R8 read-only visual comparison API for R7/R6/R2 candidate matrices.

This is not an L3 proposal: no POST, Apply, Reject or publish authority.
"""
from __future__ import annotations

import asyncio
from itertools import islice
from pathlib import Path
import sys
from typing import Any

from fastapi import APIRouter, HTTPException

from backlot import agent_review as l4
from backlot import programmatic_review as r2_api
from lib.paths import REPO_ROOT

SCRIPTS_DIR = REPO_ROOT / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import evedirector_compare_matrix_r8 as r8  # noqa: E402
import evedirector_platform_layout_r7 as r7  # noqa: E402
import evedirector_review_stage as stage  # noqa: E402
import evedirector_subtitle_layout_r6 as r6  # noqa: E402

router = APIRouter()


def _project(project_id: str) -> Path:
    l4._safe_project_dir(project_id)
    try:
        return stage._ensure_project(l4.PROJECTS_DIR, project_id)
    except stage.ReviewPackageError as exc:
        raise HTTPException(status_code=403, detail='unsafe matrix project path') from exc


def _loaded(project_id: str, matrix_id: str) -> dict:
    _project(project_id)
    try:
        return r8.load(l4.PROJECTS_DIR, project_id, matrix_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='matrix is not staged') from exc
    except (r8.MatrixReviewError, r7.PlatformLayoutError, r6.SubtitleLayoutError,
            stage.ReviewPackageError, stage.bridge.r0.ProgramError,
            OSError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail='R8 matrix failed source/variant replay') from exc


def _index(project_id: str) -> dict[str, Any]:
    project = _project(project_id)
    root = project / r8.DIR_NAME
    if not root.exists():
        return {'project_id': project_id, 'matrices': [], 'authority': 'read_only', 'apply_supported': False}
    try:
        stage._require_plain_dir(root, project)
    except stage.ReviewPackageError as exc:
        raise HTTPException(status_code=403, detail='unsafe comparison root') from exc
    matrices = []
    for folder in sorted(islice(root.iterdir(), 128), key=lambda p:p.name):
        if len(matrices) >= 32:
            break
        if folder.name.startswith('.') or not stage.ID.fullmatch(folder.name):
            continue
        if not folder.is_dir() and not folder.is_symlink():
            continue
        try:
            checked = r8.load(l4.PROJECTS_DIR, project_id, folder.name)
            pins = checked['manifest']['variant_pins']
            matrices.append({'matrix_id': folder.name, 'status': 'REPLAY_PASS',
                             'profiles': [p['profile'] for p in pins],
                             'variant_count': len(pins), 'candidate_only': True,
                             'apply_supported': False})
        except (FileNotFoundError, r8.MatrixReviewError, r7.PlatformLayoutError,
                r6.SubtitleLayoutError, stage.ReviewPackageError, stage.bridge.r0.ProgramError,
                OSError, KeyError, ValueError, TypeError):
            matrices.append({'matrix_id':folder.name,'status':'INTEGRITY_FAILED',
                             'candidate_only':True,'apply_supported':False})
    return {'project_id': project_id, 'matrices': matrices,
            'authority': 'read_only', 'apply_supported': False}


def _detail(project_id: str, matrix_id: str) -> dict[str, Any]:
    checked = _loaded(project_id, matrix_id)
    pins = checked['manifest']['variant_pins']
    specs = {v['profile']:v for v in checked['r7_matrix']['variants']}
    variants=[]
    for pin in pins:
        cid = pin['candidate_id']
        # Reuses R2/R3/R4/R5/R6's sanitized, independently replayed detail.
        # A damaged visual check or layout proof fails the entire comparison.
        item = r2_api._detail(project_id, cid)
        if (not item['preview']['available'] or
            item['timing']['fps'] != pin['fps'] or
            item['timing']['frames'] != pin['frames'] or
            item['digests']['source_sha256'] != pin['source_sha256'] or
            item['digests']['program_sha256'] != pin['program_sha256'] or
            item['layout_check']['status'] != 'PASS_SAFE_LAYOUT_CONTRACT'):
            raise HTTPException(status_code=409, detail='R8 compared candidate evidence has changed')
        spec = specs[pin['profile']]
        variants.append({
            'profile': pin['profile'], 'provider': spec['provider'],
            'format': spec['format'], 'candidate_id':cid,
            'width': pin['width'], 'height':pin['height'],
            'fps':pin['fps'], 'frames':pin['frames'],
            'safe_area':spec['safe_area'], 'line_count':spec['line_count'],
            'media_url':item['preview']['media_url'],
            'source_anchors':[{'scene_id':s['id'], **s['source']} for s in item['scenes']],
            'checks': {k:item[k]['status'] for k in (
                'visual_check','text_check','multilingual_check','layout_check')},
            'proof':{'source_sha256':pin['source_sha256'],
                     'program_sha256':pin['program_sha256'],
                     'layout_receipt_sha256':pin['layout_receipt_sha256'],
                     'video_sha256':pin['video_sha256']},
        })
    sync = {'mode':'shared_frame_index_preview_seek', 'fps':pins[0]['fps'],
            'frames':pins[0]['frames'], 'seconds':pins[0]['frames']/pins[0]['fps'],
            'exact_frame_decode_attested':False}
    return {
        'schema': 'evedirector.compare_review_api.v0.1',
        'project_id':project_id, 'matrix_id':matrix_id, 'status':'REPLAY_PASS',
        'candidate_only':True,
        'authority':{'mode':'read_only','apply_supported':False,'publish_supported':False,
                     'approved_for_publish':False,'official_platform_safe_area_certified':False,
                     'full_pixel_equivalence_attested':False},
        'sync':sync, 'variants':variants,
        'source_sha256':checked['manifest']['source_sha256'],
        'excluded':['official_platform_UI_guarantees','full_pixel_equivalence',
                    'human_approval','accurate_frame_seek_across_devices'],
    }

@router.get('/api/project/{project_id}/programmatic-compare')
async def compare_index(project_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_index, project_id)

@router.get('/api/project/{project_id}/programmatic-compare/{matrix_id}')
async def compare_detail(project_id: str, matrix_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_detail, project_id, matrix_id)
