"""R6 deterministic subtitle wrapping / pinned-font / safe-area adversarial tests."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import evedirector_subtitle_layout_r6 as r6
import evedirector_programmatic as r0
import evedirector_review_stage as stage


@pytest.fixture
def fixture():
    root=ROOT/'examples/native-video'
    base=json.loads((root/'r6-layout-base.json').read_text(encoding='utf-8'))
    req=json.loads((root/'r6-layout-request.json').read_text(encoding='utf-8'))
    source=(root/'source/r6-subtitle-layout.md').read_bytes()
    return base,req,source


def _compile(t):
    base,req,source=t
    return r6.compile_layout(base,source,ROOT/'styles',req)


def test_compile_source_grounding_explicit_sublayers_and_bbox(fixture):
    plan,report=_compile(fixture)
    assert report['status']=='PASS_SAFE_LAYOUT_CONTRACT'
    assert report['candidate_only'] is True
    assert report['approved_for_publish'] is False
    assert report['visual_equivalence_attested'] is False
    assert report['line_count']==4
    assert report['font']['font_file_embedded'] is False
    assert 'file' not in report['font']
    assert report['compiled_program_sha256']==r0.validate(plan,fixture[2],ROOT/'styles')['program_sha256']
    assert '安全自動換行' in [x['text'] for x in report['lines']]
    for scene in plan['scenes']:
        assert 'subtitle' not in {l['id'] for l in scene['layers']}
        assert len(scene['layers'])==3
        for layer in scene['layers']:
            if layer['kind']=='text':
                assert len(layer['text'])<=28
                assert layer['font_profile']=='noto-cjk-tc-v1'
    for line in report['lines']:
        assert line['x']+line['glyph_bbox'][2] <= plan['width']-36
        assert line['y']+line['glyph_bbox'][3] <= plan['height']-30
        assert line['x']+line['glyph_bbox'][0] >= 36
        assert line['y']+line['glyph_bbox'][1] >= 36


def test_compile_is_bitwise_deterministic(fixture):
    p1,r1=_compile(fixture)
    p2,r2=_compile(fixture)
    assert stage.canonical(p1)==stage.canonical(p2)
    assert stage.canonical(r1)==stage.canonical(r2)
    assert _compile(fixture)[1]['font']['sha256']==fixture[1]['font']['sha256']


def test_old_scene_ir_unchanged():
    plan=json.loads((ROOT/'examples/native-video/program.json').read_text(encoding='utf-8'))
    source=(ROOT/'examples/native-video/source/README.md').read_bytes()
    assert r0.validate(plan,source,ROOT/'styles')['frames']==60


@pytest.mark.parametrize('alter,match',[
    (lambda r:r['font'].update(sha256='0'*64),'pinned font SHA/index'),
    (lambda r:r['font'].update(face_index=0),'pinned font SHA/index'),
    (lambda r:r['font'].update(profile='web-font-url'),'pinned font'),
    (lambda r:r.update(schema='evil'),'schema'),
    (lambda r:r.update(fetch='https://evil.invalid/font.ttf'),'unknown or missing'),
    (lambda r:r['safe_area'].update(left=300),'safe margins'),
    (lambda r:r['safe_area'].update(top=200,bottom=100),'safe zone'),
    (lambda r:r['cues'][0].update(placement='right'),'placement'),
    (lambda r:r['cues'][0].update(text='未曾出現在來源文件'),'exact scene source'),
    (lambda r:r['cues'][0].update(text='繁體中文\nAI字幕'),'unsupported subtitle'),
    (lambda r:r['cues'][0].update(text='繁體中文\u200dAI字幕'),'unsupported subtitle'),
    (lambda r:r['cues'][0].update(text='繁體中文\u202eAI字幕'),'unsupported subtitle'),
    (lambda r:r['cues'][0].update(text='繁體中文  AI字幕'),'NFC'),
    (lambda r:r['cues'][0].update(text='繁體中文👍AI字幕'),'unsupported subtitle'),
])
def test_bad_layout_rejected(fixture,alter,match):
    base,req,source=copy.deepcopy(fixture)
    alter(req)
    with pytest.raises(r6.SubtitleLayoutError,match=match):
        r6.compile_layout(base,source,ROOT/'styles',req)


def test_unbreakable_long_latin_word_rejected(fixture):
    base,req,source=copy.deepcopy(fixture)
    word='LONGCAPTIONWORD'*8
    req['cues'][0]['text']=word
    # Source evidence exists: rejection is caused by bounded typesetting.
    lines=source.decode('utf-8').splitlines()
    lines[2] += ' '+word
    updated=('\n'.join(lines)+'\n').encode('utf-8')
    with pytest.raises(r6.SubtitleLayoutError,match='cannot fit'):
        r6.compile_layout(base,updated,ROOT/'styles',req)


def test_duplicate_cue_and_unsafe_target_rejected(fixture):
    base,req,source=copy.deepcopy(fixture)
    req['cues'].append(copy.deepcopy(req['cues'][0]))
    with pytest.raises(r6.SubtitleLayoutError,match='duplicate'):
        r6.compile_layout(base,source,ROOT/'styles',req)
    req=copy.deepcopy(fixture[1]);req['cues'][0]['layer_id']='../../x'
    with pytest.raises(r6.SubtitleLayoutError,match='layer missing'):
        r6.compile_layout(base,source,ROOT/'styles',req)


def test_missing_font_refuses_fallback(monkeypatch,fixture):
    def bad():
        raise r6.r5.MultilangProbeError('not installed')
    monkeypatch.setattr(r6.r5,'font_environment',bad)
    with pytest.raises(r6.SubtitleLayoutError,match='font unavailable'):
        _compile(fixture)


def test_safe_area_does_not_resize_source(fixture):
    old=stage.canonical(fixture[0])
    _compile(fixture)
    assert stage.canonical(fixture[0])==old


def test_stage_replay_tamper_and_append_only(tmp_path,fixture):
    base,req,source=fixture
    plan,report=_compile(fixture)
    projects=tmp_path/'projects';(projects/'demo').mkdir(parents=True)
    source_path=tmp_path/'source.md';source_path.write_bytes(source)
    plan_path=tmp_path/'plan.json';plan_path.write_bytes(stage.canonical(plan))
    stage.stage(projects,'demo','layout_r6',plan_path,source_path,ROOT/'styles')
    item=stage.load_package(projects,'demo','layout_r6')
    path=r6.store(projects,'demo','layout_r6',item,base,req)
    assert r6.load_report(projects,'demo','layout_r6',item)==report
    with pytest.raises(r6.SubtitleLayoutError,match='already exists'):
        r6.store(projects,'demo','layout_r6',item,base,req)
    bad=json.loads(path.read_text(encoding='utf-8'));bad['receipt']['status']='PASS_FULL_VIDEO'
    path.write_bytes(stage.canonical(bad))
    with pytest.raises(r6.SubtitleLayoutError,match='no longer matches'):
        r6.load_report(projects,'demo','layout_r6',item)


def test_stage_rejects_modified_compiled_plan(tmp_path,fixture):
    base,req,source=fixture
    plan,_=_compile(fixture)
    plan['scenes'][0]['layers'][1]['x']+=14
    projects=tmp_path/'projects';(projects/'demo').mkdir(parents=True)
    source_path=tmp_path/'source.md';source_path.write_bytes(source)
    plan_path=tmp_path/'plan.json';plan_path.write_bytes(stage.canonical(plan))
    stage.stage(projects,'demo','layout_r6',plan_path,source_path,ROOT/'styles')
    item=stage.load_package(projects,'demo','layout_r6')
    with pytest.raises(r6.SubtitleLayoutError,match='differs from staged'):
        r6.store(projects,'demo','layout_r6',item,base,req)


def test_layout_report_rejects_symlink(tmp_path,fixture):
    base,req,source=fixture
    plan,_=_compile(fixture)
    projects=tmp_path/'projects';(projects/'demo').mkdir(parents=True)
    sp=tmp_path/'source.md';sp.write_bytes(source)
    pp=tmp_path/'plan.json';pp.write_bytes(stage.canonical(plan))
    stage.stage(projects,'demo','layout_r6',pp,sp,ROOT/'styles')
    item=stage.load_package(projects,'demo','layout_r6')
    p=r6.store(projects,'demo','layout_r6',item,base,req)
    real=tmp_path/'attack.json';real.write_text('private',encoding='utf-8')
    p.unlink()
    try:p.symlink_to(real)
    except (NotImplementedError,OSError):pytest.skip('symlinks unavailable')
    with pytest.raises(stage.ReviewPackageError):
        r6.load_report(projects,'demo','layout_r6',item)


def test_font_index_is_pinned_to_file(fixture):
    env=r6.r5.font_environment()
    assert fixture[1]['font']['face_index']==env['face_index']
    assert fixture[1]['font']['sha256']==env['font_sha256']
