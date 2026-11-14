"""R5 L4 projection separates missing/failed font evidence from approval."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import evedirector_review_stage as stage
import evedirector_multilang_probe_r5 as r5
import backlot.agent_review as l4
import backlot.programmatic_review as api
import backlot.server as server


@pytest.fixture
def env(tmp_path,monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg unavailable')
    projects=tmp_path/'projects'
    (projects/'multilang').mkdir(parents=True)
    monkeypatch.setattr(l4,'PROJECTS_DIR',projects)
    monkeypatch.setattr(server,'PROJECTS_DIR',projects)
    video=tmp_path/'black.mp4'
    subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-f','lavfi',
                    '-i','color=c=black:s=640x360:r=12','-frames:v','60',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True,timeout=40)
    stage.stage(projects,'multilang','black',ROOT/'examples/native-video/r5-multilingual.json',
                ROOT/'examples/native-video/source/r5-multilingual.md',ROOT/'styles',video)
    app=FastAPI();app.include_router(api.router)
    return {'projects':projects,'client':TestClient(app)}


def test_not_run_stays_not_run(env):
    response=env['client'].get('/api/project/multilang/programmatic-review/black')
    assert response.status_code==200
    assert response.json()['multilingual_check']=={
        'status':'NOT_RUN', 'unsigned_local_record':True,
        'visual_equivalence_attested':False,'approved_for_publish':False,
    }


def test_failed_cjk_visible_with_font_receipt(env):
    item=stage.load_package(env['projects'],'multilang','black')
    try:
        result=r5.inspect(item,'black')
    except r5.MultilangProbeError:
        pytest.skip('Noto CJK font unavailable')
    assert result['status']=='FAIL_SAMPLED_MULTILINGUAL_TEXT'
    r5.store(env['projects'],'multilang','black',result)
    response=env['client'].get('/api/project/multilang/programmatic-review/black')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['multilingual_check']['status']=='FAIL_SAMPLED_MULTILINGUAL_TEXT'
    assert data['multilingual_check']['font']['font_file_embedded'] is False
    assert data['multilingual_check']['failed_samples']>0
    assert data['multilingual_check']['approved_for_publish'] is False
    assert data['authority']['apply_supported'] is False


def test_tampered_report_is_rejected_even_if_rehashed(env):
    item=stage.load_package(env['projects'],'multilang','black')
    try:
        report=r5.inspect(item,'black')
    except r5.MultilangProbeError:
        pytest.skip('Noto CJK font unavailable')
    path=r5.store(env['projects'],'multilang','black',report)
    path.write_bytes(path.read_bytes()+b'changed')
    response=env['client'].get('/api/project/multilang/programmatic-review/black')
    assert response.status_code==409
    assert 'R5 multilingual' in response.json()['detail']


def test_no_new_apply_even_if_L3_enabled(env,monkeypatch):
    monkeypatch.setenv(l4.ACTIONS_ENV,'1')
    route='/api/project/multilang/programmatic-review/black'
    assert env['client'].post(route+'/apply',json={'confirmation':'APPLY black'}).status_code==404
    paths={r.path for r in server.create_app().routes if hasattr(r,'path')}
    assert '/api/project/{project_id}/programmatic-review/{candidate_id}' in paths
    assert '/api/project/{project_id}/programmatic-review/{candidate_id}/apply' not in paths
