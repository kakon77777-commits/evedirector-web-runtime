#!/usr/bin/env python3
"""EveDirector R9: bounded offline plugin discovery, invocation, and receipts.

This is an additive, candidate-only adapter host. Registry JSON is *data*, not
executable instructions. Only the explicitly coded handlers below can run.
No network, canonical writes, external publication or arbitrary shell commands.

EVOE remains an independently installed, privately licensed engine; no EVOE
implementation or font binary is copied into this public host.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "plugins" / "evedirector"
SCHEMA = "evedirector.plugin_request.v1"
RECEIPT_SCHEMA = "evedirector.plugin_run_receipt.v1"
SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_REQUEST = 16 * 1024
MAX_INPUT = 2 * 1024 * 1024
MAX_SNAPSHOT = 1024 * 1024
MAX_VIDEO = 128 * 1024 * 1024
MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_TOTAL_FILES = 120

# Only these functions may be invoked. Plugin manifests NEVER supply a command.
IMPLEMENTED = {
    "native-r0": {"render_video"},
    "evoe": {"animate_frames"},
    "ordr": {"inspect_snapshot"},
}


class PluginError(ValueError):
    pass


def exact(obj: Any, required: set[str], optional: set[str] = frozenset(), *, label: str = "object") -> dict:
    if not isinstance(obj, dict) or required - obj.keys() or obj.keys() - required - optional:
        raise PluginError(f"{label} has missing or forbidden fields")
    return obj


def ident(v: Any, label: str = "identifier") -> str:
    if not isinstance(v, str) or SLUG.fullmatch(v) is None:
        raise PluginError(f"invalid {label}")
    return v


def uint(v: Any, minimum: int, maximum: int, label: str) -> int:
    if type(v) is not int or not minimum <= v <= maximum:
        raise PluginError(f"{label} outside integer budget")
    return v


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def strict_decode(raw: bytes, limit: int = MAX_INPUT) -> Any:
    if len(raw) > limit:
        raise PluginError("JSON exceeds input budget")
    def no_duplicates(pairs):
        d = {}
        for key, val in pairs:
            if key in d:
                raise PluginError("duplicate JSON object key")
            d[key] = val
        return d
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(PluginError("NaN/Infinity forbidden")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PluginError("invalid UTF-8 JSON") from exc


def json_read(path: Path, limit: int = MAX_INPUT) -> Any:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise PluginError("missing, linked or oversized JSON file")
    return strict_decode(path.read_bytes(), limit)


def safe_relative(root: Path, name: Any, limit: int = MAX_INPUT) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise PluginError("input path must be a project-relative POSIX path")
    p = PurePosixPath(name)
    if any(s in ("", ".", "..") for s in p.parts) or ":" in name:
        raise PluginError("input path traversal is forbidden")
    if root.is_symlink() or not root.is_dir():
        raise PluginError("input root must be an existing real directory")
    path = root.joinpath(*p.parts)
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (ValueError, OSError) as exc:
        raise PluginError("input escapes bounded input root") from exc
    cur = root
    for part in p.parts:
        cur = cur / part
        if cur.is_symlink():
            raise PluginError("symlink input forbidden")
    if not path.is_file() or path.stat().st_size > limit:
        raise PluginError("missing or oversized input")
    return path


def catalog() -> list[dict[str, Any]]:
    if CATALOG_DIR.is_symlink() or not CATALOG_DIR.is_dir():
        raise PluginError("plugin catalog directory missing or linked")
    out = []
    for path in sorted(CATALOG_DIR.glob("*.json")):
        item = json_read(path, MAX_REQUEST)
        exact(item, {"schema", "plugin_id", "version", "title", "source", "operations", "authority", "status"}, label="plugin manifest")
        name = ident(item["plugin_id"], "plugin ID")
        if item["schema"] != "evedirector.plugin_manifest.v1" or path.stem != name or name not in IMPLEMENTED:
            raise PluginError("unsupported or unregistered plugin manifest")
        if not isinstance(item["operations"], list) or set(item["operations"]) != IMPLEMENTED[name]:
            raise PluginError("plugin operations disagree with reviewed handlers")
        if not isinstance(item["title"], str) or not isinstance(item["source"], str) or not isinstance(item["version"], str):
            raise PluginError("invalid plugin metadata")
        exact(item["authority"], {"canonical_write", "network", "publish", "request_only"}, label="plugin authority")
        if item["authority"] != {"canonical_write": False, "network": False, "publish": False, "request_only": True}:
            raise PluginError("plugin cannot request elevated authority")
        out.append(item)
    if {x["plugin_id"] for x in out} != set(IMPLEMENTED):
        raise PluginError("plugin catalog is incomplete")
    return out


def describe(plugin_id: str) -> dict[str, Any]:
    ident(plugin_id, "plugin")
    for item in catalog():
        if item["plugin_id"] == plugin_id:
            return item
    raise PluginError("plugin not registered")


def resolve_request(value: Any) -> dict[str, Any]:
    req = exact(value, {"schema", "plugin_id", "operation", "candidate_id", "inputs"}, label="plugin request")
    if req["schema"] != SCHEMA:
        raise PluginError("unsupported plugin request schema")
    plugin = ident(req["plugin_id"], "plugin")
    operation = ident(req["operation"], "operation")
    ident(req["candidate_id"], "candidate")
    if operation not in IMPLEMENTED.get(plugin, set()):
        raise PluginError("unknown plugin operation")
    if not isinstance(req["inputs"], dict):
        raise PluginError("inputs must be a JSON object")
    data = req["inputs"]
    if plugin == "native-r0":
        exact(data, {"plan", "source"}, label="native input")
    elif plugin == "evoe":
        exact(data, {"scene", "size", "frame_count", "fps", "samples"}, label="EVOE input")
        uint(data["size"], 4, 256, "EVOE resolution")
        if data["size"] % 4:
            raise PluginError("EVOE size must be multiple of 4")
        uint(data["frame_count"], 2, 100, "frame_count")
        uint(data["fps"], 1, 60, "fps")
        uint(data["samples"], 1, 4, "samples")
    elif plugin == "ordr":
        exact(data, {"snapshot"}, label="ORDR input")
    return req


def _check_artifact(path: Path, max_bytes: int = MAX_VIDEO) -> str:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > max_bytes:
        raise PluginError("expected bounded output missing or unsafe")
    return digest(path.read_bytes())


def _png_dimensions(path: Path) -> tuple[int, int]:
    if _check_artifact(path, MAX_FRAME_BYTES) is None:
        raise AssertionError("unreachable")
    with path.open("rb") as inp:
        header = inp.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise PluginError("invalid PNG output signature")
    return struct.unpack(">II", header[16:24])


def _ffprobe(path: Path, *, frames: int, fps: int, width: int, height: int) -> None:
    if not shutil.which("ffprobe"):
        raise PluginError("ffprobe required for candidate MP4")
    result = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_read_frames", "-of", "json", str(path)],
         stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    if result.returncode or len(result.stdout) > 64_000:
        raise PluginError("ffprobe failed")
    data = strict_decode(result.stdout, 64_000)
    streams = data.get("streams", []) if isinstance(data, dict) else []
    if len(streams) != 1:
        raise PluginError("MP4 must have exactly one video stream")
    s = streams[0]
    try:
        frame_rate = Fraction(str(s["r_frame_rate"]))
        actual_frames = int(s["nb_read_frames"])
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise PluginError("invalid video stream metadata") from exc
    if (s.get("codec_name") != "h264" or s.get("width") != width or s.get("height") != height or
            frame_rate != fps or actual_frames != frames):
        raise PluginError("candidate MP4 does not match expected frame contract")


def inspect_ordr(data: Any) -> dict[str, Any]:
    exact(data, {"contract_version", "core_state_schema_version", "cursor", "world_time",
                 "observer", "reference_observer", "constraints", "regions"}, label="ORDR snapshot")
    if data["contract_version"] != "1.0.0" or data["core_state_schema_version"] != 1:
        raise PluginError("ORDR v1 contract required, no silent upgrade")
    cur = exact(data["cursor"], {"contract_version", "world_id", "state_fingerprint", "computation_frame"}, label="ORDR cursor")
    if cur["contract_version"] != "1.0.0" or not isinstance(cur["world_id"], str) or not cur["world_id"]:
        raise PluginError("ORDR cursor contract mismatch")
    uint(cur["state_fingerprint"], 0, 2**64-1, "ORDR cursor fingerprint")
    uint(cur["computation_frame"], 0, 2**64-1, "ORDR computation frame")
    if not isinstance(data["world_time"], (int, float)) or isinstance(data["world_time"], bool):
        raise PluginError("ORDR world_time invalid")
    if not (float("-inf") < data["world_time"] < float("inf")):
        raise PluginError("ORDR world_time nonfinite")
    regions = data["regions"]
    if not isinstance(regions, list) or not 1 <= len(regions) <= 64:
        raise PluginError("ORDR region scope must be finite 1..64")
    summaries, seen = [], set()
    allowed_fields = {"depth", "normal", "occlusion", "visibility"}
    for entry in regions:
        exact(entry, {"address", "materialized", "latent", "frontier", "demand", "pending_request",
                      "generated", "conflicts", "layers", "samples", "provenance"}, label="ORDR region")
        if entry["demand"] is not None or entry["pending_request"] is not None or entry["conflicts"] != []:
            raise PluginError("renderer profile rejects demand/pending/conflicts")
        addr = exact(entry["address"], {"space", "x", "y", "z", "lod"}, label="region address")
        if not isinstance(addr["space"], str) or not addr["space"]:
            raise PluginError("invalid ORDR canvas space")
        for key in ("x", "y", "z"):
            uint(addr[key], -(2**31), 2**31-1, key)
        uint(addr["lod"], 0, 255, "lod")
        key = (addr["space"], addr["x"], addr["y"], addr["z"], addr["lod"])
        if key in seen:
            raise PluginError("duplicate ORDR region")
        seen.add(key)
        if not isinstance(entry["layers"], list) or not isinstance(entry["samples"], list) or len(entry["layers"]) > 128 or len(entry["samples"]) > 128:
            raise PluginError("ORDR field transfer exceeds bounded budget")
        for field in entry["layers"] + entry["samples"]:
            if not isinstance(field, dict) or field.get("component") not in allowed_fields:
                raise PluginError("ORDR field not allowed by read-only renderer profile")
        summaries.append({"region": addr, "materialized": entry["materialized"] is not None,
                          "generated": entry["generated"] is not None,
                          "frontier": entry["frontier"] if entry["frontier"] is not None else None,
                          "visible_field_components": sorted({v["component"] for v in entry["layers"] + entry["samples"]})})
    return {"schema": "evedirector.ordr_region_projection.v1", "contract_version": "1.0.0",
            "cursor": {"world_id": cur["world_id"], "computation_frame": cur["computation_frame"],
                       "state_fingerprint": cur["state_fingerprint"]},
            "region_count": len(summaries), "regions": summaries,
            "coordinate_mapping": {"handedness": "right", "x": "image-right", "y": "image-down", "z": "forward"},
            "canonical_write": False, "diagnostic_only": True,
            "origin_verified_by_ordr_core": False,
            "note": "An offline bounded snapshot view, NOT an ORDR reconstruction or camera renderer."}


def _run_native(req: dict, input_root: Path, stage: Path) -> dict[str, Any]:
    # Import only an already-installed first-party renderer; no dynamic eval.
    sys.path.insert(0, str(ROOT / "scripts"))
    import evedirector_programmatic as r0
    plan_path = safe_relative(input_root, req["inputs"]["plan"])
    source_path = safe_relative(input_root, req["inputs"]["source"], MAX_INPUT)
    plan_raw, source_raw = plan_path.read_bytes(), source_path.read_bytes()
    plan = strict_decode(plan_raw)
    if not isinstance(plan, dict):
        raise PluginError("native program must be a JSON object")
    style = plan.get("style")
    if not isinstance(style, str) or not SLUG.fullmatch(style):
        raise PluginError("style must be an allow-listed slug")
    styles = ROOT / "styles"
    receipt = r0.validate(plan, source_raw, styles)
    stage.joinpath("styles").mkdir()
    stage.joinpath("styles", style+".yaml").write_bytes((styles / (style+".yaml")).read_bytes())
    (stage / "plan.json").write_bytes(plan_raw)
    (stage / "source.md").write_bytes(source_raw)
    render_info = r0.render(plan, receipt, stage / "candidate.mp4")
    (stage / "native_receipt.json").write_bytes(canonical(receipt))
    return {"engine": "evedirector-native-r0", "render_info_status": "RENDERED_CANDIDATE",
            "resolution": [plan["width"], plan["height"]], "fps": plan["fps"], "frames": plan["frames"],
            "source_sha256": digest(source_raw), "plan_sha256": digest(plan_raw),
            "note": "Source-grounded native R0 output; not human approved."}


def _run_evoe(req: dict, input_root: Path, stage: Path, external_root: Path | None, allow_external: bool) -> dict[str, Any]:
    if not allow_external or external_root is None:
        raise PluginError("EVOE runtime requires explicit --evoe-root and --allow-external")
    if external_root.is_symlink() or not external_root.is_dir() or not (external_root/"src/evoe/cli.py").is_file():
        raise PluginError("external EVOE root is missing or not a trusted local installation")
    scene = safe_relative(input_root, req["inputs"]["scene"], 512*1024)
    (stage / "scene.json").write_bytes(scene.read_bytes())
    inputs = req["inputs"]
    count = inputs["frame_count"]
    times = [i / (count-1) for i in range(count)]
    args = [sys.executable, "-B", "-m", "evoe.cli", "animate", "--scene", str(stage/"scene.json"),
            "--times", ",".join(format(t, ".14g") for t in times),
            "--size", str(inputs["size"]), "--samples", str(inputs["samples"]),
            "--output", str(stage/"frames")]
    # External code is user-installed; withhold API keys/tokens and do not run a shell.
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR") if k in os.environ}
    env.update({"PYTHONPATH": str((external_root/"src").resolve()), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"})
    proc = subprocess.run(args, cwd=stage, env=env, capture_output=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise PluginError(f"EVOE returned error code {proc.returncode}; see local engine logs")
    frames_meta = json_read(stage/"frames"/"frames.json", 100*1024)
    if not isinstance(frames_meta, dict) or frames_meta.get("schema") != "evoe.anim-sequence.v0.1":
        raise PluginError("EVOE did not return the v0.1 animation receipt")
    actual_times = frames_meta.get("frame_times")
    if not isinstance(actual_times,list) or len(actual_times) != count or any(abs(float(x)-y)>1e-8 for x,y in zip(actual_times,times)):
        raise PluginError("EVOE time samples do not match the requested schedule")
    if not isinstance(frames_meta.get("receipts"), list) or len(frames_meta["receipts"]) != count:
        raise PluginError("missing EVOE per-frame receipts")
    for i in range(count):
        if _png_dimensions(stage/"frames"/f"frame_{i:03d}.png") != (inputs["size"], inputs["size"]):
            raise PluginError("EVOE returned wrong frame dimensions")
    if not shutil.which("ffmpeg"):
        raise PluginError("ffmpeg required to assemble EVOE frames into MP4")
    command = ["ffmpeg", "-nostdin", "-v", "error", "-framerate", str(inputs["fps"]), "-i",
               str(stage/"frames"/"frame_%03d.png"), "-frames:v", str(count), "-an", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(stage/"candidate.mp4")]
    done = subprocess.run(command, cwd=stage, capture_output=True, timeout=120, check=False)
    if done.returncode:
        raise PluginError("FFmpeg refused to assemble EVOE frames")
    _check_artifact(stage/"candidate.mp4")
    _ffprobe(stage/"candidate.mp4", frames=count, fps=inputs["fps"], width=inputs["size"], height=inputs["size"])
    return {"engine": "evoe.external-cpu-reference.v0.1", "frame_count": count,
            "resolution": [inputs["size"], inputs["size"]], "fps": inputs["fps"],
            "source_sha256": digest(scene.read_bytes()), "external_code_executed_with_explicit_opt_in": True,
            "note": "EVOE produces geometry-derived frames; MP4 is a bounded downstream view, not canonical EVOE geometry."}


def _run_ordr(req: dict, input_root: Path, stage: Path) -> dict[str, Any]:
    source = safe_relative(input_root, req["inputs"]["snapshot"], MAX_SNAPSHOT)
    raw = source.read_bytes()
    summary = inspect_ordr(strict_decode(raw, MAX_SNAPSHOT))
    (stage / "ordr_snapshot.json").write_bytes(raw)
    (stage / "ordr_projection.json").write_bytes(canonical(summary))
    return {"engine": "ordr.contract.v1.read-only-offline", "source_sha256": digest(raw),
            "region_count": summary["region_count"], "coord_mapping": summary["coordinate_mapping"],
            "origin_verified_by_ordr_core": False, "note": "Snapshot transfer inspection; no ORDR Core operation invoked."}


def _files(stage: Path) -> dict[str, str]:
    out = {}
    for p in sorted(stage.rglob("*")):
        if p.is_symlink():
            raise PluginError("plugin produced symlink")
        if not p.is_file():
            continue
        rel = p.relative_to(stage).as_posix()
        if rel == "run-receipt.json":
            continue
        if len(out) >= MAX_TOTAL_FILES:
            raise PluginError("plugin produced too many files")
        out[rel] = _check_artifact(p, MAX_VIDEO)
    return out


def run(req: dict[str, Any], input_root: Path, output_root: Path,
        *, evoe_root: Path | None = None, allow_external: bool = False) -> dict[str, Any]:
    req = resolve_request(req)
    describe(req["plugin_id"])  # reject missing or changed reviewed plugin manifests
    if output_root.is_symlink():
        raise PluginError("output root may not be a symlink")
    output_root.mkdir(parents=True, exist_ok=True)
    if not output_root.is_dir():
        raise PluginError("output root must be a directory")
    # A subprocess runs with cwd=stage. Its scene/output arguments must be
    # absolute even when the user supplied a relative --output-root.
    output_root = output_root.resolve()
    dest = output_root / req["candidate_id"]
    if dest.exists() or dest.is_symlink():
        raise PluginError("candidate already exists; append-only jobs cannot be overwritten")
    stage = Path(tempfile.mkdtemp(prefix=".staging-plugin-", dir=output_root))
    try:
        (stage / "request.json").write_bytes(canonical(req))
        if req["plugin_id"] == "native-r0":
            result = _run_native(req, input_root, stage)
        elif req["plugin_id"] == "evoe":
            result = _run_evoe(req, input_root, stage, evoe_root, allow_external)
        else:
            result = _run_ordr(req, input_root, stage)
        hashes = _files(stage)
        receipt = {"schema": RECEIPT_SCHEMA, "candidate_id": req["candidate_id"],
                   "plugin_id": req["plugin_id"], "operation": req["operation"],
                   "candidate_only": True, "review_required": True, "canonical_write": False,
                   "network_requested": False, "published": False,
                   "inputs_sha256": hashes.get("request.json"), "files_sha256": hashes,
                   "result": result, "verification": "EVIDENCE_RECORDED_NOT_HUMAN_APPROVED"}
        (stage / "run-receipt.json").write_bytes(canonical(receipt))
        if dest.exists() or dest.is_symlink():
            raise PluginError("candidate appeared during staging")
        stage.rename(dest)
        return receipt
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify(run_dir: Path) -> dict[str, Any]:
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise PluginError("run directory unsafe")
    receipt = json_read(run_dir/"run-receipt.json", MAX_REQUEST)
    exact(receipt, {"schema", "candidate_id", "plugin_id", "operation", "candidate_only", "review_required",
                   "canonical_write", "network_requested", "published", "inputs_sha256", "files_sha256",
                   "result", "verification"}, label="run receipt")
    if (receipt["schema"] != RECEIPT_SCHEMA or receipt["candidate_id"] != run_dir.name or
        receipt["candidate_only"] is not True or receipt["review_required"] is not True or
        receipt["canonical_write"] is not False or receipt["published"] is not False or
        receipt["network_requested"] is not False):
        raise PluginError("invalid candidate receipt authority")
    req = resolve_request(json_read(run_dir/"request.json", MAX_REQUEST))
    if req["plugin_id"] != receipt["plugin_id"] or req["operation"] != receipt["operation"]:
        raise PluginError("receipt request mismatch")
    hashes = _files(run_dir)
    if hashes != receipt["files_sha256"] or hashes.get("request.json") != receipt["inputs_sha256"]:
        raise PluginError("run artifact hashes changed")
    if req["plugin_id"] == "native-r0":
        sys.path.insert(0, str(ROOT / "scripts"))
        import evedirector_programmatic as r0
        program = json_read(run_dir/"plan.json")
        source = (run_dir/"source.md").read_bytes()
        expected = r0.validate(program, source, run_dir/"styles")
        observed = json_read(run_dir/"native_receipt.json")
        if canonical(expected) != canonical(observed):
            raise PluginError("native source-derived receipt mismatch")
        _ffprobe(run_dir/"candidate.mp4", frames=program["frames"], fps=program["fps"], width=program["width"], height=program["height"])
    elif req["plugin_id"] == "evoe":
        spec=req["inputs"]; meta=json_read(run_dir/"frames"/"frames.json", 100*1024)
        if meta.get("schema") != "evoe.anim-sequence.v0.1" or len(meta.get("receipts",[])) != spec["frame_count"]:
            raise PluginError("EVOE frame manifest changed")
        for i in range(spec["frame_count"]):
            if _png_dimensions(run_dir/"frames"/f"frame_{i:03d}.png") != (spec["size"],spec["size"]):
                raise PluginError("EVOE PNG size changed")
        _ffprobe(run_dir/"candidate.mp4",frames=spec["frame_count"],fps=spec["fps"],width=spec["size"],height=spec["size"])
    else:
        raw=(run_dir/"ordr_snapshot.json").read_bytes()
        actual=inspect_ordr(strict_decode(raw, MAX_SNAPSHOT))
        if canonical(actual) != (run_dir/"ordr_projection.json").read_bytes():
            raise PluginError("ORDR projection differs from source snapshot")
    return {"candidate_id": req["candidate_id"], "status": "PASS_BOUNDED_REPLAY",
            "scope": "run files, schema and available static receipts; not semantic truth or human approval",
            "canonical_write": False, "published": False}


def doctor(plugin: str, evoe_root: Path | None = None) -> dict[str, Any]:
    ident(plugin)
    if plugin not in IMPLEMENTED:
        raise PluginError("unknown plugin")
    if plugin == "native-r0":
        available = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
        return {"plugin_id":plugin,"available":available,"requires":["pillow", "pyyaml", "ffmpeg", "ffprobe"]}
    if plugin == "ordr":
        return {"plugin_id":plugin,"available":True,"mode":"offline-snapshot-consumer",
                "ordr_core_connected":False,"can_write_canonical":False}
    available = evoe_root is not None and evoe_root.is_dir() and not evoe_root.is_symlink() and (evoe_root/"src/evoe/cli.py").is_file()
    return {"plugin_id":plugin,"available":bool(available),"mode":"explicit-local-external-execution",
            "requires":["EVOE source installed separately", "--evoe-root", "--allow-external", "ffmpeg", "ffprobe"],
            "plugin_executed":False}


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description="EveDirector R9 bounded AI-native plugin host")
    cmd=p.add_subparsers(dest="command",required=True)
    cmd.add_parser("catalog")
    desc=cmd.add_parser("describe");desc.add_argument("--plugin",required=True)
    dr=cmd.add_parser("doctor");dr.add_argument("--plugin",required=True);dr.add_argument("--evoe-root",type=Path)
    rv=cmd.add_parser("validate");rv.add_argument("--request",required=True,type=Path)
    run_cmd=cmd.add_parser("run");run_cmd.add_argument("--request",required=True,type=Path)
    run_cmd.add_argument("--input-root",required=True,type=Path)
    run_cmd.add_argument("--output-root",required=True,type=Path)
    run_cmd.add_argument("--evoe-root",type=Path);run_cmd.add_argument("--allow-external",action="store_true")
    verify_cmd=cmd.add_parser("verify");verify_cmd.add_argument("--run-dir",required=True,type=Path)
    args=p.parse_args(argv)
    try:
        if args.command=="catalog":
            result={"schema":"evedirector.plugin_catalog.v1","plugins":catalog(),"network_execution":False}
        elif args.command=="describe":
            result=describe(args.plugin)
            if result is None:raise PluginError("plugin not registered")
        elif args.command=="doctor":result=doctor(args.plugin,args.evoe_root)
        elif args.command=="validate":result={"status":"VALID_REQUEST_ONLY","request":resolve_request(json_read(args.request,MAX_REQUEST))}
        elif args.command=="run":result=run(json_read(args.request,MAX_REQUEST),args.input_root,args.output_root,
                                               evoe_root=args.evoe_root,allow_external=args.allow_external)
        else:result=verify(args.run_dir)
        print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
        return 0
    except (PluginError, OSError, ValueError, ImportError, subprocess.TimeoutExpired) as exc:
        print(f"PLUGIN_REJECTED: {exc}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
