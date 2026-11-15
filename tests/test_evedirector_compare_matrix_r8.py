"""R8 source R7/R6/R2 coupled comparison and tamper regression.

Generated black MP4s in fixtures are *deliberately not* visual-equivalence proof;
R8 validates byte provenance and timelines, not the frame contents.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import evedirector_compare_matrix_r8 as r8
import evedirector_platform_layout_r7 as r7
import evedirector_review_stage as stage
import evedirector_subtitle_layout_r6 as r6

EX=ROOT/'examples/native-video'
S=ROOT/'styles'
P='r8-test-project'
MID='r8_three_profiles'


def build_seed(projects: Path) -> None:
    project=projects/P
    project.mkdir(parents=True)
    base=stage.bridge.read_strict_json(EX/'r6-layout-base.json')
    src=(EX/'source/r6-subtitle-layout.md').read_bytes()
    req=stage.bridge.read_strict_json(EX/'r7-platform-layout-request.json')
    report,variants=r7.compile_matrix(base,src,S,req)
    assert len(variants)==3
    for variant in variants:
        profile=variant['profile']
        cid='r7_'+profile
        video=project/(profile+'.mp4')
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y',
                        '-f','lavfi','-i',f"color=c=black:s={variant['plan']['width']}x{variant['plan']['height']}:r=12",
                        '-frames:v','60','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(video)],
                       check=True,timeout=40)
        plan_path=project/(profile+'.json')
        plan_path.write_bytes(stage.canonical(variant['plan']))
        stage.stage(projects,P,cid,plan_path,EX/'source/r6-subtitle-layout.md',S,video)
        item=stage.load_package(projects,P,cid)
        r6.store(projects,P,cid,item,variant['base'],variant['layout_request'])
        video.unlink()
        plan_path.unlink()
    result=r8.store(projects,P,MID,EX/'r6-layout-base.json',EX/'source/r6-subtitle-layout.md',
                    EX/'r7-platform-layout-request.json',EX/'r8-compare-links.json',S)
    assert len(result['variant_pins'])==3


@pytest.fixture(scope='module')
def template(tmp_path_factory):
    projects=tmp_path_factory.mktemp('r8base')/'projects'
    projects.mkdir()
    build_seed(projects)
    return projects


@pytest.fixture
def staged(tmp_path,template):
    projects=tmp_path/'projects'
    shutil.copytree(template,projects)
    return projects


def test_r8_staged_replay_and_pins(staged):
    item=r8.load(staged,P,MID)
    pins=item['manifest']['variant_pins']
    assert len(pins)==3
    assert [p['profile'] for p in pins]==['square_social_v1','tiktok_vertical_v1','youtube_landscape_v1']
    assert len({p['video_sha256'] for p in pins})==3
    assert {p['frames'] for p in pins}=={60}
    assert {p['fps'] for p in pins}=={12}
    assert item['manifest']['approved_for_publish'] is False
    assert item['manifest']['official_platform_safe_area_certified'] is False
    assert item['r7_matrix']['visual_equivalence_attested'] is False


def test_r8_append_only_no_overwrite(staged):
    with pytest.raises(r8.MatrixReviewError,match='append-only'):
        r8.store(staged,P,MID,EX/'r6-layout-base.json',EX/'source/r6-subtitle-layout.md',
                 EX/'r7-platform-layout-request.json',EX/'r8-compare-links.json',S)


@pytest.mark.parametrize('file',[
    'manifest.json','base.json','source.md','request.json','links.json','matrix.json',
    'styles/evemiss-native-demo.yaml'])
def test_manifest_material_tamper_fails(staged,file):
    p=staged/P/r8.DIR_NAME/MID/file
    p.write_bytes(p.read_bytes()+b'\nwrong')
    with pytest.raises((r8.MatrixReviewError,r7.PlatformLayoutError,
                        r6.SubtitleLayoutError,stage.ReviewPackageError,
                        stage.bridge.r0.ProgramError,ValueError)):
        r8.load(staged,P,MID)


def test_staged_mp4_tampering_fails(staged):
    video=staged/P/stage.PACKAGE_DIR/'r7_square_social_v1'/'preview.mp4'
    with video.open('ab') as f:f.write(b'not expected bytes')
    with pytest.raises((r8.MatrixReviewError,stage.ReviewPackageError,
                        r6.SubtitleLayoutError)):
        r8.load(staged,P,MID)


def test_r6_receipt_tamper_fails(staged):
    report=staged/P/r6.RECORD_DIR/'r7_tiktok_vertical_v1'/'layout_report.json'
    data=json.loads(report.read_text(encoding='utf-8'))
    data['receipt']['line_count']=99
    report.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises((r8.MatrixReviewError,r6.SubtitleLayoutError)):
        r8.load(staged,P,MID)


def test_r7_program_and_source_replay_fails_when_candidate_modified(staged):
    plan=staged/P/stage.PACKAGE_DIR/'r7_youtube_landscape_v1'/'plan.json'
    p=json.loads(plan.read_text(encoding='utf-8'));p['title']='forged version'
    plan.write_text(json.dumps(p),encoding='utf-8')
    with pytest.raises((r8.MatrixReviewError,stage.ReviewPackageError,stage.bridge.r0.ProgramError)):
        r8.load(staged,P,MID)


def test_no_cross_project_reference(staged):
    other=staged/'other-project';other.mkdir()
    with pytest.raises((FileNotFoundError,stage.ReviewPackageError)):
        r8.load(staged,'other-project',MID)


def test_malformed_ids_and_link_ambiguity(staged):
    with pytest.raises(stage.ReviewPackageError):r8.load(staged,P,'../outside')
    with pytest.raises(stage.ReviewPackageError):r8.load(staged,'../bad',MID)
    report=r8.load(staged,P,MID)['r7_matrix']
    bad={'schema':r8.LINKS_SCHEMA,'links':[
        {'profile':'square_social_v1','candidate_id':'r7_square_social_v1'},
        {'profile':'square_social_v1','candidate_id':'r7_tiktok_vertical_v1'},
    ]}
    with pytest.raises(r8.MatrixReviewError):r8._load_links(bad,report)
    bad['links'][1]['profile']='tiktok_vertical_v1';bad['links'][1]['candidate_id']='../hack'
    with pytest.raises(r8.MatrixReviewError):r8._load_links(bad,report)
    bad['links'][1]['candidate_id']='r7_tiktok_vertical_v1';bad['links'][1]['post']='http://evil'
    with pytest.raises(r8.MatrixReviewError):r8._load_links(bad,report)


def test_wrong_profile_candidate_binding_fails(staged):
    mpath=staged/P/r8.DIR_NAME/MID/'links.json'
    data=json.loads(mpath.read_text(encoding='utf-8'))
    data['links'][0]['candidate_id'],data['links'][1]['candidate_id']=(
        data['links'][1]['candidate_id'],data['links'][0]['candidate_id'])
    mpath.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(r8.MatrixReviewError):r8.load(staged,P,MID)


def test_symlink_source_escape_fails(staged,tmp_path):
    source=staged/P/r8.DIR_NAME/MID/'source.md';source.unlink()
    other=tmp_path/'private.md';other.write_text('private',encoding='utf-8')
    try:source.symlink_to(other)
    except (OSError,NotImplementedError):pytest.skip('no symlinks')
    with pytest.raises((r8.MatrixReviewError,stage.ReviewPackageError)):r8.load(staged,P,MID)


def test_missing_candidate_fails_closed(staged):
    shutil.rmtree(staged/P/stage.PACKAGE_DIR/'r7_square_social_v1')
    with pytest.raises((FileNotFoundError,stage.ReviewPackageError)):
        r8.load(staged,P,MID)


def test_extra_r8_files_fail(staged):
    (staged/P/r8.DIR_NAME/MID/'untrusted.json').write_text('{}',encoding='utf-8')
    with pytest.raises(r8.MatrixReviewError,match='extra'):
        r8.load(staged,P,MID)
