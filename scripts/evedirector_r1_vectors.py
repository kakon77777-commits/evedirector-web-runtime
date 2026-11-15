#!/usr/bin/env python3
"""Create reproducible R0 reference interpolation vectors for R1 Node comparison."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_remotion_bridge as bridge


def generate(plan: dict, source: bytes, styles: Path) -> dict:
    bundle = bridge.build_props(plan, source, styles)["bundle"]
    vectors = []
    for scene in plan["scenes"]:
        for layer in scene["layers"]:
            fields = ("x", "y", "opacity", "width", "height") if layer["kind"] != "text" else ("x", "y", "opacity")
            last = scene["end_frame"] - scene["start_frame"] - 1
            for field in fields:
                for frame in sorted(set((0, min(last, 1), min(last, 10), min(last, 15), last))):
                    vectors.append({
                        "scene": scene["id"], "layer": layer["id"],
                        "field": field, "frame": frame,
                        "value": bridge.r0._value(layer, field, frame),
                    })
    return {
        "schema": "evedirector.interpolation_vectors.v0.1",
        "r0_program_sha256": bundle["program_sha256"],
        "vectors": vectors,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", type=Path, default=Path("examples/native-video/program.json"))
    p.add_argument("--source", type=Path, default=Path("examples/native-video/source/README.md"))
    p.add_argument("--styles-dir", type=Path, default=Path("styles"))
    p.add_argument("--out", type=Path, default=Path("generated/interpolation_vectors.json"))
    args = p.parse_args()
    vectors = generate(bridge.read_strict_json(args.plan), bridge.read_source(args.source), args.styles_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(vectors, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n", encoding="utf-8")
    print("INTERPOLATION_VECTORS:", len(vectors["vectors"]))


if __name__ == "__main__":
    main()
