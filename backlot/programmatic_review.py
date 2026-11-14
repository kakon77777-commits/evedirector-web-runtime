"""EveDirector R2 read-only Programmatic Preview channel mounted in L4.

Distinct from L3 agent runs: NO Validate / Apply / Reject endpoints. This router
only exposes verified R0/R1 scene facts and a SHA-pinned MP4 candidate. It never
returns raw prompts, arbitrary files, or an L3 approval identity.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backlot import agent_review as l4
from lib.paths import REPO_ROOT

SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import evedirector_review_stage as stage  # noqa: E402
import evedirector_remotion_bridge as bridge  # noqa: E402

router = APIRouter()
READ_ONLY = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _project(project_id: str) -> Path:
    # Reuse the existing L4 project guard and preserve its 400/404 semantics.
    l4._safe_project_dir(project_id)
    try:
        return stage._ensure_project(l4.PROJECTS_DIR, project_id)
    except stage.ReviewPackageError as exc:
        raise HTTPException(status_code=403, detail="unsafe review project directory") from exc


def _read_package(project_id: str, candidate_id: str) -> dict[str, Any]:
    _project(project_id)
    try:
        return stage.load_package(l4.PROJECTS_DIR, project_id, candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="programmatic candidate not found") from exc
    except (stage.ReviewPackageError, bridge.r0.ProgramError,
            OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=409, detail="programmatic candidate failed integrity check") from exc


def _summary(candidate_id: str, item: dict[str, Any]) -> dict[str, Any]:
    b = item["props"]["bundle"]
    return {
        "candidate_id": candidate_id,
        "status": "source_replayed_preview_only",
        "created_at": item["manifest"]["created_at"],
        "title": b["title"],
        "scene_count": len(b["clips"]),
        "frames": b["durationInFrames"],
        "fps": b["fps"],
        "preview_available": item["video_path"] is not None,
        "candidate_only": True,
        "apply_supported": False,
    }


def _list(project_id: str) -> dict[str, Any]:
    project_dir = _project(project_id)
    root = project_dir / stage.PACKAGE_DIR
    if not root.exists():
        return {"project_id": project_id, "candidates": [],
                "authority": "read-only-no-apply", "actions_supported": False}
    try:
        stage._require_plain_dir(root, project_dir)
    except stage.ReviewPackageError as exc:
        raise HTTPException(status_code=403, detail="unsafe programmatic candidates directory") from exc
    results: list[dict[str, Any]] = []
    # Bounded scan avoids attacker-controlled gigantic directories in UI listing.
    for folder in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        if len(results) >= 100:
            break
        if folder.name.startswith(".") or not stage.ID.fullmatch(folder.name):
            continue
        if not folder.is_dir() and not folder.is_symlink():
            continue
        try:
            item = stage.load_package(l4.PROJECTS_DIR, project_id, folder.name)
            results.append(_summary(folder.name, item))
        except (FileNotFoundError, stage.ReviewPackageError, bridge.r0.ProgramError,
                OSError, ValueError, TypeError, KeyError):
            results.append({"candidate_id": folder.name, "status": "integrity_failed",
                            "preview_available": False, "candidate_only": True,
                            "apply_supported": False})
    results.sort(key=lambda item: str(item.get("created_at") or item["candidate_id"]), reverse=True)
    return {"project_id": project_id, "candidates": results,
            "authority": "read-only-no-apply", "actions_supported": False}


def _detail(project_id: str, candidate_id: str) -> dict[str, Any]:
    item = _read_package(project_id, candidate_id)
    b = item["props"]["bundle"]
    lines = item["source_lines"]
    scenes = []
    for clip in b["clips"]:
        a = clip["source"]
        line = lines[a["line_start"] - 1]
        scenes.append({
            "id": clip["id"],
            "from": clip["from"],
            "durationInFrames": clip["durationInFrames"],
            "start_seconds": clip["from"] / b["fps"],
            "duration_seconds": clip["durationInFrames"] / b["fps"],
            "layers": len(clip["layers"]),
            "source": {
                "line_start": a["line_start"],
                "line_end": a["line_end"],
                "source_contains": a["source_contains"],
                "logical_line_sha256": a["logical_line_sha256"],
                "excerpt": line.strip()[:500],
            },
        })
    media_url = (f"/api/project/{project_id}/programmatic-review/{candidate_id}/media"
                 if item["video_path"] is not None else None)
    return {
        "schema": "evedirector.programmatic_review_api.v0.1",
        "project_id": project_id,
        "candidate_id": candidate_id,
        "title": b["title"],
        "candidate_only": True,
        "review_required": True,
        "authority": {
            "mode": "read_only",
            "apply_supported": False,
            "validate_supported": False,
            "reject_supported": False,
            "canonical_spec_mutated": False,
            "source_approval_verified": False,
            "preview_matches_program_verified": False,
            "source_evidence_scope": b["source_evidence_scope"],
        },
        "timing": {
            "width": b["width"], "height": b["height"], "fps": b["fps"],
            "frames": b["durationInFrames"],
            "seconds": b["durationInFrames"] / b["fps"],
        },
        "digests": {
            "source_sha256": b["source_sha256"],
            "program_sha256": b["program_sha256"],
            "style_sha256": b["style_sha256"],
            "props_sha256": item["receipt"]["props_sha256"],
            "receipt_sha256": item["manifest"]["receipt_sha256"],
        },
        "preview": {
            "available": item["video_path"] is not None,
            "media_url": media_url,
            "integrity": "sha256-matches-staged-file" if media_url else "no-video-staged",
            "visual_equivalence_attested": False,
        },
        "scenes": scenes,
    }


@router.get("/api/project/{project_id}/programmatic-review")
async def programmatic_review_index(project_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_list, project_id)


@router.get("/api/project/{project_id}/programmatic-review/{candidate_id}")
async def programmatic_review_detail(project_id: str, candidate_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_detail, project_id, candidate_id)


@router.get("/api/project/{project_id}/programmatic-review/{candidate_id}/media")
async def programmatic_review_media(project_id: str, candidate_id: str) -> FileResponse:
    item = await asyncio.to_thread(_read_package, project_id, candidate_id)
    video = item["video_path"]
    if video is None:
        raise HTTPException(status_code=404, detail="candidate has no staged video")
    return FileResponse(
        video, media_type="video/mp4", filename=f"{candidate_id}.mp4",
        content_disposition_type="inline", headers=READ_ONLY,
    )
