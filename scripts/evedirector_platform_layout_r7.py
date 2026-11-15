#!/usr/bin/env python3
"""R7 deterministic multi-platform Scene Program layout compiler.

Versioned editorial-safe presets, *not* provider-published safe-zone guarantees.
Reuses R0 source anchoring and R6 pinned-font layout; produces candidate-only
plans and replayable receipts. No network assets, video publish or Apply.
"""
from __future__ import annotations
import argparse
import copy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_programmatic as r0
import evedirector_subtitle_layout_r6 as r6
import evedirector_review_stage as stage

SCHEMA = "evedirector.platform_layout_request.v0.1"
REPORT_SCHEMA = "evedirector.platform_layout_matrix.v0.1"
# Self-authored editing presets. Numbers are *not* platform UI certifications.
PROFILES = {
    "bilibili_landscape_v1": {"provider":"bilibili", "format":"16:9","width":640,"height":360,"font_size":38,"safe_area":{"left":42,"right":42,"top":38,"bottom":48}},
    "bilibili_vertical_v1": {"provider":"bilibili", "format":"9:16","width":360,"height":640,"font_size":36,"safe_area":{"left":40,"right":40,"top":60,"bottom":126}},
    "square_social_v1": {"provider":"generic", "format":"1:1","width":540,"height":540,"font_size":38,"safe_area":{"left":50,"right":50,"top":50,"bottom":94}},
    "tiktok_vertical_v1": {"provider":"tiktok", "format":"9:16","width":360,"height":640,"font_size":36,"safe_area":{"left":36,"right":46,"top":72,"bottom":140}},
    "youtube_landscape_v1": {"provider":"youtube", "format":"16:9","width":640,"height":360,"font_size":38,"safe_area":{"left":36,"right":36,"top":36,"bottom":36}},
    "youtube_shorts_v1": {"provider":"youtube", "format":"9:16","width":360,"height":640,"font_size":36,"safe_area":{"left":36,"right":36,"top":64,"bottom":120}},
}

class PlatformLayoutError(ValueError):
    pass

def canonical(data):
    return stage.canonical(data)

def digest(data):
    return sha256(data).hexdigest()

def _keys(obj, expected, context):
    if not isinstance(obj, dict) or set(obj) != set(expected):
        raise PlatformLayoutError(f"{context} unknown or missing keys")

def _scaled(base, profile):
    result = copy.deepcopy(base)
    sx = profile["width"] / base["width"]
    sy = profile["height"] / base["height"]
    result["width"], result["height"] = profile["width"], profile["height"]
    for scene in result["scenes"]:
        for layer in scene["layers"]:
            if layer.get("keyframes"):
                raise PlatformLayoutError("R7 cannot silently rescale animated base layers")
            for key, factor in (("x",sx),("y",sy),("width",sx),("height",sy)):
                if key in layer:
                    val = round(layer[key] * factor)
                    layer[key] = max(1,val) if key in ("width","height") else val
            if layer["kind"] == "text":
                layer["font_size"] = profile["font_size"]
    return result

def _fingerprint(plan):
    return [(s["id"], s["start_frame"], s["end_frame"], s["source_contains"]) for s in plan["scenes"]]

def compile_matrix(base, source, styles_dir, request):
    _keys(request, ("schema","profiles","font","cues"), "R7 request")
    if request["schema"] != SCHEMA:
        raise PlatformLayoutError("unsupported R7 request schema")
    profiles = request["profiles"]
    if (not isinstance(profiles,list) or not 1 <= len(profiles) <= 6
            or any(type(p) is not str or p not in PROFILES for p in profiles)
            or profiles != sorted(set(profiles))):
        raise PlatformLayoutError("profiles must be sorted, unique known names")
    r0.validate(base,source,styles_dir)
    # No text layers may silently disappear in a platform export.
    expected_cues = {(s["id"],l["id"]) for s in base["scenes"] for l in s["layers"] if l["kind"]=="text"}
    cues=request["cues"]
    if (not isinstance(cues,list) or len(cues) != len(expected_cues)
        or any(not isinstance(c,dict) or set(c) != {"scene_id","layer_id","text","placement"} for c in cues)
        or {(c["scene_id"],c["layer_id"]) for c in cues} != expected_cues):
        raise PlatformLayoutError("one source-grounded cue required for each base text layer")
    results=[]
    source_fingerprint=_fingerprint(base)
    for profile_name in profiles:
        preset=PROFILES[profile_name]
        scaled=_scaled(base,preset)
        layout={"schema":r6.SCHEMA, "font":copy.deepcopy(request["font"]),
                "safe_area":copy.deepcopy(preset["safe_area"]), "cues":copy.deepcopy(cues)}
        plan,receipt=r6.compile_layout(scaled,source,styles_dir,layout)
        if _fingerprint(plan) != source_fingerprint:
            raise PlatformLayoutError("scene ids, timing or source anchor changed")
        if receipt["font"]["sha256"] != request["font"]["sha256"]:
            raise PlatformLayoutError("font fingerprint drift")
        results.append({"profile":profile_name,"preset":copy.deepcopy(preset),
                        "base":scaled,"layout_request":layout,"plan":plan,"receipt":receipt})
    report={"schema":REPORT_SCHEMA,"status":"PASS_EDITING_SAFE_LAYOUT_MATRIX",
            "candidate_only":True,"approved_for_publish":False,
            "official_platform_safe_area_certified":False,
            "visual_equivalence_attested":False,
            "source_sha256":digest(source),"base_sha256":digest(canonical(base)),
            "request_sha256":digest(canonical(request)),
            "presets_sha256":digest(canonical(PROFILES)),
            "variants":[{"profile":v["profile"],"provider":v["preset"]["provider"],
                         "format":v["preset"]["format"],"width":v["plan"]["width"],
                         "height":v["plan"]["height"],"fps":v["plan"]["fps"],
                         "frames":v["plan"]["frames"],"safe_area":v["preset"]["safe_area"],
                         "line_count":v["receipt"]["line_count"],
                         "program_sha256":digest(canonical(v["plan"])),
                         "layout_receipt_sha256":digest(canonical(v["receipt"]))}
                        for v in results],
            "excluded":["official_platform_UI_guarantees","all_devices_overlay_safety",
                        "rendered_pixel_equivalence","publication_approval"]}
    return report,results

def _expected_files(report, results):
    files={"matrix.json":canonical(report)}
    for v in results:
        p=v["profile"]
        files[p+".plan.json"]=canonical(v["plan"])
        files[p+".base.json"]=canonical(v["base"])
        files[p+".r6-request.json"]=canonical(v["layout_request"])
        files[p+".layout-receipt.json"]=canonical(v["receipt"])
    return files

def output_files(folder,files,verify):
    if verify:
        if folder.is_symlink() or not folder.is_dir() or {p.name for p in folder.iterdir()} != set(files):
            raise PlatformLayoutError("R7 output missing/unexpected files")
        for name,raw in files.items():
            path=folder/name
            if path.is_symlink() or not path.is_file() or path.read_bytes()!=raw:
                raise PlatformLayoutError(f"R7 replay mismatch: {name}")
        return
    if folder.exists() or folder.is_symlink():
        raise PlatformLayoutError("R7 output exists; append-only/no overwrite")
    folder.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix=".r7-",dir=folder.parent))
    try:
        for name,raw in files.items():
            (temp/name).write_bytes(raw)
        temp.rename(folder)
    finally:
        if temp.exists(): shutil.rmtree(temp)

def main(argv=None):
    p=argparse.ArgumentParser(description="EveDirector R7 finite platform safe-layout compiler")
    p.add_argument("action", choices=("compile","verify"))
    p.add_argument("--base",type=Path,required=True)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--request",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--styles-dir",type=Path,default=Path(__file__).resolve().parents[1]/"styles")
    args=p.parse_args(argv)
    try:
        base=stage.bridge.read_strict_json(args.base)
        source=stage.bridge.read_source(args.source)
        request=stage.bridge.read_strict_json(args.request,128_000)
        report,variants=compile_matrix(base,source,args.styles_dir,request)
        output_files(args.out,_expected_files(report,variants),args.action=="verify")
        print(f"R7 {args.action}: PASS | profiles={len(variants)} | candidate_only=True")
        return 0
    except (PlatformLayoutError,r6.SubtitleLayoutError,r6.r5.MultilangProbeError,
            r0.ProgramError,stage.ReviewPackageError,OSError,ValueError,TypeError,KeyError) as exc:
        print(f"R7 {args.action}: FAIL | {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
