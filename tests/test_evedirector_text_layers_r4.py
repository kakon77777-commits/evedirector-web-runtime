"""R4 bounded text probes, fail-closed replay and authority tests."""
from __future__ import annotations

import copy
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evedirector_text_layers_r4 as r4
import evedirector_review_stage as stage
import evedirector_remotion_bridge as bridge


@pytest.fixture
def bundle():
    return bridge.build_props(
        bridge.read_strict_json(ROOT / "examples/native-video/program.json"),
        bridge.read_source(ROOT / "examples/native-video/source/README.md"),
        ROOT / "styles",
    )["bundle"]


@pytest.fixture
def black_env(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("requires FFmpeg and FFprobe")
    root = tmp_path / "projects"
    (root / "demo").mkdir(parents=True)
    path = tmp_path / "black.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=640x360:r=12", "-frames:v", "60",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True, timeout=45)
    stage.stage(root, "demo", "black_r4", ROOT / "examples/native-video/program.json",
                ROOT / "examples/native-video/source/README.md", ROOT / "styles", path)
    return root


def test_frame_sampling_is_bounded_and_covers_demo(bundle):
    frames = r4._frame_set(bundle)
    assert len(frames) == 60 and frames == list(range(60))
    large = copy.deepcopy(bundle)
    large["width"] = 250000
    with pytest.raises(r4.TextProbeError, match="memory"):
        r4._frame_set(large)


def test_ascii_font_and_unicode_boundaries(bundle):
    clip = bundle["clips"][0]
    layer = copy.deepcopy(clip["layers"][2])
    ok, reason = r4._supports_layer(layer, bundle, 29, r4.FONT_PATH)
    assert ok and reason == ""
    layer["text"] = "漢字"
    assert r4._supports_layer(layer, bundle, 29, r4.FONT_PATH) == (
        False, "non-ascii-or-multiline-text-not-modeled")
    layer["text"] = "A\nB"
    assert not r4._supports_layer(layer, bundle, 29, r4.FONT_PATH)[0]
    layer["text"] = "EVEDIRECTOR"
    assert not r4._supports_layer(layer, bundle, 29, "/missing/this-font.ttf")[0]


def test_layer_geometry_coverage_with_edges(bundle):
    clip = bundle["clips"][0]
    panel = clip["layers"][1]
    assert r4._shape_cover(panel, 29, 100, 150) == (True, False)
    assert r4._shape_cover(panel, 29, 53, 126)[0]
    assert r4._shape_cover(panel, 29, 1, 1)[0] is False


def test_no_video_is_refused(tmp_path):
    root = tmp_path / "projects"
    (root / "demo").mkdir(parents=True)
    stage.stage(root, "demo", "no_video", ROOT / "examples/native-video/program.json",
                ROOT / "examples/native-video/source/README.md", ROOT / "styles")
    with pytest.raises(r4.TextProbeError, match="no verified video"):
        r4.inspect(stage.load_package(root, "demo", "no_video"), "no_video")


def test_same_spec_black_has_failed_text_strokes(black_env):
    item = stage.load_package(black_env, "demo", "black_r4")
    report = r4.inspect(item, "black_r4")
    assert report["status"] == "FAIL_SAMPLED_TEXT"
    assert report["total_frames"] == 60
    assert report["sampled_frames"] == list(range(60))
    assert report["bad_pixels"] > 200
    assert report["approved_for_publish"] is False
    assert report["visual_equivalence_attested"] is False
    assert report["excluded"] and "non-ASCII-glyphs" in report["excluded"]


def test_report_replay_exact_and_append_only(black_env):
    item = stage.load_package(black_env, "demo", "black_r4")
    report = r4.inspect(item, "black_r4")
    path = r4.store(black_env, "demo", "black_r4", report)
    assert path.stem == stage.digest(path.read_bytes())
    assert r4.load_report(black_env, "demo", "black_r4", item) == report
    with pytest.raises(r4.TextProbeError, match="already exists"):
        r4.store(black_env, "demo", "black_r4", report)


def test_rehashed_forged_pass_is_rejected(black_env):
    item = stage.load_package(black_env, "demo", "black_r4")
    report = r4.inspect(item, "black_r4")
    path = r4.store(black_env, "demo", "black_r4", report)
    path.unlink()
    report["status"] = "PASS_SAMPLED_TEXT"
    forged = stage.canonical(report)
    (path.parent / (stage.digest(forged) + ".json")).write_bytes(forged)
    with pytest.raises(r4.TextProbeError, match="fresh video measurement"):
        r4.load_report(black_env, "demo", "black_r4", item)


def test_report_bit_flip_and_symlink_are_rejected(black_env, tmp_path):
    item = stage.load_package(black_env, "demo", "black_r4")
    report = r4.inspect(item, "black_r4")
    path = r4.store(black_env, "demo", "black_r4", report)
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(r4.TextProbeError, match="hash mismatch"):
        r4.load_report(black_env, "demo", "black_r4", item)
    path.unlink()
    outside = tmp_path / "external"
    outside.write_text("not a report", encoding="utf-8")
    try:
        path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(r4.TextProbeError, match="unsafe"):
        r4.load_report(black_env, "demo", "black_r4", item)


def test_missing_report_returns_none(black_env):
    item = stage.load_package(black_env, "demo", "black_r4")
    assert r4.load_report(black_env, "demo", "black_r4", item) is None


def test_injected_video_hash_mismatch_refuses_report(black_env):
    item = stage.load_package(black_env, "demo", "black_r4")
    report = r4.inspect(item, "black_r4")
    r4.store(black_env, "demo", "black_r4", report)
    bad = copy.deepcopy(item)
    bad["manifest"]["video"]["sha256"] = "f" * 64
    with pytest.raises(r4.TextProbeError, match="fresh video measurement"):
        r4.load_report(black_env, "demo", "black_r4", bad)


def test_cli_does_not_turn_failure_into_success(black_env, capsys):
    args = ["--projects-dir", str(black_env), "--project-id", "demo", "--candidate-id", "black_r4"]
    assert r4.main(["check", *args]) == 3
    assert r4.main(["verify", *args]) == 3
    assert "FAIL_SAMPLED_TEXT" in capsys.readouterr().out


def test_partial_coverage_cannot_fake_full_success(bundle):
    clip = bundle["clips"][0]
    heading = copy.deepcopy(clip["layers"][2])
    heading["text"] = "漢字"
    assert r4._supports_layer(heading, bundle, 29, r4.FONT_PATH)[0] is False
    assert r4._supports_layer(heading, bundle, 29, r4.FONT_PATH)[1] != ""
