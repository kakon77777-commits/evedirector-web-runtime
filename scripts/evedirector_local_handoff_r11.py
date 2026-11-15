#!/usr/bin/env python3
"""R11 local engine integration handoff. External EVOE runs only after opt-in.
ORDR is a bounded offline read-only snapshot, not a reconstructed 3D renderer.
No private engine source or absolute local engine path is exported.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_plugin_hub as hub
import evedirector_scene_ir_r10 as r10

SCHEMA = 'evedirector.local_integration_handoff.v1'
INPUT_FILES = (
    'program.json', 'source/README.md', 'source/r10-plugin-composition.md',
    'plugins/native-r0.request.json', 'plugins/r10-evoe-60.request.json',
    'plugins/ordr-snapshot.request.json', 'plugins/r10-composition.draft.json',
    'plugins/evoe-demo.scene.json', 'plugins/ordr-synthetic-snapshot.json',
)
RUN_IDS = ('native_demo_r9', 'evoe_geometry_demo_r10', 'ordr_snapshot_demo_r9')
MAX_ENGINE_SOURCE = 2_000_000

class HandoffError(ValueError):
    pass

def _root(path: Path, *, required: tuple[str, ...] = ()) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise HandoffError('local engine root absent, unsafe or linked')
    resolved = path.resolve(strict=True)
    for name in required:
        file = resolved / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_ENGINE_SOURCE:
            raise HandoffError('local engine contract files absent, linked or oversized')
        if not file.resolve().is_relative_to(resolved):
            raise HandoffError('contract file escapes engine root')
    return resolved

def _git_head(root: Path) -> str | None:
    if not shutil.which('git'):
        return None
    try:
        proc = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                              text=True, capture_output=True, timeout=8, check=False)
        rev = proc.stdout.strip()
        return rev if proc.returncode == 0 and re.fullmatch('[0-9a-f]{40}', rev) else None
    except (OSError, subprocess.TimeoutExpired):
        return None

def _fingerprint(path: Path | None, contract_files: tuple[str, ...], engine: str) -> dict[str, Any]:
    if path is None:
        return {'engine': engine, 'installed': False, 'source_identity_verified': False}
    root = _root(path, required=contract_files)
    return {
        'engine': engine, 'installed': True,
        'contract_files_sha256': {name: hub.digest((root / name).read_bytes()) for name in contract_files},
        'git_head_claim': _git_head(root),
        'source_identity_verified': False, 'private_source_embedded': False,
    }

def doctor(evoe_root: Path | None = None, ordr_core: Path | None = None,
           ordr_adapters: Path | None = None) -> dict[str, Any]:
    evoe = _fingerprint(evoe_root, ('src/evoe/cli.py', 'src/evoe/spec.py', 'src/evoe/render.py'), 'EVOE')
    core = _fingerprint(ordr_core, ('Cargo.toml', 'src/adapter.rs'), 'ORDR-Core')
    adapter = _fingerprint(ordr_adapters, ('Cargo.toml', 'src/lib.rs'), 'ORDR-Adapters')
    if ordr_adapters is not None and ordr_core is None:
        raise HandoffError('ORDR-Adapters inspection requires matching ORDR-Core root')
    return {
        'schema': 'evedirector.local_engine_doctor.v1',
        'native_media_tools': {'ffmpeg': bool(shutil.which('ffmpeg')),
                               'ffprobe': bool(shutil.which('ffprobe'))},
        'engines': [evoe, core, adapter],
        'evoe_cli_ready': evoe['installed'],
        'ordr_v1_contract_inspectable': core['installed'] and adapter['installed'],
        'ordr_core_executed': False, 'external_code_executed': False,
        'privacy': 'No external source files or absolute engine paths included in receipts',
    }

def _source_copy(source_root: Path, target: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in INPUT_FILES:
        source = hub.safe_relative(source_root, name, 2_000_000)
        data = source.read_bytes()
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as f:
            f.write(data)
        hashes[name] = hub.digest(data)
    return hashes

def _checked_dir(directory: Path) -> Path:
    if directory.is_symlink() or not directory.is_dir():
        raise HandoffError('handoff directory missing or symlinked')
    for item in directory.rglob('*'):
        if item.is_symlink():
            raise HandoffError('handoff contains a linked artifact')
    return directory

def _inputs_pin(directory: Path) -> dict[str, str]:
    _checked_dir(directory)
    return {name: hub.digest(hub.safe_relative(directory, name, 2_000_000).read_bytes()) for name in INPUT_FILES}

def stage(*, input_root: Path, output_root: Path, candidate_id: str,
          evoe_root: Path | None, allow_local_engines: bool,
          ordr_core: Path | None = None, ordr_adapters: Path | None = None) -> dict[str, Any]:
    hub.ident(candidate_id, 'local handoff id')
    if not allow_local_engines or evoe_root is None:
        raise HandoffError('explicit --allow-local-engines and --evoe-root required')
    checks = doctor(evoe_root, ordr_core, ordr_adapters)
    if not checks['native_media_tools']['ffmpeg'] or not checks['native_media_tools']['ffprobe']:
        raise HandoffError('FFmpeg and FFprobe required for local integration')
    if input_root.is_symlink() or not input_root.is_dir():
        raise HandoffError('input root must be an existing nonlinked directory')
    if output_root.is_symlink():
        raise HandoffError('output root cannot be a symlink')
    output_resolved = output_root.resolve()
    for protected in (input_root, evoe_root, ordr_core, ordr_adapters):
        if protected is not None and output_resolved.is_relative_to(protected.resolve()):
            raise HandoffError('output root must be outside protected input/engine checkouts')
    output_root.mkdir(parents=True, exist_ok=True)
    _checked_dir(output_root)
    dest = output_root / candidate_id
    if dest.exists() or dest.is_symlink():
        raise HandoffError('candidate exists; integration handoffs are append-only')
    temp = Path(tempfile.mkdtemp(prefix='.r11-staging-', dir=output_root))
    try:
        inputs = temp / 'inputs'
        inputs.mkdir()
        input_hashes = _source_copy(input_root, inputs)
        runs = temp / 'runs'
        for name in ('native-r0.request.json', 'r10-evoe-60.request.json', 'ordr-snapshot.request.json'):
            request = hub.json_read(inputs / 'plugins' / name, hub.MAX_REQUEST)
            hub.run(request, inputs, runs, evoe_root=evoe_root, allow_external=allow_local_engines)
        for name in RUN_IDS:
            hub.verify(runs / name)
        draft = hub.json_read(inputs / 'plugins' / 'r10-composition.draft.json', r10.MAX_DRAFT)
        if draft['candidate_id'] != 'r10_native_evoe_ordr_composite':
            raise HandoffError('R10 integration draft identity differs from reviewed example')
        ir = r10.lock(draft, inputs, runs)
        (temp / 'scene-ir.locked.json').write_bytes(hub.canonical(ir))
        composed = r10.compose(ir, inputs, runs, temp / 'composition')
        r10.verify(temp / 'composition' / ir['candidate_id'], inputs, runs)
        result = {
            'schema': SCHEMA, 'candidate_id': candidate_id,
            'input_sha256': input_hashes, 'engine_fingerprints': checks['engines'],
            'runs_sha256': {name: hub.digest((runs / name / 'run-receipt.json').read_bytes()) for name in RUN_IDS},
            'scene_ir_sha256': hub.digest((temp / 'scene-ir.locked.json').read_bytes()),
            'composition_receipt_sha256': hub.digest((temp / 'composition' / ir['candidate_id'] / 'compose-receipt.json').read_bytes()),
            'composite_mp4_sha256': composed['mp4_sha256'],
            'evoe_subprocess_executed': True,
            'evoe_engine_authenticity_independently_verified': False,
            'ordr_snapshot_is_replayable': True, 'ordr_core_executed': False,
            'ordr_source_authenticity_verified': False, 'canonical_write': False,
            'published': False, 'human_approved': False,
            'verification_scope': 'R9/R10 local artifact replay + local source fingerprints; not engine signature, independent rerender or human approval',
        }
        (temp / 'handoff-receipt.json').write_bytes(hub.canonical(result))
        if dest.exists() or dest.is_symlink():
            raise HandoffError('handoff destination appeared during staging')
        temp.rename(dest)
        return result
    finally:
        if temp.exists():
            shutil.rmtree(temp)

def verify(candidate_dir: Path) -> dict[str, Any]:
    directory = _checked_dir(candidate_dir)
    receipt = hub.json_read(directory / 'handoff-receipt.json', hub.MAX_INPUT)
    hub.exact(receipt, {
        'schema', 'candidate_id', 'input_sha256', 'engine_fingerprints', 'runs_sha256',
        'scene_ir_sha256', 'composition_receipt_sha256', 'composite_mp4_sha256',
        'evoe_subprocess_executed', 'evoe_engine_authenticity_independently_verified',
        'ordr_snapshot_is_replayable', 'ordr_core_executed', 'ordr_source_authenticity_verified',
        'canonical_write', 'published', 'human_approved', 'verification_scope',
    })
    if (receipt['schema'] != SCHEMA or receipt['candidate_id'] != directory.name or
        receipt['canonical_write'] is not False or receipt['published'] is not False or
        receipt['human_approved'] is not False or
        receipt['evoe_subprocess_executed'] is not True or
        receipt['ordr_snapshot_is_replayable'] is not True or
        receipt['evoe_engine_authenticity_independently_verified'] is not False or
        receipt['ordr_core_executed'] is not False or
        receipt['ordr_source_authenticity_verified'] is not False or
        not isinstance(receipt['engine_fingerprints'], list) or
        [x.get('engine') for x in receipt['engine_fingerprints'] if isinstance(x, dict)]
          != ['EVOE', 'ORDR-Core', 'ORDR-Adapters'] or
        receipt['engine_fingerprints'][0].get('installed') is not True or
        any(x.get('source_identity_verified') is not False for x in receipt['engine_fingerprints'])):
        raise HandoffError('handoff receipt violates candidate authority')
    inputs = directory / 'inputs'
    hashes = _inputs_pin(inputs)
    if hashes != receipt['input_sha256']:
        raise HandoffError('handoff input hashes changed')
    runs = directory / 'runs'
    expected_runs = {name: hub.digest((runs / name / 'run-receipt.json').read_bytes()) for name in RUN_IDS}
    if expected_runs != receipt['runs_sha256']:
        raise HandoffError('plugin receipt hashes changed')
    for name in RUN_IDS:
        hub.verify(runs / name)
    pinned = directory / 'scene-ir.locked.json'
    if pinned.is_symlink() or not pinned.is_file() or hub.digest(pinned.read_bytes()) != receipt['scene_ir_sha256']:
        raise HandoffError('Scene IR lock hash changed')
    ir = hub.json_read(pinned, r10.MAX_DRAFT)
    r10.replay(ir, inputs, runs)
    dest = directory / 'composition' / ir['candidate_id']
    result = r10.verify(dest, inputs, runs)
    if (hub.digest((dest / 'compose-receipt.json').read_bytes()) != receipt['composition_receipt_sha256']
            or result['composition_sha256'] != receipt['composite_mp4_sha256']):
        raise HandoffError('composition receipt hash changed')
    return {
        'schema': 'evedirector.local_handoff_verification.v1',
        'status': 'PASS_BOUNDED_OFFLINE_REPLAY', 'candidate_id': directory.name,
        'real_evoe_authenticity_attested': False,
        'ordr_core_executed_in_this_handoff': False,
        'canonical_write': False, 'human_approved': False, 'published': False,
        'engine_rerun_performed': False,
    }

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='EveDirector R11 Windows/local engine integration handoff')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('doctor', 'stage'):
        s = sub.add_parser(name)
        s.add_argument('--evoe-root', type=Path)
        s.add_argument('--ordr-core-root', type=Path)
        s.add_argument('--ordr-adapters-root', type=Path)
        if name == 'stage':
            s.add_argument('--input-root', type=Path, default=Path(__file__).resolve().parents[1] / 'examples' / 'native-video')
            s.add_argument('--output-root', type=Path, required=True)
            s.add_argument('--candidate-id', type=str, required=True)
            s.add_argument('--allow-local-engines', action='store_true')
    v = sub.add_parser('verify')
    v.add_argument('--candidate-dir', required=True, type=Path)
    a = p.parse_args(argv)
    try:
        if a.command == 'doctor':
            result = doctor(a.evoe_root, a.ordr_core_root, a.ordr_adapters_root)
        elif a.command == 'stage':
            result = stage(input_root=a.input_root, output_root=a.output_root,
                           candidate_id=a.candidate_id, evoe_root=a.evoe_root,
                           allow_local_engines=a.allow_local_engines,
                           ordr_core=a.ordr_core_root, ordr_adapters=a.ordr_adapters_root)
        else:
            result = verify(a.candidate_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (HandoffError, hub.PluginError, r10.SceneIRError, OSError, ValueError,
            TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        print('R11_HANDOFF_REJECTED: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
