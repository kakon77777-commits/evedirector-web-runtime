#!/usr/bin/env python3
"""R5 bounded multilingual font and sampled glyph presence verifier.

Only opt-in Noto Sans CJK TC font-profile layers are eligible. Source/plan/video
must first be replayed by R2. A PASS means a limited sample of CJK/Latin ink
and background agrees under an attested local font face; NOT OCR, exact
character equivalence, all frames, typography approval or publishing rights.
Font files are never copied to report, repository, or distribution archives.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evedirector_review_stage as stage
import evedirector_visual_probe as r3
import evedirector_text_layers_r4 as r4

SCHEMA = 'evedirector.multilingual_glyph_probe.v0.1'
METHOD = 'noto-cjk-tc-glyph-evidence-v0.1'
RECORD_DIR = 'programmatic_multilang_checks'
PROFILE = 'noto-cjk-tc-v1'
FAMILY = 'Noto Sans CJK TC'
MAX_FONT_BYTES = 32_000_000
MAX_REPORT_BYTES = 500_000
MAX_FRAMES = 30
MAX_MEMORY = 48 * 1024 * 1024
MAX_PIXELS_PER_LINE = 320
MAX_SHIFT = 12
MIN_INK = 25
MIN_BLANK = 15
INK_PASS = 0.88
BLANK_PASS = 0.88


class MultilangProbeError(ValueError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as inp:
        for chunk in iter(lambda: inp.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=1)
def font_environment() -> dict[str, Any]:
    """Require OS fontconfig to select the exact CJK-TC face (no fallback)."""
    try:
        info = subprocess.run(
            ['fc-match', '-f', '%{file}\n%{index}\n%{family}\n', FAMILY],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip().splitlines()
        if len(info) != 3:
            raise MultilangProbeError('fontconfig returned malformed profile')
        path = Path(info[0])
        face_index = int(info[1])
        if (FAMILY not in info[2].split(',') or not path.is_file() or path.is_symlink()
                or path.stat().st_size > MAX_FONT_BYTES or face_index not in range(0, 32)):
            raise MultilangProbeError('Noto Sans CJK TC font face missing or unsafe')
        from fontTools.ttLib import TTFont
        face = TTFont(str(path), fontNumber=face_index, lazy=True)
        try:
            name_table = face['name']
            cmap = face.getBestCmap() or {}
            # Stronger than trusting the filename: explicitly require core TC glyphs.
            if any(ord(ch) not in cmap for ch in '繁體中文程式生成影片字幕測試標題英混排'):
                raise MultilangProbeError('font face lacks required traditional Chinese glyphs')
        finally:
            face.close()
        return {'profile': PROFILE, 'family': FAMILY, 'face_index': face_index,
                'font_sha256': _sha(path), 'font_bytes': path.stat().st_size,
                'file': str(path)}  # `file` MUST NOT be serialized in public reports.
    except (ImportError, FileNotFoundError, OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError,
            ValueError, KeyError) as exc:
        raise MultilangProbeError('verified Noto Sans CJK TC font unavailable') from exc


@lru_cache(maxsize=1)
def supported_characters() -> frozenset[int]:
    env = font_environment()
    from fontTools.ttLib import TTFont
    font = TTFont(env['file'], fontNumber=env['face_index'], lazy=True)
    try:
        return frozenset((font.getBestCmap() or {}).keys())
    finally:
        font.close()


def _frames(bundle: dict[str, Any]) -> list[int]:
    size = bundle['width'] * bundle['height'] * 3
    if not 0 < size <= MAX_MEMORY:
        raise MultilangProbeError('oversized RGB frame')
    total = bundle['durationInFrames']
    limit = min(MAX_FRAMES, total, MAX_MEMORY // size)
    if limit < len(bundle['clips']):
        raise MultilangProbeError('insufficient bounded frame coverage')
    frames = {round((total - 1) * i / max(1, limit - 1)) for i in range(limit)}
    for clip in bundle['clips']:
        frames.add(clip['from'] + clip['durationInFrames'] // 2)
    if len(frames) > limit:
        mandatory = {c['from'] + c['durationInFrames'] // 2 for c in bundle['clips']}
        rest = sorted(frames - mandatory)
        n = limit - len(mandatory)
        frames = mandatory | {rest[round((len(rest) - 1) * j / max(1, n - 1))] for j in range(n)}
    return sorted(frames)


def _points(face: ImageFont.FreeTypeFont, text: str) -> tuple[list[tuple[int,int]], list[tuple[int,int]], int, int]:
    bbox = face.getbbox(text)
    if bbox is None:
        raise MultilangProbeError('empty glyph bbox')
    x0, y0, x1, y1 = bbox
    w, h = x1-x0+6, y1-y0+6
    if not 0 < w <= 850 or not 0 < h <= 180:
        raise MultilangProbeError('text glyph bounds exceed local probe limits')
    mask = Image.new('L', (w, h))
    ImageDraw.Draw(mask).text((3-x0, 3-y0), text, font=face, fill=255)
    ink, blank = [], []
    pix = mask.load()
    for y in range(1, h-1):
        for x in range(1, w-1):
            value = pix[x,y]
            if value >= 225:
                ink.append((x+x0-3, y+y0-3))
            elif value <= 6:
                # Restrict background evidence to the actual glyph bbox.
                if 3 <= x < w-3 and 3 <= y < h-3:
                    blank.append((x+x0-3, y+y0-3))
    def thin(points: list[tuple[int,int]], budget: int) -> list[tuple[int,int]]:
        if len(points) <= budget:
            return points
        return [points[i*(len(points)-1)//(budget-1)] for i in range(budget)]
    return thin(ink, 200), thin(blank, 120), w, h


def _measure_line(bundle: dict, clip: dict, local: int, layer_index: int,
                  decoded: bytes, face: ImageFont.FreeTypeFont, line: str,
                  line_no: int) -> dict[str, Any]:
    layer = clip['layers'][layer_index]
    g = r3._geometry_at(layer, local)
    width, height = bundle['width'], bundle['height']
    x0 = int(g['x'])
    y0 = int(g['y']) + int(round(line_no * 1.2 * layer['font_size']))
    if layer['font_size'] < 36:
        return {'status': 'INCONCLUSIVE', 'reason': 'font-size-below-calibrated-range'}
    if g['opacity'] < .9:
        return {'status': 'INCONCLUSIVE', 'reason': 'low-opacity-or-keyframe-transition'}
    if x0 < 4 or y0 < 4 or x0 >= width - 25 or y0 >= height - 45:
        return {'status': 'INCONCLUSIVE', 'reason': 'outside-supported-canvas'}
    if any(ord(ch) not in supported_characters() for ch in line if ch != ' '):
        return {'status': 'INCONCLUSIVE', 'reason': 'font-glyph-coverage-missing'}
    try:
        ink, blank, w, h = _points(face, line)
    except (OSError, ValueError, MultilangProbeError):
        return {'status': 'INCONCLUSIVE', 'reason': 'unsupported-font-raster'}
    if x0 + w > width - 5 or y0 + h > height - 5:
        return {'status': 'INCONCLUSIVE', 'reason': 'line-would-wrap-or-clip'}
    if len(ink) < MIN_INK or len(blank) < MIN_BLANK:
        return {'status': 'INCONCLUSIVE', 'reason': 'insufficient-glyph-ink-or-negative-space'}
    fg = r4._rgb(layer['fill'], bundle['palette'])
    # Font ascenders and line-box baselines are rasterizer-dependent, but the
    # within-line ink/negative-space pattern should remain locally comparable.
    best: tuple[float, float, float, int, int, int, int] | None = None
    for dy in range(-MAX_SHIFT, MAX_SHIFT+1, 2):
        for dx in (-2, 0, 2):
            hit_ink = hit_blank = cnt_ink = cnt_blank = 0
            for kind, positions in ((1, ink), (0, blank)):
                for sx,sy in positions:
                    x, y = x0+sx+dx, y0+sy+dy
                    if not (1 <= x < width-1 and 1 <= y < height-1):
                        continue
                    # Unmodelled post-text geometry or later text is not evidence.
                    if any(other['kind'] == 'text' and
                           r3._geometry_at(other,local)['x'] - 3 <= x <
                           r3._geometry_at(other,local)['x'] + max(
                               len(s) for s in other['text'].split('\n')) * other['font_size'] * 1.4 and
                           r3._geometry_at(other,local)['y'] - 3 <= y <
                           r3._geometry_at(other,local)['y'] +
                           len(other['text'].split('\n')) * other['font_size'] * 1.5
                           for other in clip['layers'][layer_index+1:]):
                        continue
                    if any(other['kind'] != 'text' and r4._shape_cover(other, local, x, y)[0]
                           for other in clip['layers'][layer_index+1:]):
                        continue
                    base, edge = r4._geometry_color(bundle, clip['layers'], local, x, y,
                                                     stop=layer_index)
                    if edge:
                        continue
                    direction = [g['opacity']*(fg[j]-base[j]) for j in range(3)]
                    norm = sum(v*v for v in direction)
                    if norm < 2500:
                        continue
                    off = (y*width+x)*3
                    rgb = decoded[off:off+3]
                    ratio = sum((rgb[j]-base[j])*direction[j] for j in range(3))/norm
                    if kind:
                        cnt_ink += 1
                        if ratio > .45:
                            hit_ink += 1
                    else:
                        cnt_blank += 1
                        if ratio < .35:
                            hit_blank += 1
            if cnt_ink < MIN_INK or cnt_blank < MIN_BLANK:
                continue
            recall = hit_ink / cnt_ink
            precision = hit_blank / cnt_blank
            quality = .7 * recall + .3 * precision
            candidate = (quality, recall, precision, dx, dy, cnt_ink, cnt_blank)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None:
        return {'status': 'INCONCLUSIVE', 'reason': 'insufficient-visible-sampled-ink'}
    quality, recall, precision, dx, dy, cnt_ink, cnt_blank = best
    status = 'PASS' if recall >= INK_PASS and precision >= BLANK_PASS else 'FAIL'
    return {'status': status, 'reason': '' if status == 'PASS' else 'multilingual-glyph-evidence-mismatch',
            'ink_ratio': round(recall, 5), 'blank_ratio': round(precision, 5),
            'quality': round(quality, 5), 'shift': [dx,dy],
            'ink_points': cnt_ink, 'blank_points': cnt_blank}


def inspect(item: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    if item['video_path'] is None or item['manifest'].get('video') is None:
        raise MultilangProbeError('R2 candidate has no hash-verified MP4')
    bundle = item['props']['bundle']
    layers = [(clip, layer) for clip in bundle['clips'] for layer in clip['layers']
              if layer['kind'] == 'text' and layer.get('font_profile') == PROFILE]
    if not layers:
        raise MultilangProbeError('R5 requires explicit Noto Sans CJK TC text layer')
    try:
        env = font_environment()
    except MultilangProbeError:
        # A missing contracted font is a *measured limitation*, not a PASS
        # and not an excuse to substitute a local fallback silently.
        return {
            'schema': SCHEMA, 'method': METHOD, 'candidate_id': candidate_id,
            'status': 'INCONCLUSIVE_MULTILINGUAL_TEXT',
            'candidate_only': True, 'approved_for_publish': False,
            'visual_equivalence_attested': False,
            'scope': 'font-contract-unavailable-no-glyph-verification',
            'excluded': ['all-glyph-measurements', 'fallback-fonts', 'OCR', 'release-approval'],
            'pins': {'source_sha256': item['manifest']['source_sha256'],
                     'program_sha256': item['manifest']['program_sha256'],
                     'props_sha256': item['manifest']['props_sha256'],
                     'video_sha256': item['manifest']['video']['sha256']},
            'font': {'profile': PROFILE, 'family': FAMILY, 'availability': 'MISSING',
                     'font_file_embedded': False},
            'sampled_frames': [], 'total_frames': bundle['durationInFrames'],
            'declared_text_lines': sum(len(l['text'].split('\n')) for _,l in layers),
            'covered_text_lines': 0, 'unmeasured_samples': 0,
            'failed_samples': 0, 'checks': [],
        }
    frames = _frames(bundle)
    images = r3._decode_frames(item['video_path'], frames, bundle['width'], bundle['height'])
    checks: list[dict[str, Any]] = []
    face_cache: dict[int, ImageFont.FreeTypeFont] = {}
    for frame, data in zip(frames, images):
        clip = r3._active_clip(bundle, frame)
        local = frame - clip['from']
        for i, layer in enumerate(clip['layers']):
            if layer['kind'] != 'text' or layer.get('font_profile') != PROFILE:
                continue
            font_size = layer['font_size']
            if font_size not in face_cache:
                face_cache[font_size] = ImageFont.truetype(env['file'], font_size,
                                                           index=env['face_index'])
            for line_no, line in enumerate(layer['text'].split('\n')):
                result = _measure_line(bundle, clip, local, i, data, face_cache[font_size], line, line_no)
                checks.append({'frame': frame, 'clip_id': clip['id'], 'layer_id': layer['id'],
                               'line': line_no, **result})
    if not checks:
        raise MultilangProbeError('R5 contains no sampled text rows')
    expected = {(c['id'],layer['id'],j) for c in bundle['clips'] for layer in c['layers']
                if layer['kind'] == 'text' and layer.get('font_profile') == PROFILE
                for j in range(len(layer['text'].split('\n')))}
    passed = {(r['clip_id'],r['layer_id'],r['line']) for r in checks if r['status'] == 'PASS'}
    failed = any(r['status'] == 'FAIL' for r in checks)
    status = ('FAIL_SAMPLED_MULTILINGUAL_TEXT' if failed else
              'INCONCLUSIVE_MULTILINGUAL_TEXT' if not expected.issubset(passed) else
              'PASS_SAMPLED_MULTILINGUAL_TEXT')
    manifest = item['manifest']
    return {
        'schema': SCHEMA, 'method': METHOD, 'candidate_id': candidate_id, 'status': status,
        'candidate_only': True, 'approved_for_publish': False,
        'visual_equivalence_attested': False,
        'scope': 'sampled-high-contrast-noto-cjk-tc-ink-and-negative-space-only',
        'excluded': ['OCR', 'semantic-identity', 'complex-shaping', 'bidi', 'vertical-text',
                     'all-frames', 'pixel-perfect-font-matching', 'audio', 'release-approval'],
        'pins': {'source_sha256': manifest['source_sha256'],
                 'program_sha256': manifest['program_sha256'],
                 'props_sha256': manifest['props_sha256'],
                 'video_sha256': manifest['video']['sha256']},
        'font': {'profile': PROFILE, 'family': FAMILY, 'sha256': env['font_sha256'],
                 'index': env['face_index'], 'bytes': env['font_bytes'],
                 'font_file_embedded': False},
        'sampled_frames': frames, 'total_frames': bundle['durationInFrames'],
        'declared_text_lines': len(expected), 'covered_text_lines': len(passed),
        'unmeasured_samples': sum(x['status']=='INCONCLUSIVE' for x in checks),
        'failed_samples': sum(x['status']=='FAIL' for x in checks),
        'checks': checks,
    }


def _root(projects_dir: Path, project_id: str, candidate_id: str) -> Path:
    project = stage._ensure_project(projects_dir, project_id)
    stage.checked_id(candidate_id)
    return project / RECORD_DIR / candidate_id


def store(projects_dir: Path, project_id: str, candidate_id: str, result: dict[str, Any]) -> Path:
    root = _root(projects_dir, project_id, candidate_id)
    if root.exists() or root.is_symlink():
        raise MultilangProbeError('R5 report already exists; choose a new candidate id')
    root.parent.mkdir(exist_ok=True)
    stage._require_plain_dir(root.parent, root.parent.parent)
    raw = stage.canonical(result)
    if len(raw) > MAX_REPORT_BYTES:
        raise MultilangProbeError('R5 report oversized')
    root.mkdir()
    path = root / (stage.digest(raw)+'.json')
    path.write_bytes(raw)
    return path


def load_report(projects_dir: Path, project_id: str, candidate_id: str,
                item: dict[str, Any]) -> dict[str, Any] | None:
    root = _root(projects_dir, project_id, candidate_id)
    if not root.parent.exists():
        return None
    project = stage._ensure_project(projects_dir, project_id)
    stage._require_plain_dir(root.parent, project)
    if not root.exists():
        return None
    stage._require_plain_dir(root, root.parent)
    files = list(root.iterdir())
    if len(files) != 1:
        raise MultilangProbeError('R5 report directory ambiguous')
    path = files[0]
    if (path.is_symlink() or not path.is_file() or not re.fullmatch(r'[a-f0-9]{64}\.json',path.name)
            or path.stat().st_size > MAX_REPORT_BYTES):
        raise MultilangProbeError('unsafe R5 report')
    raw = path.read_bytes()
    if stage.digest(raw) != path.stem:
        raise MultilangProbeError('R5 report SHA mismatch')
    reported = stage.bridge.read_strict_json(path, MAX_REPORT_BYTES)
    expected = inspect(item, candidate_id)
    if stage.canonical(reported) != stage.canonical(expected):
        raise MultilangProbeError('R5 report differs from fresh font/video measurement')
    return reported


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='EveDirector R5 multilingual glyph probe')
    parser.add_argument('action', choices=['check','verify'])
    parser.add_argument('--projects-dir',type=Path,default=Path(__file__).resolve().parents[1]/'projects')
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--candidate-id',required=True)
    args = parser.parse_args(argv)
    try:
        item = stage.load_package(args.projects_dir,args.project_id,args.candidate_id)
        if args.action == 'check':
            result = inspect(item,args.candidate_id)
            store(args.projects_dir,args.project_id,args.candidate_id,result)
        else:
            result = load_report(args.projects_dir,args.project_id,args.candidate_id,item)
            if result is None:
                raise MultilangProbeError('no R5 report staged')
        print(json.dumps({'status': result['status'], 'lines': result['declared_text_lines'],
                          'sampled_frames': len(result['sampled_frames']),
                          'failed_samples': result['failed_samples']},ensure_ascii=False))
        return 0 if result['status']=='PASS_SAMPLED_MULTILINGUAL_TEXT' else 3
    except (MultilangProbeError,stage.ReviewPackageError,stage.bridge.r0.ProgramError,
            r3.VisualProbeError,OSError,ValueError,KeyError,TypeError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
