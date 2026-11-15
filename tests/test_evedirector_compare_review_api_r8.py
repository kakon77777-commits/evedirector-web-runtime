"""R8 Backlot/ L4 / L6 navigation and read-only API integration tests."""
from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_evedirector_compare_matrix_r8 import staged, template, P, MID
import backlot.agent_review as l4
import backlot.server as server
import backlot.programmatic_compare as r8_api
import evedirector_review_stage as stage


@pytest.fixture
def client(staged,monkeypatch):
    monkeypatch.setattr(l4,'PROJECTS_DIR',staged)
    monkeypatch.setattr(server,'PROJECTS_DIR',staged)
    app=server.create_app()
    with TestClient(app) as client:
        yield client


def _root():return '/api/project/'+P+'/programmatic-compare'


def test_actual_server_routes_and_l4_entry(client):
    app=client.app
    paths={r.path for r in app.routes if hasattr(r,'path')}
    assert '/api/project/{project_id}/programmatic-compare' in paths
    assert '/api/project/{project_id}/programmatic-compare/{matrix_id}' in paths
    assert '/p/{project_id}/programmatic-compare' in paths
    assert not any('/programmatic-compare/' in x and x.endswith(('/apply','/publish','/reject','/validate')) for x in paths)
    page=client.get('/p/'+P+'/programmatic-compare')
    assert page.status_code==200 and 'programmatic-compare.js' in page.text
    js=client.get('/ui/programmatic-compare.js')
    assert js.status_code==200 and 'source_anchors' in js.text
    l4_page=client.get('/p/'+P+'/agent-review')
    assert l4_page.status_code==200
    js=client.get('/ui/agent-review.js')
    assert 'programmatic-compare' in js.text


def test_sanitized_side_by_side_data_and_sync(client):
    listing=client.get(_root())
    assert listing.status_code==200
    index=listing.json()
    assert index['authority']=='read_only' and index['apply_supported'] is False
    assert index['matrices'][0]['status']=='REPLAY_PASS'
    r=client.get(_root()+'/'+MID)
    assert r.status_code==200,r.text
    d=r.json()
    assert d['status']=='REPLAY_PASS'
    assert d['sync']['fps']==12 and d['sync']['frames']==60
    assert d['sync']['exact_frame_decode_attested'] is False
    assert len(d['variants'])==3
    assert d['authority']['apply_supported'] is False
    assert d['authority']['publish_supported'] is False
    assert d['authority']['official_platform_safe_area_certified'] is False
    assert d['authority']['full_pixel_equivalence_attested'] is False
    for v in d['variants']:
        assert v['media_url'].startswith('/api/project/'+P+'/programmatic-review/')
        assert v['checks']['layout_check']=='PASS_SAFE_LAYOUT_CONTRACT'
        assert v['checks']['visual_check']=='NOT_RUN'
        assert v['width']>0 and v['height']>0
        assert len(v['proof']['video_sha256'])==64
        assert len(v['source_anchors'])==2
        assert 'private_debug' not in json.dumps(v)
        media=client.get(v['media_url'])
        assert media.status_code==200 and media.headers['content-type'].startswith('video/mp4')
    assert 'request.json' not in d
    assert 'base.json' not in d


def test_no_writes_even_when_l3_actions_enabled(client,monkeypatch,staged):
    monkeypatch.setenv(l4.ACTIONS_ENV,'1')
    spec=staged/P/'video_spec.yaml'
    spec.write_text('protected: true\n',encoding='utf-8')
    initial=spec.read_bytes()
    paths=[_root(),_root()+'/'+MID,
           _root()+'/'+MID+'/apply',_root()+'/'+MID+'/publish']
    for path in paths:
        r=client.post(path,json={'reviewer':'forged','confirmation':'APPLY '+MID})
        assert r.status_code in (404,405), (path,r.status_code)
    assert spec.read_bytes()==initial


def test_corrupt_matrix_and_preview_fail_closed(client,staged):
    manifest=staged/P/'programmatic_compare_matrices'/MID/'manifest.json'
    manifest.write_bytes(manifest.read_bytes()+b' forged')
    detail=client.get(_root()+'/'+MID)
    assert detail.status_code==409
    listing=client.get(_root())
    assert listing.status_code==200
    assert listing.json()['matrices'][0]['status']=='INTEGRITY_FAILED'


def test_unlinked_project_has_no_matrix(client,staged):
    (staged/'different-project').mkdir()
    r=client.get('/api/project/different-project/programmatic-compare')
    assert r.status_code==200 and r.json()['matrices']==[]
    r=client.get('/api/project/different-project/programmatic-compare/'+MID)
    assert r.status_code in (404,409)


def test_invalid_candidates_do_not_surface_paths(client,staged,tmp_path):
    victim=tmp_path/'do-not-expose.md';victim.write_text('PRIVATE_TOKEN',encoding='utf-8')
    original=staged/P/stage.PACKAGE_DIR/'r7_tiktok_vertical_v1'/'source.md'
    original.unlink()
    try: original.symlink_to(victim)
    except OSError: pytest.skip('symlink unsupported')
    r=client.get(_root()+'/'+MID)
    assert r.status_code==409
    assert 'PRIVATE_TOKEN' not in r.text and str(victim) not in r.text
