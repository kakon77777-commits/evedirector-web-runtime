"""R4 local L4 projection: not-run/failed, replay tamper, no Apply authority."""
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
import evedirector_text_layers_r4 as text_r4
import backlot.agent_review as l4
import backlot.programmatic_review as review_api
import backlot.server as server


@pytest.fixture
def env(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe unavailable")
    projects_dir = tmp_path / "projects"
    (projects_dir / "r4demo").mkdir(parents=True)
    monkeypatch.setattr(l4, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(server, "PROJECTS_DIR", projects_dir)
    wrong = tmp_path / "black.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=640x360:r=12", "-frames:v", "60",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(wrong),
    ], check=True, timeout=45)
    stage.stage(projects_dir,"r4demo","wrong", ROOT / "examples/native-video/program.json",
                ROOT / "examples/native-video/source/README.md", ROOT / "styles", wrong)
    app=FastAPI()
    app.include_router(review_api.router)
    return {"root":projects_dir,"client":TestClient(app)}


def test_not_run_is_not_pass(env):
    response=env["client"].get("/api/project/r4demo/programmatic-review/wrong")
    assert response.status_code==200
    assert response.json()["text_check"]=={
        "status":"NOT_RUN","unsigned_local_record":True,
        "visual_equivalence_attested":False,"approved_for_publish":False,
    }


def test_failed_text_check_visible_with_no_approval(env):
    item=stage.load_package(env["root"],"r4demo","wrong")
    report=text_r4.inspect(item,"wrong")
    text_r4.store(env["root"],"r4demo","wrong",report)
    response=env["client"].get("/api/project/r4demo/programmatic-review/wrong")
    assert response.status_code==200, response.text
    data=response.json()
    text=data["text_check"]
    assert text["status"]=="FAIL_SAMPLED_TEXT"
    assert text["sampled_frames"]==60
    assert text["declared_text_layers"]==5
    assert text["bad_pixels"]>200
    assert text["approved_for_publish"] is False
    assert data["authority"]["apply_supported"] is False
    assert data["visual_check"]["status"]=="NOT_RUN"
    assert env["client"].get("/api/project/r4demo/programmatic-review/wrong/media").status_code==200


def test_corrupt_text_check_returns_409_without_media_restriction(env):
    item=stage.load_package(env["root"],"r4demo","wrong")
    path=text_r4.store(env["root"],"r4demo","wrong",text_r4.inspect(item,"wrong"))
    path.write_bytes(path.read_bytes()+b"tamper")
    response=env["client"].get("/api/project/r4demo/programmatic-review/wrong")
    assert response.status_code==409
    assert "R4 text check" in response.json()["detail"]
    assert env["client"].get("/api/project/r4demo/programmatic-review/wrong/media").status_code==200


def test_can_never_apply_R4_even_if_L3_enabled(env,monkeypatch):
    monkeypatch.setenv(l4.ACTIONS_ENV,"1")
    root="/api/project/r4demo/programmatic-review/wrong"
    assert env["client"].post(root,json={"confirmation":"APPLY wrong"}).status_code in {404,405}
    assert env["client"].post(root+"/apply",json={"confirmation":"APPLY wrong"}).status_code==404
    paths={r.path for r in server.create_app().routes if hasattr(r,"path")}
    assert "/api/project/{project_id}/programmatic-review/{candidate_id}" in paths
    assert "/api/project/{project_id}/programmatic-review/{candidate_id}/apply" not in paths
