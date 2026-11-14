#!/usr/bin/env python3
"""EveDirector R1 add-only, source-linked Scene IR -> Remotion props exporter.

No rendering, code execution, remote fetch or existing L0-L6 state mutation.
The R0 validator remains the sole scene-program authority. Remotion consumes
only the returned allow-listed primitive data and never model-authored scripts.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_programmatic as r0

BUNDLE_SCHEMA = "evedirector.remotion_clip_bundle.v0.1"
MAX_SOURCE_BYTES = 2_000_000
MAX_PLAN_BYTES = 2_000_000
MAX_PROPS_BYTES = 3_000_000
MAX_RECEIPT_BYTES = 500_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise r0.ProgramError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_strict_json(path: Path, limit: int = MAX_PLAN_BYTES) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) > limit:
        raise r0.ProgramError(f"JSON input exceeds {limit} bytes")
    try:
        parsed = json.loads(
            data.decode("utf-8"), object_pairs_hook=strict_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                r0.ProgramError(f"invalid JSON constant: {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise r0.ProgramError(f"invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise r0.ProgramError("top-level JSON must be an object")
    return parsed


def read_source(path: Path) -> bytes:
    source = path.read_bytes()
    if len(source) > MAX_SOURCE_BYTES:
        raise r0.ProgramError(f"source exceeds {MAX_SOURCE_BYTES} bytes")
    return source


def build_props(plan: dict[str, Any], source: bytes, styles_dir: Path) -> dict[str, Any]:
    """R0-valid input -> JSON only; exact trace from source line to each clip."""
    receipt = r0.validate(plan, source, styles_dir)
    source_lines = source.decode("utf-8").splitlines()
    anchors_by_id = {a["scene_id"]: a for a in receipt["anchors"]}
    clips: list[dict[str, Any]] = []
    for scene in plan["scenes"]:
        anchor = anchors_by_id[scene["id"]]
        line = source_lines[anchor["line_start"] - 1]
        clips.append({
            "id": scene["id"],
            "from": scene["start_frame"],
            "durationInFrames": scene["end_frame"] - scene["start_frame"],
            "source": {
                "source_contains": anchor["source_contains"],
                "line_start": anchor["line_start"],
                "line_end": anchor["line_end"],
                "logical_line_sha256": sha256(line.encode("utf-8")),
            },
            "layers": copy.deepcopy(scene["layers"]),
        })
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "title": plan["title"],
        "candidate_only": True,
        "review_required": True,
        "canonical_spec_mutated": False,
        "source_approval_verified": False,
        "source_evidence_scope": "substring-present-at-explicit-line",
        "program_sha256": receipt["program_sha256"],
        "source_sha256": receipt["source_sha256"],
        "style": receipt["style"],
        "style_sha256": receipt["style_sha256"],
        "palette": receipt["palette"],
        "width": plan["width"],
        "height": plan["height"],
        "fps": plan["fps"],
        "durationInFrames": plan["frames"],
        "clips": clips,
    }
    return {"bundle": bundle}


def build_receipt(props: dict[str, Any]) -> dict[str, Any]:
    bundle = props["bundle"]
    return {
        "schema": "evedirector.remotion_bridge_receipt.v0.1",
        "candidate_only": True,
        "canonical_spec_mutated": False,
        "review_required": True,
        "props_sha256": sha256(r0._canonical_json(props)),
        "source_sha256": bundle["source_sha256"],
        "program_sha256": bundle["program_sha256"],
        "style_sha256": bundle["style_sha256"],
        "clip_count": len(bundle["clips"]),
        "durationInFrames": bundle["durationInFrames"],
        "source_anchors": [
            {"clip_id": c["id"], "from": c["from"], "durationInFrames": c["durationInFrames"], **c["source"]}
            for c in bundle["clips"]
        ],
        "render_status": "NOT_RENDERED_BY_REMOTION",
        "L0_L6_status": "NOT_EVALUATED_NO_REPOSITORY_ACCESS",
    }


def verify(props: dict[str, Any], plan: dict[str, Any], source: bytes, styles_dir: Path,
           expected_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = build_props(plan, source, styles_dir)
    if r0._canonical_json(props) != r0._canonical_json(expected):
        raise r0.ProgramError("props differ from exact source/plan/style-derived export")
    receipt = build_receipt(expected)
    if expected_receipt is not None and r0._canonical_json(receipt) != r0._canonical_json(expected_receipt):
        raise r0.ProgramError("receipt differs from exact source/plan/style-derived export")
    return receipt


def write_new_atomic(path: Path, content: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise r0.ProgramError(f"destination exists: {path} (pass --force)")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".evedirector-r1-", delete=False) as out:
            temp_path = Path(out.name)
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EveDirector R1 offline Remotion-props bridge")
    parser.add_argument("command", choices=["export", "verify"])
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--styles-dir", type=Path, default=Path(__file__).resolve().parents[1] / "styles")
    parser.add_argument("--props", required=True, type=Path, help="export destination / verify input")
    parser.add_argument("--receipt", type=Path, help="optional export destination / verify input")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.receipt and args.receipt.resolve() == args.props.resolve():
            raise r0.ProgramError("props and receipt cannot be the same file")
        plan = read_strict_json(args.plan)
        source = read_source(args.source)
        if args.command == "export":
            if (args.props.exists() or (args.receipt and args.receipt.exists())) and not args.force:
                raise r0.ProgramError("destination exists; pass --force to overwrite")
            props = build_props(plan, source, args.styles_dir)
            receipt = build_receipt(props)
            write_new_atomic(args.props, r0._canonical_json(props), args.force)
            if args.receipt:
                write_new_atomic(args.receipt, r0._canonical_json(receipt), args.force)
        else:
            props = read_strict_json(args.props, MAX_PROPS_BYTES)
            existing = read_strict_json(args.receipt, MAX_RECEIPT_BYTES) if args.receipt else None
            receipt = verify(props, plan, source, args.styles_dir, existing)
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (r0.ProgramError, OSError, ImportError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
