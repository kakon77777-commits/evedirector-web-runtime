"""EveDirector R2 — isolated L4 programmatic preview, threat and replay tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evedirector_review_stage as stage
import evedirector_remotion_bridge as bridge
import backlot.agent_review as l4
import backlot.programmatic_review as review_r2
import backlot.server as server


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    projects_dir = tmp_path / "projects"
    project = projects_dir / "review-demo"
    project.mkdir(parents=True)
    monkeypatch.setattr(l4, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(server, "PROJECTS_DIR", projects_dir)
    plan = ROOT / "examples/native-video/program.json"
    source = ROOT / "examples/native-video/source/README.md"
    styles = ROOT / "styles"
    manifest = stage.stage(projects_dir, "review-demo", "demo_r2", plan, source, styles)
    app = FastAPI()
    app.include_router(review_r2.router)
    return {
        "client": TestClient(app), "project": project, "projects": projects_dir,
        "candidate": project / stage.PACKAGE_DIR / "demo_r2",
        "manifest": manifest, "plan": plan, "source": source, "styles": styles,
    }


def _base(setup: dict) -> str:
    return "/api/project/review-demo/programmatic-review"


def test_stage_and_read_only_index(setup: dict):
    response = setup["client"].get(_base(setup))
    assert response.status_code == 200
    data = response.json()
    assert data["authority"] == "read-only-no-apply"
    assert data["actions_supported"] is False
    assert len(data["candidates"]) == 1
    candidate = data["candidates"][0]
    assert candidate["candidate_id"] == "demo_r2"
    assert candidate["status"] == "source_replayed_preview_only"
    assert candidate["apply_supported"] is False
    assert candidate["scene_count"] == 2
    assert candidate["frames"] == 60
    assert candidate["fps"] == 12
    assert candidate["preview_available"] is False


def test_detail_grounding_sanitized_and_no_approval(setup: dict):
    response = setup["client"].get(_base(setup) + "/demo_r2")
    assert response.status_code == 200
    d = response.json()
    assert d["authority"]["mode"] == "read_only"
    assert d["authority"]["apply_supported"] is False
    assert d["authority"]["source_approval_verified"] is False
    assert d["authority"]["preview_matches_program_verified"] is False
    assert d["preview"] == {
        "available": False,
        "media_url": None,
        "integrity": "no-video-staged",
        "visual_equivalence_attested": False,
    }
    assert len(d["scenes"]) == 2
    for scene in d["scenes"]:
        a = scene["source"]
        assert a["source_contains"] in a["excerpt"]
        assert a["logical_line_sha256"] == hashlib.sha256(
            a["excerpt"].encode("utf-8")).hexdigest()
    assert d["timing"]["seconds"] == 5
    text = response.text
    assert "response.txt" not in text
    assert "request.json" not in text
    assert "model_metadata" not in text
    assert setup["client"].get(_base(setup) + "/demo_r2/media").status_code == 404


def test_no_apply_path_even_when_l3_actions_enabled(setup: dict, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(l4.ACTIONS_ENV, "1")
    spec = setup["project"] / "video_spec.yaml"
    spec.write_text("canonical: protected\n", encoding="utf-8")
    before = spec.read_bytes()
    base = _base(setup)
    for url in [base, base + "/demo_r2", base + "/demo_r2/media"]:
        assert setup["client"].post(url, json={
            "reviewer": "someone", "confirmation": "APPLY demo_r2",
        }).status_code in {404, 405}
    assert setup["client"].post(base + "/demo_r2/apply", json={
        "reviewer": "someone", "confirmation": "APPLY demo_r2",
    }).status_code == 404
    assert spec.read_bytes() == before


def test_replay_rejects_duplicate_existing_candidate(setup: dict):
    with pytest.raises(stage.ReviewPackageError, match="already exists"):
        stage.stage(setup["projects"], "review-demo", "demo_r2",
                    setup["plan"], setup["source"], setup["styles"])


@pytest.mark.parametrize("file,mutator", [
    ("source.md", lambda p: p.write_bytes(p.read_bytes().replace(b"motion", b"motion!", 1))),
    ("plan.json", lambda p: p.write_text(
        p.read_text(encoding="utf-8").replace('"frames": 60', '"frames": 59'), encoding="utf-8")),
    ("props.json", lambda p: p.write_bytes(p.read_bytes().replace(b'"candidate_only":true', b'"candidate_only":false', 1))),
    ("receipt.json", lambda p: p.write_bytes(p.read_bytes().replace(b'"clip_count":2', b'"clip_count":9', 1))),
    ("manifest.json", lambda p: p.write_bytes(p.read_bytes().replace(b'"candidate_only":true', b'"candidate_only":false', 1))),
    ("styles/evemiss-native-demo.yaml", lambda p: p.write_bytes(p.read_bytes() + b"\n# tampered style\n")),
])
def test_tamper_fails_closed(setup: dict, file, mutator):
    path = setup["candidate"] / file
    original = path.read_bytes()
    mutator(path)
    assert path.read_bytes() != original
    detail = setup["client"].get(_base(setup) + "/demo_r2")
    assert detail.status_code == 409
    assert "failed integrity" in detail.json()["detail"]
    listing = setup["client"].get(_base(setup))
    assert listing.status_code == 200
    assert listing.json()["candidates"][0]["status"] == "integrity_failed"


def test_duplicate_json_keys_rejected(setup: dict):
    path = setup["candidate"] / "manifest.json"
    data = path.read_text(encoding="utf-8")
    path.write_text(data[:-1] + ',"candidate_only":true}', encoding="utf-8")
    assert setup["client"].get(_base(setup) + "/demo_r2").status_code == 409


def test_invalid_candidate_and_project_ids_are_rejected(setup: dict):
    with pytest.raises(stage.ReviewPackageError):
        stage.load_package(setup["projects"], "review-demo", "../escape")
    with pytest.raises(stage.ReviewPackageError):
        stage.stage(setup["projects"], "review-demo", "a/b",
                    setup["plan"], setup["source"], setup["styles"])
    assert setup["client"].get(_base(setup) + "/missing").status_code == 404
    assert setup["client"].get("/api/project/missing/programmatic-review").status_code == 404


def test_cross_project_isolation(setup: dict):
    (setup["projects"] / "other-demo").mkdir()
    response = setup["client"].get("/api/project/other-demo/programmatic-review")
    assert response.status_code == 200 and response.json()["candidates"] == []
    assert setup["client"].get("/api/project/other-demo/programmatic-review/demo_r2").status_code == 404


def test_file_symlink_escape_rejected(setup: dict, tmp_path: Path):
    secret = tmp_path / "private-source.md"
    secret.write_text("private secret\n", encoding="utf-8")
    path = setup["candidate"] / "source.md"
    path.unlink()
    try:
        path.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this filesystem")
    assert setup["client"].get(_base(setup) + "/demo_r2").status_code == 409


def test_directory_symlink_escape_rejected(setup: dict, tmp_path: Path):
    shutil.rmtree(setup["candidate"] / "styles")
    other = tmp_path / "outside-styles"
    other.mkdir()
    try:
        (setup["candidate"] / "styles").symlink_to(other, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this filesystem")
    assert setup["client"].get(_base(setup) + "/demo_r2").status_code == 409


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="requires local FFmpeg/FFprobe")
def test_mp4_stage_stream_and_tamper_rejection(setup: dict, tmp_path: Path):
    video = tmp_path / "black-preview.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=640x360:r=12",
        "-frames:v", "60", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ], check=True, timeout=60)
    # Metadata is consistent but black frames intentionally do NOT match the scene
    # program. The API must refuse to certify visual equivalence.
    stage.stage(setup["projects"], "review-demo", "black_test",
                setup["plan"], setup["source"], setup["styles"], video)
    detail = setup["client"].get(_base(setup) + "/black_test")
    assert detail.status_code == 200
    d = detail.json()
    assert d["preview"]["available"]
    assert d["preview"]["visual_equivalence_attested"] is False
    media = setup["client"].get(_base(setup) + "/black_test/media")
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("video/mp4")
    assert media.headers["cache-control"] == "no-store"
    assert media.content == video.read_bytes()
    path = setup["project"] / stage.PACKAGE_DIR / "black_test" / "preview.mp4"
    with path.open("ab") as f:
        f.write(b"TAMPER")
    assert setup["client"].get(_base(setup) + "/black_test/media").status_code == 409


def test_server_has_l4_and_r2_routes_without_apply(setup: dict):
    app = server.create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/p/{project_id}/agent-review" in paths
    assert "/api/project/{project_id}/programmatic-review" in paths, {
        "app": sorted(paths),
        "r2_module_routes": [r.path for r in review_r2.router.routes],
        "server_alias_routes": [r.path for r in server.programmatic_review_router.routes],
        "server_module": server.__file__,
        "r2_module": review_r2.__file__,
    }
    assert "/api/project/{project_id}/programmatic-review/{candidate_id}" in paths
    assert "/api/project/{project_id}/programmatic-review/{candidate_id}/media" in paths
    assert "/api/project/{project_id}/programmatic-review/{candidate_id}/apply" not in paths
    with TestClient(app) as client:
        page = client.get("/p/review-demo/agent-review")
        assert page.status_code == 200
        assert "agent-review.js" in page.text
        assert client.get(_base(setup) + "/demo_r2").status_code == 200
