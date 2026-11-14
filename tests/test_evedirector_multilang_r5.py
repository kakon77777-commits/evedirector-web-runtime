"""R5 multilingual candidate/font-profile contracts; excludes release authority."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import evedirector_programmatic as r0
import evedirector_remotion_bridge as bridge
import evedirector_review_stage as stage
import evedirector_multilang_probe_r5 as r5


@pytest.fixture
def r5plan():
    return json.loads((ROOT / 'examples/native-video/r5-multilingual.json').read_text(encoding='utf-8'))


@pytest.fixture
def source():
    return (ROOT / 'examples/native-video/source/r5-multilingual.md').read_bytes()


def test_legacy_R0_R1_receipt_is_unchanged():
    plan = json.loads((ROOT / 'examples/native-video/program.json').read_text(encoding='utf-8'))
    source = (ROOT / 'examples/native-video/source/README.md').read_bytes()
    assert r0.validate(plan, source, ROOT / 'styles')['frames'] == 60
    bundle = bridge.build_props(plan, source, ROOT / 'styles')['bundle']
    assert all('font_profile' not in x for c in bundle['clips'] for x in c['layers'])


def test_R5_explicit_font_profile_is_source_grounded(r5plan, source):
    receipt = r0.validate(r5plan, source, ROOT / 'styles')
    assert receipt['frames'] == 60
    props = bridge.build_props(r5plan, source, ROOT / 'styles')
    assert props['bundle']['clips'][0]['layers'][1]['font_profile'] == 'noto-cjk-tc-v1'
    assert props['bundle']['clips'][1]['layers'][1]['text'].count('\n') == 1
    assert bridge.verify(props, r5plan, source, ROOT / 'styles')


def test_reject_implicit_unicode_fallback(r5plan, source):
    plan = copy.deepcopy(r5plan)
    del plan['scenes'][0]['layers'][1]['font_profile']
    with pytest.raises(r0.ProgramError, match='requires explicit CJK'):
        r0.validate(plan, source, ROOT / 'styles')


@pytest.mark.parametrize('profile', ['../../evil', 'Noto Sans CJK TC', 'custom:https://evil', '', 9])
def test_reject_unknown_font_profile(r5plan, source, profile):
    plan = copy.deepcopy(r5plan)
    plan['scenes'][0]['layers'][1]['font_profile'] = profile
    with pytest.raises(r0.ProgramError, match='font_profile'):
        r0.validate(plan, source, ROOT / 'styles')


def test_reject_font_profile_on_geometry(r5plan, source):
    plan=copy.deepcopy(r5plan)
    plan['scenes'][0]['layers'][0]['font_profile']='noto-cjk-tc-v1'
    with pytest.raises(r0.ProgramError, match='incompatible'):
        r0.validate(plan,source,ROOT/'styles')


@pytest.mark.parametrize('value', ['x\u202eABC', 'a\u200bB', 'a\u200dB', 'a\tB', 'line\rB'])
def test_reject_format_controls(r5plan, source, value):
    plan=copy.deepcopy(r5plan)
    plan['scenes'][0]['layers'][1]['text']=value
    with pytest.raises(r0.ProgramError,match='forbidden'):
        r0.validate(plan,source,ROOT/'styles')


@pytest.mark.parametrize('value', ['\nChinese', 'ab\n\nChinese','中'*29,'中\n英\n文'])
def test_reject_unsupported_explicit_lines(r5plan, source, value):
    plan=copy.deepcopy(r5plan)
    plan['scenes'][1]['layers'][1]['text']=value
    with pytest.raises(r0.ProgramError,match='unsupported CJK line layout'):
        r0.validate(plan,source,ROOT/'styles')


def test_coverage_and_font_hash_available_when_installed():
    try:
        env=r5.font_environment()
    except r5.MultilangProbeError:
        pytest.skip('opt-in Noto Sans CJK TC test requires fonts-noto-cjk')
    assert env['family'] == 'Noto Sans CJK TC'
    assert env['face_index'] >= 0
    assert len(env['font_sha256'])==64
    assert env['font_bytes']>100_000
    assert all(ord(x) in r5.supported_characters() for x in '繁體字幕程式影片')


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='requires FFmpeg')
def test_black_video_fails_and_missing_font_is_inconclusive(tmp_path, monkeypatch, r5plan, source):
    projects=tmp_path/'projects'
    (projects/'demo').mkdir(parents=True)
    video=tmp_path/'black.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi',
                    '-i','color=c=black:s=640x360:r=12','-frames:v','60',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True,timeout=45)
    stage.stage(projects,'demo','black',ROOT/'examples/native-video/r5-multilingual.json',
                ROOT/'examples/native-video/source/r5-multilingual.md',ROOT/'styles',video)
    item=stage.load_package(projects,'demo','black')
    monkeypatch.setattr(r5,'font_environment',lambda: (_ for _ in ()).throw(r5.MultilangProbeError('no font')))
    unknown=r5.inspect(item,'black')
    assert unknown['status']=='INCONCLUSIVE_MULTILINGUAL_TEXT'
    assert unknown['font']['font_file_embedded'] is False
    monkeypatch.undo()
    try:
        report=r5.inspect(item,'black')
    except r5.MultilangProbeError:
        pytest.skip('Noto CJK font unavailable')
    assert report['status']=='FAIL_SAMPLED_MULTILINGUAL_TEXT'
    assert report['failed_samples']>0
    assert report['approved_for_publish'] is False
    assert report['font']['font_file_embedded'] is False
    assert 'file' not in report['font']
    path=r5.store(projects,'demo','black',report)
    assert r5.load_report(projects,'demo','black',item)==report
    with pytest.raises(r5.MultilangProbeError,match='already exists'):
        r5.store(projects,'demo','black',report)
    bad=copy.deepcopy(report);bad['status']='PASS_SAMPLED_MULTILINGUAL_TEXT'
    raw=stage.canonical(bad)
    path.unlink()
    forged=path.parent/(hashlib.sha256(raw).hexdigest()+'.json')
    forged.write_bytes(raw)
    with pytest.raises(r5.MultilangProbeError,match='differs from fresh'):
        r5.load_report(projects,'demo','black',item)


def test_low_font_size_is_not_a_fake_pass(r5plan, source):
    plan=copy.deepcopy(r5plan)
    plan['scenes'][0]['layers'][1]['font_size']=25
    assert r0.validate(plan,source,ROOT/'styles')['frames']==60
    class DummyFace:
        pass
    layer=plan['scenes'][0]['layers'][1]
    bundle=bridge.build_props(plan,source,ROOT/'styles')['bundle']
    result=r5._measure_line(bundle,bundle['clips'][0],0,1,b'',DummyFace(),layer['text'],0)
    assert result['status']=='INCONCLUSIVE'
    assert result['reason']=='font-size-below-calibrated-range'
