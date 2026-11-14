#!/usr/bin/env python3
"""EveDirector R3 bounded, offline, sampled visual geometry comparison.

A PASS is limited to sampled flat-color/geometry pixels at selected frames.
Text, transitions, anti-aliased edges, audio, arbitrary effects, truth of the
source, and release permissions are OUT OF SCOPE. Never grants L3/L4 Apply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_review_stage as stage

SCHEMA = "evedirector.sampled_visual_check.v0.1"
METHOD = "flat-color-geometric-probes-v0.1"
REPORT_DIR = "programmatic_visual_checks"
MAX_FRAMES = 32
MAX_FRAME_BYTES = 80 * 1024 * 1024
MAX_PIXELS_PER_FRAME = 3000
MAX_REPORT_BYTES = 512_000
COLOR_TOLERANCE = 20  # maximum RGB-channel deviation per eligible pixel
BAD_PIXEL_FRACTION = 0.04
MAE_CEILING = 8.0
EDGE_MARGIN = 4.0


class VisualProbeError(ValueError):
    pass


def color_rgb(color: str) -> tuple[int, int, int]:
    if len(color) != 7 or color[0] != "#":
        raise VisualProbeError("invalid palette color")
    try:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError as exc:
        raise VisualProbeError("invalid palette color") from exc


def _interpolated(layer: dict[str, Any], key: str, frame: int) -> float:
    """Independent analytic interpreter of piecewise-linear frame-keyed specs."""
    points = layer.get("keyframes", {}).get(key)
    if not points:
        return float(layer.get(key, 1 if key == "opacity" else 0))
    if frame <= points[0]["frame"]:
        return float(points[0]["value"])
    for left, right in zip(points, points[1:]):
        if frame <= right["frame"]:
            t = (frame - left["frame"]) / (right["frame"] - left["frame"])
            return float(left["value"]) * (1 - t) + float(right["value"]) * t
    return float(points[-1]["value"])


def _active_clip(bundle: dict[str, Any], frame: int) -> dict[str, Any]:
    for clip in bundle["clips"]:
        if clip["from"] <= frame < clip["from"] + clip["durationInFrames"]:
            return clip
    raise VisualProbeError("uncovered frame in validated bundle")


def _select_frames(bundle: dict[str, Any]) -> list[int]:
    """Select boundaries, midpoints, and motion events, with hard resource cap."""
    total = bundle["durationInFrames"]
    frame_bytes = bundle["width"] * bundle["height"] * 3
    if frame_bytes <= 0 or frame_bytes > MAX_FRAME_BYTES:
        raise VisualProbeError("frame buffer exceeds bounded visual probe limit")
    limit = min(MAX_FRAMES, MAX_FRAME_BYTES // frame_bytes, total)
    clips = bundle["clips"]
    if limit < len(clips):
        raise VisualProbeError("not enough frame budget to sample all clips")
    mandatory: set[int] = set()
    candidates: set[int] = set()
    for c in clips:
        first = c["from"]
        count = c["durationInFrames"]
        mandatory.add(first + count // 2)
        candidates.update((first, first + count - 1, first + count // 2,
                           first + count // 4, first + (count * 3) // 4))
        for layer in c["layers"]:
            for points in layer.get("keyframes", {}).values():
                for point in points:
                    f = first + point["frame"]
                    candidates.update((max(first, f - 1), f, min(first + count - 1, f + 1)))
    # Global samples prevent concentrating all checks in just one busy clip.
    candidates.update(round(i * (total - 1) / max(1, limit - 1)) for i in range(limit))
    chosen = sorted(mandatory)
    remaining = sorted(candidates - mandatory)
    slots = limit - len(chosen)
    if slots > 0:
        if len(remaining) <= slots:
            chosen.extend(remaining)
        else:
            positions = [int(i * (len(remaining) - 1) / max(1, slots - 1)) for i in range(slots)]
            chosen.extend(remaining[i] for i in positions)
    return sorted(set(chosen))


def _geometry_at(layer: dict[str, Any], frame: int) -> dict[str, float]:
    # Remotion CSS left/top/width/height are rounded via Math.round, not Python banker's round.
    def jsround(v: float) -> int:
        return math.floor(v + .5)
    obj: dict[str, float] = {
        "x": float(jsround(_interpolated(layer, "x", frame))),
        "y": float(jsround(_interpolated(layer, "y", frame))),
        "opacity": _interpolated(layer, "opacity", frame),
    }
    if layer["kind"] != "text":
        obj["w"] = float(jsround(_interpolated(layer, "width", frame)))
        obj["h"] = float(jsround(_interpolated(layer, "height", frame)))
    return obj


def _prediction(bundle: dict[str, Any], clip: dict[str, Any], local: int,
                px: int, py: int) -> tuple[tuple[int, int, int], str] | None:
    """Analytic CSS-interior composition; edge and text zones return None."""
    rgb = [float(c) for c in color_rgb(bundle["palette"]["background"])]
    touched_geometry = False
    for layer in clip["layers"]:
        g = _geometry_at(layer, local)
        if g["opacity"] <= 0.005:
            continue
        x, y = g["x"], g["y"]
        if layer["kind"] == "text":
            # Fonts differ between PIL/Chromium/OS; generously exclude any likely
            # glyph/wrap box from comparison. This verifier NEVER tests text.
            font_size = layer["font_size"]
            lines = layer["text"].split("\n")
            total_width = max((len(line) for line in lines), default=1) * font_size * 1.45
            # Browser auto-sized absolute text may wrap on the right edge.
            available = max(1.0, bundle["width"] - max(0, x))
            wraps = max(1, math.ceil(total_width / available))
            height = font_size * 1.55 * max(len(lines), wraps)
            if (x - 12 <= px <= min(bundle["width"], x + max(total_width, available) + 12)
                    and y - 14 <= py <= y + height + 16):
                return None
            continue
        w, h = g["w"], g["h"]
        if w < 1 or h < 1:
            continue
        dx = px + .5 - x
        dy = py + .5 - y
        if layer["kind"] == "rect":
            if (-EDGE_MARGIN <= dx <= w + EDGE_MARGIN and
                    -EDGE_MARGIN <= dy <= h + EDGE_MARGIN and
                    (min(abs(dx), abs(dx - w), abs(dy), abs(dy - h)) <= EDGE_MARGIN)):
                return None
            inside = 0 <= dx < w and 0 <= dy < h
        else:
            nx = (dx - w / 2) / (w / 2)
            ny = (dy - h / 2) / (h / 2)
            radius = math.sqrt(nx * nx + ny * ny)
            if abs(radius - 1) * min(w, h) / 2 < EDGE_MARGIN:
                return None
            inside = radius < 1
        if inside:
            c = layer["fill"]
            raw = color_rgb(c if c.startswith("#") else bundle["palette"][c])
            alpha = g["opacity"]
            rgb = [(1-alpha)*bg + alpha*fg for bg,fg in zip(rgb,raw)]
            touched_geometry = True
    return tuple(int(round(c)) for c in rgb), ("geometry" if touched_geometry else "background")


def _coordinates(bundle: dict[str, Any], clip: dict[str, Any], local: int) -> list[tuple[int, int]]:
    w, h = bundle["width"], bundle["height"]
    stride = max(6, math.ceil(math.sqrt(w * h / 1650)))
    pts: set[tuple[int, int]] = {(x,y) for y in range(stride // 2, h, stride)
                                 for x in range(stride // 2, w, stride)}
    # Also probe thin/moving shapes even if the screen-wide grid misses them.
    for layer in clip["layers"]:
        if layer["kind"] == "text":
            continue
        g = _geometry_at(layer, local)
        if g["opacity"] <= 0.01:
            continue
        for xf in (0.2, 0.5, 0.8):
            for yf in (0.2, 0.5, 0.8):
                x = math.floor(g["x"] + xf * g["w"])
                y = math.floor(g["y"] + yf * g["h"])
                if 0 <= x < w and 0 <= y < h:
                    pts.add((x, y))
    pts = sorted(pts, key=lambda q: (q[1], q[0]))
    if len(pts) > MAX_PIXELS_PER_FRAME:
        # Uniform deterministic coverage including geometry-specific points.
        pts = [pts[i * (len(pts) - 1) // (MAX_PIXELS_PER_FRAME - 1)]
               for i in range(MAX_PIXELS_PER_FRAME)]
    return pts


def _decode_frames(path: Path, frames: list[int], width: int, height: int) -> list[bytes]:
    if not frames:
        raise VisualProbeError("no frames selected")
    if len(frames) * width * height * 3 > MAX_FRAME_BYTES:
        raise VisualProbeError("visual frame decode memory budget exceeded")
    selector = "+".join(f"eq(n\\,{n})" for n in frames)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0",
           "-vf", f"select={selector}", "-vsync", "0", "-an", "-sn", "-dn",
           "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    try:
        process = subprocess.run(cmd, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VisualProbeError("bounded FFmpeg frame decode failed") from exc
    size = width * height * 3
    if process.returncode != 0 or len(process.stdout) != len(frames) * size:
        raise VisualProbeError("decoded frame count or byte length mismatch")
    return [process.stdout[i*size:(i+1)*size] for i in range(len(frames))]


def inspect(item: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    """Return deterministic report pinned to the R2 candidate's hashes."""
    if item["video_path"] is None:
        raise VisualProbeError("candidate has no verified MP4")
    bundle = item["props"]["bundle"]
    width, height = bundle["width"], bundle["height"]
    frames = _select_frames(bundle)
    decoded = _decode_frames(item["video_path"], frames, width, height)
    results: list[dict[str, Any]] = []
    total_pixels = total_geo = total_bad = 0
    weighted_mae = 0.0
    inconclusive = False
    for frame, pixels in zip(frames, decoded):
        clip = _active_clip(bundle, frame)
        local = frame - clip["from"]
        matched = geo = bad = 0
        errors_sum = 0
        for x, y in _coordinates(bundle, clip, local):
            expected = _prediction(bundle, clip, local, x, y)
            if expected is None:
                continue
            rgb, category = expected
            pos = (y * width + x) * 3
            measured = pixels[pos:pos+3]
            errors = [abs(int(measured[i]) - rgb[i]) for i in range(3)]
            matched += 1
            if category == "geometry":
                geo += 1
            if max(errors) > COLOR_TOLERANCE:
                bad += 1
            errors_sum += sum(errors)
        mae = errors_sum / (3 * matched) if matched else 255.0
        fraction = bad / matched if matched else 1.0
        status = "PASS" if matched >= 64 and fraction <= BAD_PIXEL_FRACTION and mae <= MAE_CEILING else "FAIL"
        if matched < 64:
            status = "INCONCLUSIVE"
            inconclusive = True
        results.append({"frame": frame, "clip_id": clip["id"], "eligible_pixels": matched,
                        "geometry_pixels": geo, "outlier_pixels": bad,
                        "bad_pixel_fraction": round(fraction, 6),
                        "mean_channel_absolute_error": round(mae, 5), "status": status})
        total_pixels += matched
        total_geo += geo
        total_bad += bad
        weighted_mae += errors_sum
    if total_geo < 25 or not results:
        inconclusive = True
    statuses = {x["status"] for x in results}
    if "FAIL" in statuses:
        status = "FAIL_SAMPLED_GEOMETRY"
    elif inconclusive or "INCONCLUSIVE" in statuses:
        status = "INCONCLUSIVE_SAMPLED_GEOMETRY"
    else:
        status = "PASS_SAMPLED_GEOMETRY"
    manifest = item["manifest"]
    return {
        "schema": SCHEMA,
        "method": METHOD,
        "candidate_id": candidate_id,
        "status": status,
        "candidate_only": True,
        "approved_for_publish": False,
        "visual_equivalence_attested": False,
        "coverage": "selected-frames-flat-geometry-interiors-only",
        "excluded": ["text-glyphs", "anti-aliased-edges", "audio", "external-source-truth", "publishing-rights"],
        "thresholds": {"channel_tolerance": COLOR_TOLERANCE,
                       "bad_pixel_fraction": BAD_PIXEL_FRACTION, "mean_channel_error": MAE_CEILING},
        "pins": {"source_sha256": manifest["source_sha256"],
                 "program_sha256": manifest["program_sha256"],
                 "props_sha256": manifest["props_sha256"],
                 "video_sha256": manifest["video"]["sha256"]},
        "sampled_frames": frames,
        "total_frames": bundle["durationInFrames"],
        "eligible_pixels": total_pixels,
        "geometry_pixels": total_geo,
        "outlier_pixels": total_bad,
        "bad_pixel_fraction": round(total_bad / total_pixels, 6) if total_pixels else 1.0,
        "mean_channel_absolute_error": round(weighted_mae / (3*total_pixels), 5) if total_pixels else 255.0,
        "frames": results,
    }


def _record_root(projects_dir: Path, project_id: str, candidate_id: str) -> Path:
    project = stage._ensure_project(projects_dir, project_id)
    stage.checked_id(candidate_id)
    return project / REPORT_DIR / candidate_id


def store(projects_dir: Path, project_id: str, candidate_id: str, report: dict[str, Any]) -> Path:
    """One immutable content-addressed report per candidate; existing files never overwritten."""
    root = _record_root(projects_dir, project_id, candidate_id)
    if root.exists() or root.is_symlink():
        raise VisualProbeError("visual report already staged for candidate; use a new candidate id")
    root.parent.mkdir(exist_ok=True)
    stage._require_plain_dir(root.parent, root.parent.parent)
    root.mkdir(exist_ok=False)
    content = stage.canonical(report)
    checksum = stage.digest(content)
    target = root / (checksum + ".json")
    with target.open("xb") as dst:
        dst.write(content)
    return target


def load_report(projects_dir: Path, project_id: str, candidate_id: str,
                item: dict[str, Any]) -> dict[str, Any] | None:
    """Safe read of unsigned local measurement; report is NOT authority."""
    directory = _record_root(projects_dir, project_id, candidate_id)
    if not directory.parent.exists():
        return None
    project = stage._ensure_project(projects_dir, project_id)
    stage._require_plain_dir(directory.parent, project)
    if not directory.exists():
        return None
    stage._require_plain_dir(directory, directory.parent)
    paths = list(directory.iterdir())
    if len(paths) != 1:
        raise VisualProbeError("ambiguous visual report directory")
    path = paths[0]
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES
            or not path.name.endswith(".json") or len(path.stem) != 64
            or not stage.SHA.fullmatch(path.stem)):
        raise VisualProbeError("invalid visual report file")
    content = path.read_bytes()
    if stage.digest(content) != path.stem:
        raise VisualProbeError("visual report content hash mismatch")
    report = stage.bridge.read_strict_json(path, MAX_REPORT_BYTES)
    manifest = item["manifest"]
    pins = {"source_sha256": manifest["source_sha256"],
            "program_sha256": manifest["program_sha256"],
            "props_sha256": manifest["props_sha256"],
            "video_sha256": manifest["video"]["sha256"] if manifest["video"] else None}
    if (report.get("schema") != SCHEMA or report.get("method") != METHOD
            or report.get("candidate_id") != candidate_id
            or report.get("pins") != pins
            or report.get("status") not in {
                "PASS_SAMPLED_GEOMETRY", "FAIL_SAMPLED_GEOMETRY", "INCONCLUSIVE_SAMPLED_GEOMETRY"
            } or report.get("candidate_only") is not True
            or report.get("approved_for_publish") is not False
            or report.get("visual_equivalence_attested") is not False
            or not isinstance(report.get("frames"), list)
            or not isinstance(report.get("sampled_frames"), list)
            or report.get("total_frames") != item["props"]["bundle"]["durationInFrames"]):
        raise VisualProbeError("visual report schema/pins/authority mismatch")
    if set(report) != {
        "schema", "method", "candidate_id", "status", "candidate_only",
        "approved_for_publish", "visual_equivalence_attested", "coverage",
        "excluded", "thresholds", "pins", "sampled_frames", "total_frames",
        "eligible_pixels", "geometry_pixels", "outlier_pixels",
        "bad_pixel_fraction", "mean_channel_absolute_error", "frames",
    }:
        raise VisualProbeError("unexpected report schema fields")
    if (report["coverage"] != "selected-frames-flat-geometry-interiors-only"
            or report["thresholds"] != {
                "channel_tolerance": COLOR_TOLERANCE,
                "bad_pixel_fraction": BAD_PIXEL_FRACTION,
                "mean_channel_error": MAE_CEILING,
            }
            or report["excluded"] != [
                "text-glyphs", "anti-aliased-edges", "audio",
                "external-source-truth", "publishing-rights",
            ]
            or report["sampled_frames"] != _select_frames(item["props"]["bundle"])):
        raise VisualProbeError("report coverage or measurement method mismatch")
    frames = report["frames"]
    if len(frames) != len(report["sampled_frames"]):
        raise VisualProbeError("per-frame results mismatch")
    totals = [0, 0, 0]
    statuses = set()
    for frame_index, f in zip(report["sampled_frames"], frames):
        if not isinstance(f, dict) or set(f) != {
            "frame", "clip_id", "eligible_pixels", "geometry_pixels", "outlier_pixels",
            "bad_pixel_fraction", "mean_channel_absolute_error", "status",
        }:
            raise VisualProbeError("invalid per-frame metrics")
        if (type(f["frame"]) is not int or f["frame"] != frame_index or
                f["clip_id"] != _active_clip(item["props"]["bundle"], frame_index)["id"] or
                any(type(f[key]) is not int or f[key] < 0 for key in (
                    "eligible_pixels", "geometry_pixels", "outlier_pixels")) or
                f["geometry_pixels"] > f["eligible_pixels"] or
                f["outlier_pixels"] > f["eligible_pixels"] or
                f["status"] not in {"PASS", "FAIL", "INCONCLUSIVE"}):
            raise VisualProbeError("inconsistent per-frame metric values")
        for j, key in enumerate(("eligible_pixels", "geometry_pixels", "outlier_pixels")):
            totals[j] += f[key]
        statuses.add(f["status"])
        failure_ratio = f["outlier_pixels"] / f["eligible_pixels"] if f["eligible_pixels"] else 1.0
        if (not isinstance(f["bad_pixel_fraction"], (int, float)) or
                abs(f["bad_pixel_fraction"] - failure_ratio) > 0.000002 or
                not isinstance(f["mean_channel_absolute_error"], (int, float)) or
                not math.isfinite(f["mean_channel_absolute_error"]) or
                f["mean_channel_absolute_error"] < 0 or f["mean_channel_absolute_error"] > 255):
            raise VisualProbeError("invalid per-frame error")
        expected_status = (
            "INCONCLUSIVE" if f["eligible_pixels"] < 64 else
            "PASS" if failure_ratio <= BAD_PIXEL_FRACTION and
                      f["mean_channel_absolute_error"] <= MAE_CEILING else "FAIL"
        )
        if f["status"] != expected_status:
            raise VisualProbeError("per-frame status inconsistent with metrics")
    if (totals != [report["eligible_pixels"], report["geometry_pixels"], report["outlier_pixels"]] or
            not isinstance(report["bad_pixel_fraction"], (int, float)) or
            abs(report["bad_pixel_fraction"] - (totals[2] / totals[0] if totals[0] else 1.0)) > 0.000002 or
            not isinstance(report["mean_channel_absolute_error"], (int, float)) or
            not math.isfinite(report["mean_channel_absolute_error"]) or
            report["mean_channel_absolute_error"] < 0 or report["mean_channel_absolute_error"] > 255):
        raise VisualProbeError("report totals inconsistent with per-frame results")
    expected_status = (
        "FAIL_SAMPLED_GEOMETRY" if "FAIL" in statuses else
        "INCONCLUSIVE_SAMPLED_GEOMETRY" if totals[1] < 25 or "INCONCLUSIVE" in statuses else
        "PASS_SAMPLED_GEOMETRY"
    )
    if report["status"] != expected_status:
        raise VisualProbeError("report result inconsistent with per-frame metrics")
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EveDirector R3 offline sampled geometry verifier")
    p.add_argument("command", choices=["check", "verify"])
    p.add_argument("--projects-dir", type=Path, default=Path(__file__).resolve().parents[1] / "projects")
    p.add_argument("--project-id", required=True)
    p.add_argument("--candidate-id", required=True)
    args = p.parse_args(argv)
    try:
        item = stage.load_package(args.projects_dir, args.project_id, args.candidate_id)
        report = inspect(item, args.candidate_id)
        if args.command == "check":
            path = store(args.projects_dir, args.project_id, args.candidate_id, report)
            print("REPORT:", path)
        else:
            old = load_report(args.projects_dir, args.project_id, args.candidate_id, item)
            if old is None or stage.canonical(old) != stage.canonical(report):
                raise VisualProbeError("stored report differs from fresh video re-evaluation")
        print(json.dumps({"status": report["status"], "frames": len(report["sampled_frames"]),
                          "eligible_pixels": report["eligible_pixels"],
                          "geometry_pixels": report["geometry_pixels"]}, ensure_ascii=False))
        # A failed comparison is not success, even if report is recorded.
        return 0 if report["status"] == "PASS_SAMPLED_GEOMETRY" else 3
    except (stage.ReviewPackageError, stage.bridge.r0.ProgramError, VisualProbeError,
            OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())