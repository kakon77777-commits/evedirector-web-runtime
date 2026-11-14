"""R3 bounded geometry probes, negative MP4s, immutable receipts and authority."""
from __future__ import annotations
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evedirector_visual_probe as visual
import evedirector_review_stage as stage
import evedirector_remotion_bridge as bridge


@pytest.fixture
def bundle():
    plan = bridge.read_strict_json(ROOT / "examples/native-video/program.json")
    source = bridge.read_source(ROOT / "examples/native-video/source/README.md")
    return bridge.build_props(plan, source, ROOT / "styles")["bundle"]


@pytest.fixture
def black_candidate(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("requires ffmpeg and ffprobe")
    root = tmp_path / "projects"
    (root / "demo").mkdir(parents=True)
    black = tmp_path / "black.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=640x360:r=12", "-frames:v", "60",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(black),
    ], check=True, timeout=45)
    stage.stage(root, "demo", "black_candidate",
                ROOT / "examples/native-video/program.json",
                ROOT / "examples/native-video/source/README.md", ROOT / "styles", black)
    return root


def _item(root):
    return stage.load_package(root, "demo", "black_candidate")


def test_sampling_coverage_and_bound(bundle):
    frames = visual._select_frames(bundle)
    assert 2 <= len(frames) <= visual.MAX_FRAMES
    assert frames == sorted(set(frames))
    assert frames[0] == 0 and frames[-1] == 59
    assert {visual._active_clip(bundle, i)["id"] for i in frames} == {"intro", "outro"}


def test_analytic_keyframes(bundle):
    halo = bundle["clips"][0]["layers"][0]
    assert visual._interpolated(halo, "x", 0) == 620
    assert visual._interpolated(halo, "x", 29) == 420
    assert visual._interpolated(halo, "x", 14.5) == 520
    assert visual._geometry_at(halo, 29)["x"] == 420


def test_background_geometry_and_text_mask(bundle):
    clip = bundle["clips"][0]
    assert visual._prediction(bundle, clip, 29, 2, 2) == ((11, 19, 36), "background")
    assert visual._prediction(bundle, clip, 29, 480, 90)[1] == "geometry"
    assert visual._prediction(bundle, clip, 29, 100, 162) is None
    assert visual._prediction(bundle, clip, 16, 52, 127) is None


def test_thin_geometry_gets_extra_probes(bundle):
    pts = visual._coordinates(bundle, bundle["clips"][1], 29)
    assert len(pts) == len(set(pts))
    assert len(pts) <= visual.MAX_PIXELS_PER_FRAME
    assert any(70 <= x < 85 and 90 <= y < 270 for x, y in pts)


def test_reject_oversized_frame_budget(bundle):
    bad = copy.deepcopy(bundle)
    bad["width"], bad["height"] = 12000, 10000
    with pytest.raises(visual.VisualProbeError, match="frame buffer"):
        visual._select_frames(bad)


def test_no_video_refuses_probe(tmp_path):
    root = tmp_path / "projects"
    (root / "demo").mkdir(parents=True)
    stage.stage(root, "demo", "no_video",
                ROOT / "examples/native-video/program.json",
                ROOT / "examples/native-video/source/README.md", ROOT / "styles")
    item = stage.load_package(root, "demo", "no_video")
    with pytest.raises(visual.VisualProbeError, match="no verified MP4"):
        visual.inspect(item, "no_video")
    assert visual.load_report(root, "demo", "no_video", item) is None


def test_same_spec_black_mp4_fails(black_candidate):
    report = visual.inspect(_item(black_candidate), "black_candidate")
    assert report["status"] == "FAIL_SAMPLED_GEOMETRY"
    assert report["bad_pixel_fraction"] > 0.75
    assert report["geometry_pixels"] > 100
    assert report["total_frames"] == 60
    assert "text-glyphs" in report["excluded"]
    assert report["approved_for_publish"] is False
    assert report["visual_equivalence_attested"] is False


def test_report_roundtrip_and_append_only(black_candidate):
    item = _item(black_candidate)
    report = visual.inspect(item, "black_candidate")
    path = visual.store(black_candidate, "demo", "black_candidate", report)
    assert path.stem == stage.digest(path.read_bytes())
    assert visual.load_report(black_candidate, "demo", "black_candidate", item) == report
    with pytest.raises(visual.VisualProbeError, match="already staged"):
        visual.store(black_candidate, "demo", "black_candidate", report)


def test_report_tamper_detected(black_candidate):
    item = _item(black_candidate)
    path = visual.store(black_candidate, "demo", "black_candidate",
                        visual.inspect(item, "black_candidate"))
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(visual.VisualProbeError, match="content hash"):
        visual.load_report(black_candidate, "demo", "black_candidate", item)


def test_rehashed_false_pass_rejected(black_candidate):
    item = _item(black_candidate)
    report = visual.inspect(item, "black_candidate")
    path = visual.store(black_candidate, "demo", "black_candidate", report)
    path.unlink()
    report["status"] = "PASS_SAMPLED_GEOMETRY"
    raw = stage.canonical(report)
    (path.parent / (stage.digest(raw) + ".json")).write_bytes(raw)
    with pytest.raises(visual.VisualProbeError, match="result inconsistent"):
        visual.load_report(black_candidate, "demo", "black_candidate", item)


def test_extra_report_rejected(black_candidate):
    item = _item(black_candidate)
    path = visual.store(black_candidate, "demo", "black_candidate",
                        visual.inspect(item, "black_candidate"))
    (path.parent / "junk.json").write_text("{}", encoding="utf-8")
    with pytest.raises(visual.VisualProbeError, match="ambiguous"):
        visual.load_report(black_candidate, "demo", "black_candidate", item)


def test_symlink_directory_rejected(black_candidate, tmp_path):
    item = _item(black_candidate)
    path = visual.store(black_candidate, "demo", "black_candidate",
                        visual.inspect(item, "black_candidate"))
    shutil.rmtree(path.parent)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        path.parent.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(stage.ReviewPackageError, match="symlink"):
        visual.load_report(black_candidate, "demo", "black_candidate", item)


def test_video_hash_binding(black_candidate):
    item = _item(black_candidate)
    visual.store(black_candidate, "demo", "black_candidate",
                 visual.inspect(item, "black_candidate"))
    wrong = copy.deepcopy({k:v for k,v in item.items() if k != "video_path"})
    wrong["manifest"]["video"]["sha256"] = "a"*64
    with pytest.raises(visual.VisualProbeError, match="schema/pins"):
        visual.load_report(black_candidate, "demo", "black_candidate", wrong)


def test_negative_status_exit_code_and_no_apply(black_candidate, capsys):
    args = ["--projects-dir", str(black_candidate), "--project-id", "demo",
            "--candidate-id", "black_candidate"]
    assert visual.main(["check", *args]) == 3
    assert visual.main(["verify", *args]) == 3
    assert "FAIL_SAMPLED_GEOMETRY" in capsys.readouterr().out
    report = visual.inspect(_item(black_candidate), "black_candidate")
    assert report["candidate_only"] is True
    assert report["approved_for_publish"] is False
    assert "apply" not in report
