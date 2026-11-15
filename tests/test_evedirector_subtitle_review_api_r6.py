"""R6 L4 read-only integrity and layout metric isolation tests."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import evedirector_subtitle_layout_r6 as r6
import evedirector_review_stage as stage
import backlot.agent_review as l4
import backlot.server as server


@pytest.fixture
def env(tmp_path,monkeypatch):
    projects=tmp_path/'projects'
    (projects/'review_demo').mkdir(parents=True)
    monkeypatch.setattr(l4,'PROJECTS_DIR',projects)
    monkeypatch.setattr(server,'PROJECTS_DIR',projects)
    base=json.loads((ROOT/'examples/native-video/r6-layout-base.json').read_text(encoding='utf-8'))
    req=json.loads((ROOT/'examples/native-video/r6-layout-request.json').read_text(encoding='utf-8'))
    source=ROOT/'examples/native-video/source/r6-subtitle-layout.md'
    plan,_=r6.compile_layout(base,source.read_bytes(),ROOT/'styles',req)
    plan_file=tmp_path/'compiled.json';plan_file.write_bytes(stage.canonical(plan))
    stage.stage(projects,'review_demo','r6_demo',plan_file,source,ROOT/'styles')
    item=stage.load_package(projects,'review_demo','r6_demo')
    return {'projects':projects,'base':base,'request':req,'item':item,
            'client':TestClient(server.create_app())}


def _url():
    return '/api/project/review_demo/programmatic-review/r6_demo'


def test_old_l4_preview_has_not_run_instead_of_false_pass(env):
    response=env['client'].get(_url())
    assert response.status_code==200,response.text
    value=response.json()
    assert value['layout_check']['status']=='NOT_RUN'
    assert value['layout_check']['approved_for_publish'] is False
    assert value['authority']['apply_supported'] is False


def test_valid_r6_report_is_replayed_and_sanitized(env):
    r6.store(env['projects'],'review_demo','r6_demo',env['item'],env['base'],env['request'])
    d=env['client'].get(_url())
    assert d.status_code==200,d.text
    value=d.json()
    layout=value['layout_check']
    assert layout['status']=='PASS_SAFE_LAYOUT_CONTRACT'
    assert layout['line_count']==4
    assert len(layout['lines'])==4
    assert layout['font']['font_file_embedded'] is False
    assert layout['unsigned_local_record'] is True
    assert layout['visual_equivalence_attested'] is False
    assert layout['approved_for_publish'] is False
    assert value['multilingual_check']['status']=='NOT_RUN'
    assert value['authority']['apply_supported'] is False
    assert 'font_path' not in d.text
    assert 'request.json' not in d.text


def test_forged_report_is_409_not_pass(env):
    p=r6.store(env['projects'],'review_demo','r6_demo',env['item'],env['base'],env['request'])
    v=json.loads(p.read_text(encoding='utf-8'))
    v['receipt']['status']='PASS_FULL_VIDEO'
    p.write_bytes(stage.canonical(v))
    resp=env['client'].get(_url())
    assert resp.status_code==409
    assert 'R6 subtitle layout' in resp.json()['detail']


def test_changed_pinned_font_is_409(env):
    r6.store(env['projects'],'review_demo','r6_demo',env['item'],env['base'],env['request'])
    p=env['projects']/'review_demo'/'programmatic_layout_checks'/'r6_demo'/'layout_request.json'
    v=json.loads(p.read_text(encoding='utf-8'))
    v['font']['sha256']='f'*64
    p.write_bytes(stage.canonical(v))
    assert env['client'].get(_url()).status_code==409


def test_r6_never_gains_apply_even_if_l3_enabled(env,monkeypatch):
    monkeypatch.setenv(l4.ACTIONS_ENV,'1')
    spec=env['projects']/'review_demo'/'video_spec.yaml'
    spec.write_text('canonical: untouched\n',encoding='utf-8')
    r6.store(env['projects'],'review_demo','r6_demo',env['item'],env['base'],env['request'])
    resp=env['client'].post(_url()+'/apply',json={
        'reviewer':'x','confirmation':'APPLY r6_demo'})
    assert resp.status_code==404
    assert spec.read_text(encoding='utf-8')=='canonical: untouched\n'
    assert not [r for r in server.app.routes if getattr(r,'path','').endswith('programmatic-review/{candidate_id}/apply')]
