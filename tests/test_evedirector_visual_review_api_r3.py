"""R3 read-only L4 projection: NOT_RUN, FAIL, corrupt report and no Apply."""
from __future__ import annotations
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
import evedirector_visual_probe as visual
import backlot.agent_review as l4
import backlot.programmatic_review as review_r2
import backlot.server as server


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    (root / "r3demo").mkdir(parents=True)
    monkeypatch.setattr(l4, "PROJECTS_DIR", root)
    monkeypatch.setattr(server, "PROJECTS_DIR", root)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("local ffmpeg/ffprobe required")
    video = tmp_path / "wrong.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=640x360:r=12", "-frames:v", "60",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ], check=True, timeout=30)
    stage.stage(root, "r3demo", "wrong",
                ROOT / "examples/native-video/program.json",
                ROOT / "examples/native-video/source/README.md", ROOT / "styles", video)
    app = FastAPI()
    app.include_router(review_r2.router)
    return {"root": root, "client": TestClient(app)}


def test_not_run_is_not_pass(env):
    response = env["client"].get("/api/project/r3demo/programmatic-review/wrong")
    assert response.status_code == 200
    assert response.json()["visual_check"] == {
        "status": "NOT_RUN", "unsigned_local_record": True,
        "visual_equivalence_attested": False, "approved_for_publish": False,
    }


def test_visual_failure_is_visible_without_approval(env):
    item = stage.load_package(env["root"], "r3demo", "wrong")
    visual.store(env["root"], "r3demo", "wrong", visual.inspect(item, "wrong"))
    response = env["client"].get("/api/project/r3demo/programmatic-review/wrong")
    assert response.status_code == 200
    data = response.json()
    v = data["visual_check"]
    assert v["status"] == "FAIL_SAMPLED_GEOMETRY"
    assert v["sampled_frames"] == 32 and v["total_frames"] == 60
    assert v["geometry_pixels"] > 100 and len(v["frame_checks"]) == 32
    assert v["unsigned_local_record"] is True
    assert v["visual_equivalence_attested"] is False
    assert v["approved_for_publish"] is False
    assert data["authority"]["apply_supported"] is False
    assert data["preview"]["visual_equivalence_attested"] is False
    assert env["client"].get("/api/project/r3demo/programmatic-review/wrong/media").status_code == 200


def test_corrupt_report_blocks_visual_detail(env):
    item = stage.load_package(env["root"], "r3demo", "wrong")
    report = visual.store(env["root"], "r3demo", "wrong", visual.inspect(item, "wrong"))
    report.write_bytes(report.read_bytes() + b"TAMPER")
    response = env["client"].get("/api/project/r3demo/programmatic-review/wrong")
    assert response.status_code == 409
    assert "visual check record failed integrity" in response.json()["detail"]
    # Original R2 source/media gate is separate from unsigned R3 status.
    assert env["client"].get("/api/project/r3demo/programmatic-review/wrong/media").status_code == 200


def test_no_apply_even_with_l3_env_enabled(env, monkeypatch):
    monkeypatch.setenv(l4.ACTIONS_ENV, "1")
    url = "/api/project/r3demo/programmatic-review/wrong"
    assert env["client"].post(url, json={"confirmation": "APPLY wrong"}).status_code in {404, 405}
    assert env["client"].post(url + "/apply",
                              json={"confirmation": "APPLY wrong"}).status_code == 404


def test_real_backlot_app_routes_unchanged(env):
    app = server.create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/project/{project_id}/programmatic-review/{candidate_id}" in paths
    assert "/api/project/{project_id}/programmatic-review/{candidate_id}/apply" not in paths
    with TestClient(app) as c:
        response = c.get("/api/project/r3demo/programmatic-review/wrong")
        assert response.status_code == 200
        assert response.json()["visual_check"]["status"] == "NOT_RUN"
