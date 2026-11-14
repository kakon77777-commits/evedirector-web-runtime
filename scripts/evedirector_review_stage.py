#!/usr/bin/env python3
"""EveDirector R2 candidate-only L4 staging and replay verifier.

The review package stores copies of R0 source/plan/style, R1 props/receipt,
and optionally a locally rendered MP4. No L3/L5 Apply, publishing, network
fetch, or canonical video_spec mutation. The browser/API must re-verify it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_remotion_bridge as bridge

REVIEW_SCHEMA = "evedirector.programmatic_review.v0.1"
ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
VIDEO_LIMIT_BYTES = 128 * 1024 * 1024
STYLE_LIMIT_BYTES = 512_000
PACKAGE_DIR = "programmatic_candidates"


class ReviewPackageError(ValueError):
    pass


def checked_id(value: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ReviewPackageError("invalid project/candidate id")
    return value


def canonical(value: Any) -> bytes:
    return bridge.r0._canonical_json(value)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_plain_dir(path: Path, root: Path | None = None) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ReviewPackageError("review directory is missing or a symlink")
    resolved = path.resolve()
    if root is not None:
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise ReviewPackageError("review directory escapes project") from exc
    return path


def _file_under(directory: Path, relative: str, max_size: int) -> Path:
    path = directory / relative
    if path.is_symlink() or not path.is_file():
        raise ReviewPackageError("required review artifact is missing or unsafe")
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError as exc:
        raise ReviewPackageError("review artifact escapes its directory") from exc
    if path.stat().st_size > max_size:
        raise ReviewPackageError("review artifact exceeds size limit")
    return path


def _video_probe(path: Path, props: dict[str, Any]) -> dict[str, Any]:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-count_frames",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_read_frames",
            "-of", "json", str(path),
        ], capture_output=True, text=True, timeout=30, check=False)
        if result.returncode != 0:
            raise ReviewPackageError("ffprobe rejected candidate preview")
        streams = json.loads(result.stdout).get("streams", [])
        if len(streams) != 1:
            raise ReviewPackageError("candidate preview video stream missing")
        stream = streams[0]
        b = props["bundle"]
        if (stream.get("codec_name") != "h264" or
            stream.get("width") != b["width"] or
            stream.get("height") != b["height"] or
            stream.get("r_frame_rate") != f'{b["fps"]}/1' or
            stream.get("nb_read_frames") != str(b["durationInFrames"])):
            raise ReviewPackageError("candidate preview dimensions/fps/frames mismatch")
        return {
            "codec": "h264", "width": b["width"], "height": b["height"],
            "fps": b["fps"], "frames": b["durationInFrames"],
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReviewPackageError("ffprobe unavailable or malformed candidate preview") from exc


def _copy_bounded_video(source: Path, target: Path) -> tuple[str, int]:
    if source.is_symlink() or source.suffix.lower() != ".mp4" or not source.is_file():
        raise ReviewPackageError("candidate preview must be a regular local MP4")
    size = source.stat().st_size
    if size < 1 or size > VIDEO_LIMIT_BYTES:
        raise ReviewPackageError("candidate MP4 size out of range")
    h = hashlib.sha256()
    count = 0
    with source.open("rb") as inp, target.open("xb") as out:
        while True:
            chunk = inp.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > VIDEO_LIMIT_BYTES:
                raise ReviewPackageError("candidate MP4 exceeds size limit during copy")
            out.write(chunk)
            h.update(chunk)
    return h.hexdigest(), count


def _ensure_project(projects_dir: Path, project_id: str) -> Path:
    checked_id(project_id)
    _require_plain_dir(projects_dir)
    project_dir = projects_dir / project_id
    _require_plain_dir(project_dir, projects_dir)
    return project_dir


def stage(projects_dir: Path, project_id: str, candidate_id: str,
          plan_path: Path, source_path: Path, styles_dir: Path,
          video_path: Path | None = None) -> dict[str, Any]:
    checked_id(candidate_id)
    project_dir = _ensure_project(projects_dir, project_id)
    plan = bridge.read_strict_json(plan_path)
    source = bridge.read_source(source_path)
    props = bridge.build_props(plan, source, styles_dir)
    receipt = bridge.build_receipt(props)
    style = plan["style"]
    style_file = styles_dir / f"{style}.yaml"  # R0 validated slug+local path
    style_bytes = _file_under(styles_dir, f"{style}.yaml", STYLE_LIMIT_BYTES).read_bytes()
    if digest(style_bytes) != receipt["style_sha256"]:
        raise ReviewPackageError("style changed since R1 validation")
    root = project_dir / PACKAGE_DIR
    if not root.exists():
        root.mkdir()
    _require_plain_dir(root, project_dir)
    target = root / candidate_id
    if target.exists() or target.is_symlink():
        raise ReviewPackageError("candidate already exists (append-only; choose new id)")
    staging = Path(tempfile.mkdtemp(prefix=".staging-r2-", dir=root))
    try:
        (staging / "styles").mkdir()
        (staging / "plan.json").write_bytes(plan_path.read_bytes())
        (staging / "source.md").write_bytes(source)
        (staging / "styles" / f"{style}.yaml").write_bytes(style_bytes)
        (staging / "props.json").write_bytes(canonical(props))
        (staging / "receipt.json").write_bytes(canonical(receipt))
        video: dict[str, Any] | None = None
        if video_path is not None:
            sha, size = _copy_bounded_video(video_path, staging / "preview.mp4")
            probe = _video_probe(staging / "preview.mp4", props)
            video = {**probe, "sha256": sha, "bytes": size}
        manifest = {
            "schema": REVIEW_SCHEMA,
            "candidate_id": candidate_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "candidate_only": True,
            "review_required": True,
            "source_sha256": receipt["source_sha256"],
            "program_sha256": receipt["program_sha256"],
            "style_sha256": receipt["style_sha256"],
            "props_sha256": receipt["props_sha256"],
            "receipt_sha256": digest(canonical(receipt)),
            "video": video,
        }
        (staging / "manifest.json").write_bytes(canonical(manifest))
        # Replay against the staged copies, before making the package visible.
        load_package_dir(staging, candidate_id)
        if target.exists() or target.is_symlink():
            raise ReviewPackageError("candidate destination changed during staging")
        staging.rename(target)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_package_dir(folder: Path, candidate_id: str) -> dict[str, Any]:
    checked_id(candidate_id)
    _require_plain_dir(folder)
    manifest = bridge.read_strict_json(_file_under(folder, "manifest.json", 100_000), 100_000)
    required = {
        "schema", "candidate_id", "created_at", "candidate_only", "review_required",
        "source_sha256", "program_sha256", "style_sha256", "props_sha256",
        "receipt_sha256", "video",
    }
    if (set(manifest) != required or manifest.get("schema") != REVIEW_SCHEMA or
        manifest.get("candidate_id") != candidate_id or
        manifest.get("candidate_only") is not True or
        manifest.get("review_required") is not True or
        not isinstance(manifest.get("created_at"), str) or len(manifest["created_at"]) > 64):
        raise ReviewPackageError("invalid programmatic review manifest")
    for k in ("source_sha256", "program_sha256", "style_sha256", "props_sha256", "receipt_sha256"):
        if not isinstance(manifest[k], str) or not SHA.fullmatch(manifest[k]):
            raise ReviewPackageError("invalid review hash")
    plan = bridge.read_strict_json(_file_under(folder, "plan.json", bridge.MAX_PLAN_BYTES))
    source = bridge.read_source(_file_under(folder, "source.md", bridge.MAX_SOURCE_BYTES))
    props = bridge.read_strict_json(_file_under(folder, "props.json", bridge.MAX_PROPS_BYTES), bridge.MAX_PROPS_BYTES)
    receipt = bridge.read_strict_json(_file_under(folder, "receipt.json", bridge.MAX_RECEIPT_BYTES), bridge.MAX_RECEIPT_BYTES)
    style = plan.get("style")
    if not isinstance(style, str) or not ID.fullmatch(style):
        raise ReviewPackageError("unsafe review style slug")
    _require_plain_dir(folder / "styles", folder)
    _file_under(folder, f"styles/{style}.yaml", STYLE_LIMIT_BYTES)
    bridge.verify(props, plan, source, folder / "styles", receipt)
    for key, expected in (
        ("source_sha256", digest(source)),
        ("program_sha256", props["bundle"]["program_sha256"]),
        ("style_sha256", props["bundle"]["style_sha256"]),
        ("props_sha256", receipt["props_sha256"]),
        ("receipt_sha256", digest(canonical(receipt))),
    ):
        if manifest[key] != expected:
            raise ReviewPackageError("review manifest digest mismatch")
    video_path: Path | None = None
    video = manifest["video"]
    if video is not None:
        if not isinstance(video, dict) or set(video) != {
            "codec", "width", "height", "fps", "frames", "sha256", "bytes",
        }:
            raise ReviewPackageError("invalid preview metadata")
        bundle = props["bundle"]
        if (video["codec"] != "h264" or video["width"] != bundle["width"] or
            video["height"] != bundle["height"] or video["fps"] != bundle["fps"] or
            video["frames"] != bundle["durationInFrames"] or
            not isinstance(video["sha256"], str) or not SHA.fullmatch(video["sha256"]) or
            type(video["bytes"]) is not int or not 1 <= video["bytes"] <= VIDEO_LIMIT_BYTES):
            raise ReviewPackageError("preview metadata does not match scene program")
        video_path = _file_under(folder, "preview.mp4", VIDEO_LIMIT_BYTES)
        if video_path.stat().st_size != video["bytes"]:
            raise ReviewPackageError("preview byte count mismatch")
        h = hashlib.sha256()
        with video_path.open("rb") as inp:
            for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != video["sha256"]:
            raise ReviewPackageError("preview digest mismatch")
    elif (folder / "preview.mp4").exists():
        raise ReviewPackageError("unexpected preview without manifest evidence")
    return {"manifest": manifest, "props": props, "receipt": receipt,
            "source_lines": source.decode("utf-8").splitlines(), "video_path": video_path}


def load_package(projects_dir: Path, project_id: str, candidate_id: str) -> dict[str, Any]:
    checked_id(candidate_id)
    project_dir = _ensure_project(projects_dir, project_id)
    root = project_dir / PACKAGE_DIR
    if not root.exists():
        raise FileNotFoundError("no programmatic candidates")
    _require_plain_dir(root, project_dir)
    folder = root / candidate_id
    if not folder.exists():
        raise FileNotFoundError("no such candidate")
    _require_plain_dir(folder, root)
    return load_package_dir(folder, candidate_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage a read-only programmatic review candidate")
    parser.add_argument("command", choices=["stage", "verify"])
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--projects-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "projects")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--styles-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "styles")
    parser.add_argument("--video", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "stage":
            if not args.plan or not args.source:
                raise ReviewPackageError("stage requires --plan and --source")
            result = stage(args.projects_dir, args.project_id, args.candidate_id,
                           args.plan, args.source, args.styles_dir, args.video)
        else:
            package = load_package(args.projects_dir, args.project_id, args.candidate_id)
            result = package["manifest"]
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ReviewPackageError, bridge.r0.ProgramError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
