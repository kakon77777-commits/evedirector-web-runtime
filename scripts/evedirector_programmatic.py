#!/usr/bin/env python3
"""EveDirector native programmatic-video R0: source-grounded, allow-listed scene programs.

This is an isolated candidate-render tool. It does not mutate Backlot or L0-L6 authority.
It never executes supplied code, pulls remote URLs, or loads external scene assets.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

SCHEMA = "evedirector.programmatic_video.v0.1"
ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLORS = frozenset({"background", "primary", "accent", "text", "muted"})
GEOMETRY = {"rect": {"width", "height"}, "ellipse": {"width", "height"}, "text": {"text", "font_size"}}
PLAN_KEYS = {"schema", "title", "style", "width", "height", "fps", "frames", "scenes"}
SCENE_KEYS = {"id", "start_frame", "end_frame", "source_contains", "layers"}
LAYER_KEYS = {"id", "kind", "x", "y", "fill", "opacity", "width", "height", "text", "font_size", "font_profile", "keyframes"}


class ProgramError(ValueError):
    """A scene program violates the R0 contract."""


def _check_keys(value: Any, required: set[str], optional: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ProgramError(f"{label} must be an object")
    missing, extra = required - value.keys(), value.keys() - required - optional
    if missing or extra:
        raise ProgramError(f"{label}: missing={sorted(missing)} unknown={sorted(extra)}")


def _int(value: Any, lo: int, hi: int, label: str) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise ProgramError(f"{label} must be an integer in [{lo}, {hi}]")
    return value


def _num(value: Any, lo: float, hi: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ProgramError(f"{label} must be a finite number in [{lo}, {hi}]")
    return float(value)


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise ProgramError(f"{label} must be a safe slug")
    return value


def _color(value: Any, label: str) -> str:
    if not isinstance(value, str) or (value not in COLORS and HEX.fullmatch(value) is None):
        raise ProgramError(f"{label} must be a palette token or #RRGGBB")
    return value


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda s: (_ for _ in ()).throw(ProgramError(f"invalid JSON constant: {s}")))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProgramError(f"invalid UTF-8 JSON: {exc}") from exc


def _load_style(name: str, styles_dir: Path) -> tuple[dict[str, str], str]:
    # No path component can come from model-controlled style names.
    _id(name, "style")
    path = (styles_dir / (name + ".yaml")).resolve()
    if path.parent != styles_dir.resolve() or not path.is_file():
        raise ProgramError(f"missing or unsafe local style preset: {name}")
    try:
        import yaml
    except ImportError as exc:
        raise ProgramError("PyYAML is required for checked-in style presets") from exc
    raw = path.read_bytes()
    try:
        style = yaml.safe_load(raw)
        colors = style["visual_language"]["color_palette"]
        result = {
            "background": colors["background"],
            "primary": colors["primary"][0],
            "accent": colors["accent"][0],
            "text": colors["text"],
            "muted": colors["muted"],
        }
    except (KeyError, TypeError, IndexError, yaml.YAMLError) as exc:
        raise ProgramError(f"malformed color palette for {name}: {exc}") from exc
    for k, v in result.items():
        if not isinstance(v, str) or HEX.fullmatch(v) is None:
            raise ProgramError(f"style {name} palette.{k} must be #RRGGBB")
    return result, _digest(raw)


def validate(plan: dict[str, Any], source: bytes, styles_dir: Path) -> dict[str, Any]:
    """Validate an AI-authored candidate without executing it; return an evidence receipt."""
    _check_keys(plan, PLAN_KEYS, set(), "program")
    if plan["schema"] != SCHEMA:
        raise ProgramError("unsupported schema (no silent upgrade)")
    if not isinstance(plan["title"], str) or not 1 <= len(plan["title"]) <= 140:
        raise ProgramError("title must be 1..140 characters")
    width = _int(plan["width"], 160, 1920, "width")
    height = _int(plan["height"], 90, 1080, "height")
    _int(plan["fps"], 1, 60, "fps")
    total = _int(plan["frames"], 1, 1800, "frames")
    if width * height * total > 250_000_000:
        raise ProgramError("pixel-frame budget exceeded")
    palette, style_sha = _load_style(plan["style"], styles_dir)
    try:
        lines = source.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ProgramError("source must be UTF-8") from exc
    scenes = plan["scenes"]
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 30:
        raise ProgramError("scenes must contain 1..30 items")
    cursor, ids, anchors = 0, set(), []
    for index, scene in enumerate(scenes):
        _check_keys(scene, SCENE_KEYS, set(), f"scene[{index}]")
        sid = _id(scene["id"], "scene.id")
        if sid in ids:
            raise ProgramError(f"duplicate scene id: {sid}")
        ids.add(sid)
        start = _int(scene["start_frame"], 0, total - 1, "scene.start_frame")
        end = _int(scene["end_frame"], 1, total, "scene.end_frame")
        if start != cursor or end <= start:
            raise ProgramError(f"scene {sid} has gap, overlap, or nonpositive duration")
        cursor = end
        phrase = scene["source_contains"]
        if not isinstance(phrase, str) or not 8 <= len(phrase.strip()) <= 500:
            raise ProgramError(f"scene {sid} needs a bounded source quote")
        matches = [i + 1 for i, line in enumerate(lines) if phrase in line]
        if not matches:
            raise ProgramError(f"scene {sid} has no matching source line")
        anchors.append({"scene_id": sid, "source_contains": phrase, "line_start": matches[0], "line_end": matches[0]})
        layers = scene["layers"]
        if not isinstance(layers, list) or not 1 <= len(layers) <= 48:
            raise ProgramError(f"scene {sid}: layers must contain 1..48 items")
        layer_ids = set()
        for j, layer in enumerate(layers):
            _check_keys(layer, {"id", "kind", "x", "y", "fill"}, LAYER_KEYS - {"id", "kind", "x", "y", "fill"}, f"layer[{j}]")
            lid = _id(layer["id"], "layer.id")
            if lid in layer_ids:
                raise ProgramError(f"scene {sid} has duplicate layer id: {lid}")
            layer_ids.add(lid)
            kind = layer["kind"]
            if not isinstance(kind, str) or kind not in GEOMETRY:
                raise ProgramError(f"unknown render primitive: {kind!r}")
            expected = GEOMETRY[kind]
            extra = {"width", "height", "text", "font_size"} - expected
            if kind != "text":
                extra.add("font_profile")
            if any(k in layer for k in extra) or any(k not in layer for k in expected):
                raise ProgramError(f"layer {lid} has incompatible fields for {kind}")
            for axis, hi in (("x", width * 3), ("y", height * 3)):
                _num(layer[axis], -hi, hi, f"{lid}.{axis}")
            _color(layer["fill"], f"{lid}.fill")
            _num(layer.get("opacity", 1), 0, 1, f"{lid}.opacity")
            if kind in {"rect", "ellipse"}:
                _num(layer["width"], 1, width * 3, f"{lid}.width")
                _num(layer["height"], 1, height * 3, f"{lid}.height")
            else:
                if not isinstance(layer["text"], str) or not 1 <= len(layer["text"]) <= 240:
                    raise ProgramError(f"{lid}.text must contain 1..240 characters")
                _int(layer["font_size"], 8, 160, f"{lid}.font_size")
                # R5 is opt-in. Legacy ASCII scenes retain their exact contract.
                # CJK may never use an implicit OS fallback font.
                profile = layer.get("font_profile")
                if profile not in (None, "dejavu-ascii-v1", "noto-cjk-tc-v1"):
                    raise ProgramError(f"{lid}.font_profile is not allow-listed")
                text = layer["text"]
                if any(0xD800 <= ord(ch) <= 0xDFFF or
                       (ord(ch) < 32 and ch != "\n") or
                       ch in "\u200b\u200c\u200d\u2060\ufeff\u202a\u202b\u202c\u202d\u202e" for ch in text):
                    raise ProgramError(f"{lid}.text contains forbidden control/format characters")
                if not text.isascii() and profile != "noto-cjk-tc-v1":
                    raise ProgramError(f"{lid}.text requires explicit CJK font_profile")
                if profile != "noto-cjk-tc-v1" and "\n" in text:
                    raise ProgramError(f"{lid}.text multiline requires explicit CJK profile")
                if profile == "noto-cjk-tc-v1" and (
                    len(text.split("\n")) > 2 or
                    any(not line.strip() or len(line) > 28 for line in text.split("\n"))):
                    raise ProgramError(f"{lid}.text unsupported CJK line layout")
            tracks = layer.get("keyframes", {})
            if not isinstance(tracks, dict) or set(tracks) - {"x", "y", "opacity", "width", "height"}:
                raise ProgramError(f"{lid}.keyframes has unknown tracks")
            for name, points in tracks.items():
                if name in {"width", "height"} and kind == "text":
                    raise ProgramError(f"{lid}: text width/height keyframes are forbidden")
                if not isinstance(points, list) or not 1 <= len(points) <= 50:
                    raise ProgramError(f"{lid}.{name} needs 1..50 keyframes")
                last = -1
                for point in points:
                    _check_keys(point, {"frame", "value"}, set(), f"{lid}.{name}.point")
                    t = _int(point["frame"], 0, end - start - 1, "keyframe.frame")
                    if t <= last:
                        raise ProgramError("keyframes must be strictly increasing")
                    last = t
                    bound = 1 if name == "opacity" else (width * 3 if name in {"x", "width"} else height * 3)
                    floor = 1 if name in {"width", "height"} else (0 if name == "opacity" else -bound)
                    _num(point["value"], floor, bound, f"keyframe.{name}")
    if cursor != total:
        raise ProgramError("scene timeline must cover all frames")
    return {
        "schema": "evedirector.programmatic_receipt.v0.1",
        "candidate_only": True,
        "source_sha256": _digest(source),
        "program_sha256": _digest(_canonical_json(plan)),
        "style": plan["style"],
        "style_sha256": style_sha,
        "palette": palette,
        "fps": plan["fps"],
        "resolution": [width, height],
        "frames": total,
        "anchors": anchors,
        "external_assets": 0,
        "code_executed_from_program": False,
        "canonical_spec_mutated": False,
    }


def _value(layer: dict[str, Any], key: str, frame: int) -> float:
    original = float(layer.get(key, 1 if key == "opacity" else 0))
    track = layer.get("keyframes", {}).get(key)
    if not track:
        return original
    if frame <= track[0]["frame"]:
        return float(track[0]["value"])
    for left, right in zip(track, track[1:]):
        if frame <= right["frame"]:
            fraction = (frame - left["frame"]) / (right["frame"] - left["frame"])
            return left["value"] + (right["value"] - left["value"]) * fraction
    return float(track[-1]["value"])


def draw_frame(plan: dict[str, Any], receipt: dict[str, Any], frame: int, font_file: Path | None = None):
    """Render one frame. Import of Pillow is deferred so validate needs no imaging runtime."""
    from PIL import Image, ImageDraw, ImageFont
    palette = receipt["palette"]
    width, height = receipt["resolution"]
    image = Image.new("RGBA", (width, height), palette["background"])
    scene = next(s for s in plan["scenes"] if s["start_frame"] <= frame < s["end_frame"])
    local = frame - scene["start_frame"]
    for layer in scene["layers"]:
        x, y = round(_value(layer, "x", local)), round(_value(layer, "y", local))
        opacity = round(_value(layer, "opacity", local) * 255)
        if opacity == 0:
            continue
        token = layer["fill"]
        color = token if HEX.fullmatch(token) else palette[token]
        rgba = tuple(bytes.fromhex(color[1:])) + (opacity,)
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        canvas = ImageDraw.Draw(overlay)
        if layer["kind"] == "rect":
            canvas.rectangle((x, y, x + round(_value(layer, "width", local)), y + round(_value(layer, "height", local))), fill=rgba)
        elif layer["kind"] == "ellipse":
            canvas.ellipse((x, y, x + round(_value(layer, "width", local)), y + round(_value(layer, "height", local))), fill=rgba)
        else:
            size = layer["font_size"]
            try:
                font = ImageFont.truetype(str(font_file or "DejaVuSans.ttf"), size)
            except OSError:
                font = ImageFont.load_default(size=size)
            canvas.text((x, y), layer["text"], font=font, fill=rgba)
        image = Image.alpha_composite(image, overlay)
    return image.convert("RGB")


def render(plan: dict[str, Any], receipt: dict[str, Any], output: Path, font_file: Path | None = None, force: bool = False) -> dict[str, Any]:
    if output.suffix.lower() != ".mp4":
        raise ProgramError("output must be an .mp4 file")
    if output.exists() and not force:
        raise ProgramError("output exists; pass --force to overwrite")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ProgramError("FFmpeg and FFprobe are required for MP4 render")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="evedirector-r0-") as tmp:
        directory = Path(tmp)
        for frame in range(plan["frames"]):
            draw_frame(plan, receipt, frame, font_file).save(directory / f"frame_{frame:05d}.png")
        sample = (directory / "frame_00000.png").read_bytes()
        encoded = directory / "encoded.mp4"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(plan["fps"]), "-i", str(directory / "frame_%05d.png"), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(encoded)]
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        if proc.returncode or not encoded.is_file() or encoded.stat().st_size == 0:
            raise ProgramError(f"FFmpeg render failed: {proc.stderr[-2000:]}")
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,nb_frames,r_frame_rate", "-select_streams", "v:0", "-of", "json", str(encoded)], capture_output=True, text=True, check=False)
        if probe.returncode:
            raise ProgramError(f"FFprobe failed: {probe.stderr[-2000:]}")
        streams = json.loads(probe.stdout).get("streams", [])
        if len(streams) != 1 or streams[0].get("codec_name") != "h264" or streams[0].get("width") != plan["width"] or streams[0].get("height") != plan["height"]:
            raise ProgramError("FFprobe video metadata differs from candidate plan")
        if (streams[0].get("nb_frames") != str(plan["frames"])
                or Fraction(streams[0].get("r_frame_rate", "0/1")) != plan["fps"]):
            raise ProgramError("FFprobe frame count or frame rate differs from candidate plan")
        os.replace(encoded, output)
    receipt = dict(receipt)
    receipt["render"] = {"status": "VERIFIED_LOCAL", "output_name": output.name, "output_sha256": _digest(output.read_bytes()), "bytes": output.stat().st_size, "first_frame_png_sha256": _digest(sample), "ffprobe_stream": streams[0]}
    receipt["font"] = {"configured_file_sha256": _digest(font_file.read_bytes()) if font_file else None, "note": "Cross-host pixel/MP4 byte identity is NOT claimed; font and encoder versions matter."}
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EveDirector R0: deterministic semantic scene program and offline video renderer")
    parser.add_argument("command", choices=["validate", "render"])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--styles-dir", type=Path, default=Path(__file__).resolve().parents[1] / "styles")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "render" and args.output is None:
            raise ProgramError("render requires --output")
        if args.font and not args.font.is_file():
            raise ProgramError("explicit --font file not found")
        if args.manifest and args.manifest.exists() and not args.force:
            raise ProgramError("manifest exists; pass --force to overwrite")
        plan = _read_json(args.plan)
        receipt = validate(plan, args.source.read_bytes(), args.styles_dir)
        if args.command == "render":
            receipt = render(plan, receipt, args.output, args.font, args.force)
        if args.manifest:
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_bytes(_canonical_json(receipt))
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ProgramError, OSError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

