#!/usr/bin/env python3
"""R4 local-only text stroke and later-layer occlusion probe for R0/R1 clips.

This is a bounded, renderer-independent approximation of DejaVu Sans ASCII
text. A PASS certifies sampled high-contrast strokes/negative-space and
selected fully-opaque foreground occlusions, not OCR, exact words,
CJK fonts, typography identity, all pixels or publication readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_review_stage as stage
import evedirector_visual_probe as r3

SCHEMA = "evedirector.text_layer_probe.v0.1"
METHOD = "dejavu-ascii-stroke-and-occlusion-v0.1"
RECORD_DIR = "programmatic_text_checks"
MAX_REPORT_BYTES = 500_000
MAX_FRAME_MEMORY = 60 * 1024 * 1024
MAX_SAMPLE_FRAMES = 60
MAX_POINTS_PER_LAYER_FRAME = 750
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PIXEL_OUTLIER_FRACTION = 0.29
FRAME_OUTLIER_FRACTION = 0.32
MIN_VISIBLE_INK = 12
MIN_TOTAL_VISIBLE_INK = 100
MAX_OCCLUSION_ERROR = 0.27

class TextProbeError(ValueError):
    pass


def _frame_set(bundle: dict[str, Any]) -> list[int]:
    width = bundle["width"]
    height = bundle["height"]
    total = bundle["durationInFrames"]
    size = width * height * 3
    if size <= 0 or size > MAX_FRAME_MEMORY:
        raise TextProbeError("single frame exceeds bounded memory")
    limit = min(total, MAX_SAMPLE_FRAMES, MAX_FRAME_MEMORY // size)
    if limit < len(bundle["clips"]):
        raise TextProbeError("frame budget cannot cover all clips")
    if limit == total:
        return list(range(total))
    candidates = set(r3._select_frames(bundle))
    for clip in bundle["clips"]:
        candidates.add(clip["from"] + clip["durationInFrames"] // 2)
    if len(candidates) > limit:
        # Deterministic, ordered decimation; candidates are hints not evidence.
        ordered = sorted(candidates)
        candidates = {ordered[(len(ordered)-1)*i//max(1,limit-1)] for i in range(limit)}
    if len(candidates) < limit:
        candidates.update(round((total - 1) * i / max(1, limit-1)) for i in range(limit))
    return sorted(candidates)[:limit]


def _rgb(color: str, palette: dict[str, str]) -> tuple[int, int, int]:
    return r3.color_rgb(color if color.startswith("#") else palette[color])


def _shape_cover(layer: dict[str, Any], local: int, x: int, y: int) -> tuple[bool, bool]:
    """Return (inside, near_antialiased_edge) for a geometry layer."""
    g = r3._geometry_at(layer, local)
    dx, dy = x + 0.5 - g["x"], y + 0.5 - g["y"]
    w, h = g["w"], g["h"]
    if w <= 0 or h <= 0:
        return False, False
    if layer["kind"] == "rect":
        inside = 0 <= dx < w and 0 <= dy < h
        near = inside and min(dx, dy, w-dx, h-dy) < 2
        return inside, near
    nx, ny = (dx - w/2) / (w/2), (dy - h/2) / (h/2)
    r = math.hypot(nx, ny)
    return r < 1, abs(r - 1) * min(w, h)/2 < 3


def _geometry_color(bundle: dict[str, Any], layers: list[dict], local: int,
                    x: int, y: int, *, start: int = 0, stop: int | None = None,
                    initial: tuple[float, float, float] | None = None) -> tuple[tuple[float, float, float], bool]:
    palette = bundle["palette"]
    rgb = tuple(map(float, _rgb("background", palette))) if initial is None else initial
    edge = False
    for layer in layers[start:stop]:
        if layer["kind"] == "text":
            continue
        inside, near = _shape_cover(layer, local, x, y)
        edge |= near
        if inside:
            alpha = r3._geometry_at(layer, local)["opacity"]
            col = _rgb(layer["fill"], palette)
            rgb = tuple((1-alpha) * old + alpha * new for old, new in zip(rgb, col))
    return rgb, edge


def _supports_layer(layer: dict[str, Any], bundle: dict[str, Any], local: int, font: str) -> tuple[bool, str]:
    value = layer["text"]
    if not value.isascii() or "\n" in value or "\r" in value or "\t" in value:
        return False, "non-ascii-or-multiline-text-not-modeled"
    if not value.strip():
        return False, "blank-text-no-glyph-evidence"
    g = r3._geometry_at(layer, local)
    if g["opacity"] < 0.25:
        return False, "inactive-or-too-transparent"
    if g["x"] >= bundle["width"] or g["y"] >= bundle["height"]:
        return False, "fully-outside-canvas"
    if g["x"] < -100 or g["y"] < -100:
        return False, "text-outside-supported-canvas"
    try:
        face = ImageFont.truetype(font, layer["font_size"])
        text_width = face.getlength(value)
    except (OSError, ValueError) as exc:
        return False, "font-unavailable"
    if g["x"] + text_width > bundle["width"] - 1:
        return False, "text-wrap-or-right-clip-not-modeled"
    return True, ""


def _render_mask(layer: dict[str, Any], local: int, font: str) -> tuple[Image.Image, int, int]:
    face = ImageFont.truetype(font, layer["font_size"])
    bounds = face.getbbox(layer["text"])
    if bounds is None:
        raise TextProbeError("text has empty glyph bbox")
    # Extra margin accommodates browser glyph antialias differences.
    x0 = min(0,bounds[0]) - 3
    y0 = min(0,bounds[1]) - 3
    width = min(1024, max(1, bounds[2] - x0 + 4))
    height = min(220, max(1, bounds[3] - y0 + 4))
    if width >= 1024 or height >= 220:
        raise TextProbeError("unsupported oversized text mask")
    img = Image.new("L", (width, height))
    draw = ImageDraw.Draw(img)
    draw.text((-x0, -y0), layer["text"], font=face, fill=255)
    g = r3._geometry_at(layer, local)
    return img, int(g["x"] + x0), int(g["y"] + y0)


def _collect_candidates(mask: Image.Image, ox: int, oy: int, width: int, height: int) -> list[tuple[int, int, int]]:
    raw = mask.load()
    out: list[tuple[int, int, int]] = []
    for my in range(mask.height):
        y = oy + my
        if not 1 <= y < height - 1:
            continue
        for mx in range(mask.width):
            x = ox + mx
            if not 1 <= x < width - 1:
                continue
            v = int(raw[mx, my])
            if v >= 225 or v <= 10:
                out.append((x, y, 1 if v >= 225 else 0))
    if len(out) > MAX_POINTS_PER_LAYER_FRAME:
        # Keep both expected ink and negative-space, avoiding background domination.
        ink = [p for p in out if p[2] == 1]
        blank = [p for p in out if p[2] == 0]
        def sample(seq: list[tuple[int,int,int]], budget: int) -> list[tuple[int,int,int]]:
            if len(seq) <= budget:
                return seq
            return [seq[i*(len(seq)-1)//max(1,budget-1)] for i in range(budget)]
        out = sample(ink, 450) + sample(blank, 300)
    return out


def _text_observation(bundle: dict, clip: dict, local: int, layer_idx: int,
                      image: bytes, font: str) -> dict[str, Any]:
    layers = clip["layers"]
    layer = layers[layer_idx]
    width, height = bundle["width"], bundle["height"]
    ok, reason = _supports_layer(layer, bundle, local, font)
    if not ok:
        return {"layer_id": layer["id"], "status": "INCONCLUSIVE", "reason": reason,
                "ink_pixels": 0, "blank_pixels": 0, "occluded_pixels": 0, "bad_pixels": 0,
                "occluded_bad_pixels": 0, "bad_fraction": 1.0}
    mask, ox, oy = _render_mask(layer, local, font)
    raw = _collect_candidates(mask, ox, oy, width, height)
    palette = bundle["palette"]
    ink = blank = occluded = bad = occ_bad = 0
    fg = _rgb(layer["fill"], palette)
    text_alpha = r3._geometry_at(layer, local)["opacity"]
    for x,y,is_ink in raw:
        base, edge = _geometry_color(bundle, layers, local, x, y, stop=layer_idx)
        if edge:
            continue
        # Ignore overlapping additional text layers; their compositing is not modeled.
        overlapping_text = False
        for other in layers[layer_idx+1:]:
            if other["kind"] != "text":
                continue
            gg = r3._geometry_at(other, local)
            if gg["x"] - 3 <= x < gg["x"] + len(other["text"]) * other["font_size"]:
                if gg["y"] - 3 <= y < gg["y"] + 1.6*other["font_size"]:
                    overlapping_text = True
                    break
        if overlapping_text:
            continue
        above, edge_above = _geometry_color(bundle, layers, local, x, y, start=layer_idx+1,
                                             initial=(0.,0.,0.))
        if edge_above:
            continue
        # Distinguish a fully opaque post-text mask (visible pixels MUST be geometry).
        opaque_idx = next((k for k in range(layer_idx+1, len(layers))
                           if layers[k]["kind"] != "text" and
                           r3._geometry_at(layers[k], local)["opacity"] > 0.995 and
                           _shape_cover(layers[k], local, x, y)[0]), None)
        pos = (y*width+x)*3
        measured = tuple(image[pos:pos+3])
        if opaque_idx is not None:
            # Project the final shape composite from scratch; independent of hidden text.
            expected, top_edge = _geometry_color(bundle, layers, local, x, y)
            if top_edge or not is_ink:
                continue
            occluded += 1
            if max(abs(measured[j]-expected[j]) for j in range(3)) > 35:
                occ_bad += 1
            continue
        if not is_ink and sum(abs(fg[j]-base[j]) for j in range(3)) < 90:
            continue
        # Reject unsupported semi-transparent layer above; can't compare against known underlay.
        if any(l["kind"] != "text" and 0.005 < r3._geometry_at(l,local)["opacity"] < 0.995
               and _shape_cover(l,local,x,y)[0] for l in layers[layer_idx+1:]):
            continue
        if any(l["kind"] != "text" and _shape_cover(l,local,x,y)[0]
               for l in layers[layer_idx+1:]):
            continue
        # Project the actual RGB onto the text-foreground direction, so luma
        # anti-aliasing and H264 compression affect the score less.
        direction = [text_alpha*(fg[j]-base[j]) for j in range(3)]
        norm = sum(x*x for x in direction)
        if norm < 1000:
            continue
        score = sum((measured[j]-base[j])*direction[j] for j in range(3))/norm
        if is_ink:
            ink += 1
            if score < 0.48:
                bad += 1
        else:
            blank += 1
            if score > 0.37:
                bad += 1
    checked = ink+blank
    fraction = bad / checked if checked else 1.0
    if occluded >= 12 and occ_bad / occluded > MAX_OCCLUSION_ERROR:
        status = "FAIL"
        reason = "opaque-later-layer-not-respected"
    elif ink < MIN_VISIBLE_INK or checked < 40:
        status = "INCONCLUSIVE"
        reason = "insufficient-visible-text-ink"
    elif fraction > FRAME_OUTLIER_FRACTION:
        status = "FAIL"
        reason = "text-stroke-mismatch"
    else:
        status = "PASS"
        reason = ""
    return {"layer_id": layer["id"], "status": status, "reason": reason,
            "ink_pixels": ink, "blank_pixels": blank, "occluded_pixels": occluded,
            "bad_pixels": bad, "occluded_bad_pixels": occ_bad,
            "bad_fraction": round(fraction, 6)}


def inspect(item: dict[str, Any], candidate_id: str, *, font_path: str = FONT_PATH) -> dict[str, Any]:
    """Measure sampled frames, independently of R3's geometry color probes."""
    if item["video_path"] is None or item["manifest"].get("video") is None:
        raise TextProbeError("candidate has no verified video")
    bundle = item["props"]["bundle"]
    frames = _frame_set(bundle)
    decoded = r3._decode_frames(item["video_path"], frames, bundle["width"], bundle["height"])
    results: list[dict] = []
    for frame, image in zip(frames, decoded):
        clip = r3._active_clip(bundle, frame)
        local = frame - clip["from"]
        for idx, layer in enumerate(clip["layers"]):
            if layer["kind"] != "text":
                continue
            result = _text_observation(bundle, clip, local, idx, image, font_path)
            result["frame"] = frame
            result["clip_id"] = clip["id"]
            results.append(result)
    if not results:
        raise TextProbeError("no text layers to inspect")
    total_ink = sum(x["ink_pixels"] for x in results)
    total_bad = sum(x["bad_pixels"] for x in results)
    total_checked = sum(x["ink_pixels"]+x["blank_pixels"] for x in results)
    total_occ = sum(x["occluded_pixels"] for x in results)
    total_occ_bad = sum(x["occluded_bad_pixels"] for x in results)
    statuses = {x["status"] for x in results}
    # A font/clip may have unsupported periods, but only a text layer with at
    # least one truly measured PASS can contribute to a PASS result. This does
    # not claim exhaustive text coverage; unmeasured periods are explicit.
    keys = {(x["clip_id"], x["layer_id"]) for x in results}
    supported_keys = {(x["clip_id"],x["layer_id"]) for x in results if x["status"] == "PASS"}
    if "FAIL" in statuses or (total_checked and total_bad/total_checked > PIXEL_OUTLIER_FRACTION):
        status = "FAIL_SAMPLED_TEXT"
    elif keys != supported_keys or total_ink < MIN_TOTAL_VISIBLE_INK:
        status = "INCONCLUSIVE_SAMPLED_TEXT"
    else:
        status = "PASS_SAMPLED_TEXT"
    manifest = item["manifest"]
    return {
        "schema": SCHEMA, "method": METHOD, "candidate_id": candidate_id,
        "status": status, "candidate_only": True, "approved_for_publish": False,
        "visual_equivalence_attested": False,
        "coverage": "sampled-ASCII-text-strokes-and-opaque-later-shapes-only",
        "excluded": ["non-ASCII-glyphs", "multiline-wrapping", "font-substitutions",
                     "anti-aliased-edge-exactness", "audio", "publishing-rights", "source-truth"],
        "pins": {"source_sha256": manifest["source_sha256"],
                 "program_sha256": manifest["program_sha256"],
                 "props_sha256": manifest["props_sha256"],
                 "video_sha256": manifest["video"]["sha256"]},
        "font_profile": "DejaVuSans-normal-ascii-linux-v0.1",
        "sampled_frames": frames, "total_frames": bundle["durationInFrames"],
        "text_samples": len(results), "unmeasured_samples": sum(x["status"] == "INCONCLUSIVE" for x in results),
        "covered_text_layers": len(supported_keys), "declared_text_layers": len(keys),
        "ink_pixels": total_ink,
        "blank_pixels": total_checked-total_ink,
        "occluded_pixels": total_occ, "bad_pixels": total_bad,
        "occluded_bad_pixels": total_occ_bad,
        "bad_fraction": round(total_bad/total_checked, 6) if total_checked else 1.,
        "layers": results,
    }


def _record_root(projects_dir: Path, project_id: str, candidate_id: str) -> Path:
    project = stage._ensure_project(projects_dir, project_id)
    stage.checked_id(candidate_id)
    return project / RECORD_DIR / candidate_id


def store(projects_dir: Path, project_id: str, candidate_id: str, report: dict[str, Any]) -> Path:
    root = _record_root(projects_dir, project_id, candidate_id)
    if root.exists() or root.is_symlink():
        raise TextProbeError("R4 report already exists; use a new candidate id")
    root.parent.mkdir(exist_ok=True)
    stage._require_plain_dir(root.parent, root.parent.parent)
    root.mkdir(exist_ok=False)
    raw = stage.canonical(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise TextProbeError("R4 report exceeds byte limit")
    checksum = stage.digest(raw)
    path = root / (checksum + ".json")
    path.write_bytes(raw)
    return path


def load_report(projects_dir: Path, project_id: str, candidate_id: str,
                item: dict[str, Any]) -> dict[str, Any] | None:
    directory = _record_root(projects_dir, project_id, candidate_id)
    if not directory.parent.exists():
        return None
    project = stage._ensure_project(projects_dir, project_id)
    stage._require_plain_dir(directory.parent, project)
    if not directory.exists():
        return None
    stage._require_plain_dir(directory, directory.parent)
    files = list(directory.iterdir())
    if len(files) != 1:
        raise TextProbeError("R4 report directory ambiguous")
    path = files[0]
    if (path.is_symlink() or not path.is_file() or not re.fullmatch(r"[a-f0-9]{64}\.json", path.name)
        or path.stat().st_size > MAX_REPORT_BYTES):
        raise TextProbeError("unsafe R4 report file")
    raw = path.read_bytes()
    if stage.digest(raw) != path.stem:
        raise TextProbeError("R4 report content hash mismatch")
    result = stage.bridge.read_strict_json(path, MAX_REPORT_BYTES)
    # R4 reports are local unsigned receipts, never approval. Strictly compare
    # to a fresh replay against the currently SHA-pinned MP4 to reject even a
    # re-hashed fabricated success record, without trusting report-provided math.
    expected = inspect(item, candidate_id)
    if stage.canonical(result) != stage.canonical(expected):
        raise TextProbeError("R4 report differs from fresh video measurement")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R4 sampled text and occlusion contract")
    parser.add_argument("action", choices=["check", "verify"])
    parser.add_argument("--projects-dir", type=Path, default=Path(__file__).resolve().parents[1] / "projects")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    args = parser.parse_args(argv)
    try:
        item = stage.load_package(args.projects_dir,args.project_id,args.candidate_id)
        if args.action == "check":
            report = inspect(item,args.candidate_id)
            store(args.projects_dir,args.project_id,args.candidate_id,report)
        else:
            report = load_report(args.projects_dir,args.project_id,args.candidate_id,item)
            if report is None:
                raise TextProbeError("no R4 report staged")
        print(json.dumps({"status":report["status"], "frames":len(report["sampled_frames"]),
                          "ink_pixels":report["ink_pixels"], "bad_pixels":report["bad_pixels"]},
                         sort_keys=True,ensure_ascii=False))
        return 0 if report["status"] == "PASS_SAMPLED_TEXT" else 3
    except (TextProbeError,r3.VisualProbeError,stage.ReviewPackageError,
            stage.bridge.r0.ProgramError,OSError,KeyError,ValueError,TypeError) as exc:
        print("ERROR:", exc,file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
