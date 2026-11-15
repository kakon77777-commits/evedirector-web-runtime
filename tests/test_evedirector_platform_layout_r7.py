"""R7 finite platform-layout reproducibility, rejects unsafe profiles and stale data."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys

import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import evedirector_platform_layout_r7 as r7
import evedirector_review_stage as stage

def inputs():
    folder=ROOT/"examples/native-video"
    base=json.loads((folder/"r6-layout-base.json").read_text(encoding="utf-8"))
    request=json.loads((folder/"r7-platform-layout-request.json").read_text(encoding="utf-8"))
    source=(folder/"source/r6-subtitle-layout.md").read_bytes()
    return base,request,source

def run(base,request,source):
    return r7.compile_matrix(base,source,ROOT/"styles",request)

def test_real_three_aspect_profiles_and_grounding():
    b,r,s=inputs()
    matrix,variants=run(b,r,s)
    assert matrix["status"]=="PASS_EDITING_SAFE_LAYOUT_MATRIX"
    assert matrix["official_platform_safe_area_certified"] is False
    assert matrix["approved_for_publish"] is False
    assert [(v["plan"]["width"],v["plan"]["height"]) for v in variants]==[(540,540),(360,640),(640,360)]
    assert [v["receipt"]["line_count"] for v in variants]==[3,3,2]
    for v in variants:
        assert v["receipt"]["status"]=="PASS_SAFE_LAYOUT_CONTRACT"
        assert v["receipt"]["font"]["font_file_embedded"] is False
        assert [(x["id"],x["start_frame"],x["end_frame"]) for x in v["plan"]["scenes"]]==[("intro",0,30),("outro",30,60)]
        assert v["plan"]["fps"]==b["fps"]
        assert len(v["receipt"]["lines"])>=2

def test_all_six_profile_presets_compile_with_no_unapproved_authority():
    b,r,s=inputs()
    r["profiles"]=sorted(r7.PROFILES)
    m,v=run(b,r,s)
    assert len(v)==6
    assert {item["provider"] for item in m["variants"]}=={"bilibili","youtube","tiktok","generic"}
    assert all(x["approved_for_publish"] is False for x in (m,))

def test_determinism_and_no_base_mutation():
    b,r,s=inputs()
    bb=stage.canonical(b);rb=stage.canonical(r)
    x=run(b,r,s);y=run(b,r,s)
    assert stage.canonical(x[0])==stage.canonical(y[0])
    assert [stage.canonical(z["plan"]) for z in x[1]] == [stage.canonical(z["plan"]) for z in y[1]]
    assert (stage.canonical(b),stage.canonical(r))==(bb,rb)

@pytest.mark.parametrize("mutate,pattern",[
    (lambda q:q.update(schema="wrong"),"schema"),
    (lambda q:q.update(url="https://evil.example"),"unknown"),
    (lambda q:q.update(profiles=["bad"]), "profiles"),
    (lambda q:q.update(profiles=["tiktok_vertical_v1","tiktok_vertical_v1"]), "profiles"),
    (lambda q:q.update(profiles=["youtube_landscape_v1","square_social_v1"]), "profiles"),
    (lambda q:q["font"].update(sha256="0"*64), "pinned font"),
    (lambda q:q["font"].update(face_index=0), "pinned font"),
    (lambda q:q["cues"].pop(), "one source-grounded cue"),
    (lambda q:q["cues"][0].update(text="來源沒有的文字"),"exact scene source"),
    (lambda q:q["cues"][1].update(layer_id="../unsafe"),"one source-grounded cue"),
    (lambda q:q["cues"][0].update(text="😀😀😀😀😀😀😀😀"), "unsupported subtitle"),
])
def test_adversaries_fail_closed(mutate,pattern):
    b,r,s=inputs();mutate(r)
    with pytest.raises((r7.PlatformLayoutError,r7.r6.SubtitleLayoutError),match=pattern):
        run(b,r,s)

def test_no_unspecified_keyframe_resizing():
    b,r,s=inputs()
    b["scenes"][0]["layers"][0]["keyframes"]={"x":[{"frame":0,"value":12}]}
    with pytest.raises(r7.PlatformLayoutError,match="animated"):
        run(b,r,s)

def test_export_verify_and_no_overwrite(tmp_path):
    b,r,s=inputs();m,v=run(b,r,s)
    out=tmp_path/"matrix"
    r7.output_files(out,r7._expected_files(m,v),False)
    r7.output_files(out,r7._expected_files(m,v),True)
    with pytest.raises(r7.PlatformLayoutError,match="exists"):
        r7.output_files(out,r7._expected_files(m,v),False)
    plan=out/"tiktok_vertical_v1.plan.json"
    plan.write_bytes(plan.read_bytes().replace(b'"width":360',b'"width":361',1))
    with pytest.raises(r7.PlatformLayoutError,match="replay mismatch"):
        r7.output_files(out,r7._expected_files(m,v),True)

def test_symlink_export_file_rejected(tmp_path):
    b,r,s=inputs();m,v=run(b,r,s)
    out=tmp_path/"matrix"
    r7.output_files(out,r7._expected_files(m,v),False)
    path=out/"matrix.json";path.unlink()
    other=tmp_path/"arbitrary.json";other.write_text("private",encoding="utf-8")
    try:path.symlink_to(other)
    except (OSError,NotImplementedError):pytest.skip("no symlinks")
    with pytest.raises(r7.PlatformLayoutError):
        r7.output_files(out,r7._expected_files(m,v),True)
