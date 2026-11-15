/** Deterministic, dependency-free Scene IR contract shared with Remotion and Node tests. */
export type Track = 'x' | 'y' | 'width' | 'height' | 'opacity';
export type Point = {frame: number; value: number};
export type Keyframes = Partial<Record<Track, Point[]>>;

type Common = {
  id: string; x: number; y: number; fill: string;
  opacity?: number; keyframes?: Keyframes;
};
export type Layer =
  | (Common & {kind: 'rect' | 'ellipse'; width: number; height: number})
  | (Common & {kind: 'text'; text: string; font_size: number});
export type SourceAnchor = {
  source_contains: string; line_start: number; line_end: number;
  logical_line_sha256: string;
};
export type Clip = {
  id: string; from: number; durationInFrames: number;
  source: SourceAnchor; layers: Layer[];
};
export type Palette = Record<'background' | 'primary' | 'accent' | 'text' | 'muted', string>;
export type Bundle = {
  schema: 'evedirector.remotion_clip_bundle.v0.1';
  title: string; candidate_only: true; review_required: true;
  canonical_spec_mutated: false; source_approval_verified: false;
  source_evidence_scope: 'substring-present-at-explicit-line';
  source_sha256: string; program_sha256: string; style: string;
  style_sha256: string; palette: Palette;
  width: number; height: number; fps: number;
  durationInFrames: number; clips: Clip[];
};
export type VideoProps = {bundle: Bundle};

const HEX = /^#[0-9a-fA-F]{6}$/;
const SLUG = /^[a-z][a-z0-9_-]{0,63}$/;
const SHA = /^[a-f0-9]{64}$/;
const TOKENS = ['background', 'primary', 'accent', 'text', 'muted'] as const;
const TRACKS: Track[] = ['x', 'y', 'width', 'height', 'opacity'];

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function exact(value: Record<string, unknown>, required: string[], optional: string[] = []): void {
  const keys = Object.keys(value);
  if (required.some((key) => !Object.prototype.hasOwnProperty.call(value, key)) ||
      keys.some((key) => !required.includes(key) && !optional.includes(key))) {
    throw new Error('R1 props contain missing/unknown keys');
  }
}
function integer(value: unknown, lo: number, hi: number): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= lo && value <= hi;
}
function finite(value: unknown, lo: number, hi: number): boolean {
  return typeof value === 'number' && Number.isFinite(value) && value >= lo && value <= hi;
}
function validColor(c: unknown): boolean {
  return typeof c === 'string' && (HEX.test(c) || TOKENS.includes(c as keyof Palette));
}

/** Reject custom Studio/CLI props that do not match the allow-listed scene shape.
 * SHA/source-line verification requires the separate Python CLI and original files.
 */
export function assertSafeBundle(input: unknown): asserts input is Bundle {
  if (!object(input)) throw new Error('R1 bundle must be an object');
  exact(input, ['schema','title','candidate_only','review_required','canonical_spec_mutated',
    'source_approval_verified','source_evidence_scope','source_sha256','program_sha256',
    'style','style_sha256','palette','width','height','fps','durationInFrames','clips']);
  if (input.schema !== 'evedirector.remotion_clip_bundle.v0.1' ||
      input.candidate_only !== true || input.review_required !== true ||
      input.canonical_spec_mutated !== false || input.source_approval_verified !== false ||
      input.source_evidence_scope !== 'substring-present-at-explicit-line' ||
      typeof input.title !== 'string' || input.title.length < 1 || input.title.length > 140 ||
      typeof input.style !== 'string' || !SLUG.test(input.style) ||
      ![input.source_sha256,input.program_sha256,input.style_sha256].every(
        (v) => typeof v === 'string' && SHA.test(v)
      ) || !integer(input.width,160,1920) || !integer(input.height,90,1080) ||
      !integer(input.fps,1,60) || !integer(input.durationInFrames,1,1800) ||
      (input.width as number) * (input.height as number) * (input.durationInFrames as number) > 250_000_000) {
    throw new Error('R1 bundle header invalid');
  }
  const palette = input.palette;
  if (!object(palette)) throw new Error('R1 palette missing');
  exact(palette, [...TOKENS]);
  if (!TOKENS.every((key) => typeof palette[key] === 'string' && HEX.test(palette[key] as string))) {
    throw new Error('R1 palette contains invalid color');
  }
  if (!Array.isArray(input.clips) || input.clips.length < 1 || input.clips.length > 30) {
    throw new Error('R1 clips invalid');
  }
  let cursor = 0;
  const clipIds = new Set<string>();
  for (const c of input.clips as unknown[]) {
    if (!object(c)) throw new Error('R1 clip not object');
    exact(c, ['id','from','durationInFrames','source','layers']);
    if (typeof c.id !== 'string' || !SLUG.test(c.id) || clipIds.has(c.id) ||
        !integer(c.from,0,(input.durationInFrames as number)-1) ||
        !integer(c.durationInFrames,1,input.durationInFrames as number) || c.from !== cursor ||
        (c.from as number)+(c.durationInFrames as number) > (input.durationInFrames as number)) {
      throw new Error('R1 clip timeline, ID or duration invalid');
    }
    clipIds.add(c.id);
    cursor += c.durationInFrames as number;
    if (!object(c.source)) throw new Error('R1 source anchor missing');
    exact(c.source, ['source_contains','line_start','line_end','logical_line_sha256']);
    if (typeof c.source.source_contains !== 'string' ||
        c.source.source_contains.trim().length < 8 || c.source.source_contains.length > 500 ||
        !integer(c.source.line_start,1,10000000) || c.source.line_end !== c.source.line_start ||
        typeof c.source.logical_line_sha256 !== 'string' || !SHA.test(c.source.logical_line_sha256)) {
      throw new Error('R1 source anchor invalid');
    }
    if (!Array.isArray(c.layers) || c.layers.length < 1 || c.layers.length > 48) {
      throw new Error('R1 clip layers invalid');
    }
    const layerIds = new Set<string>();
    for (const l of c.layers as unknown[]) {
      if (!object(l)) throw new Error('R1 layer not object');
      const geom = l.kind === 'rect' || l.kind === 'ellipse';
      if (!geom && l.kind !== 'text') throw new Error('R1 layer kind invalid');
      exact(l, ['id','kind','x','y','fill', ...(geom ? ['width','height'] : ['text','font_size'])],
        ['opacity','keyframes']);
      if (typeof l.id !== 'string' || !SLUG.test(l.id) || layerIds.has(l.id) ||
          !finite(l.x,-3*(input.width as number),3*(input.width as number)) ||
          !finite(l.y,-3*(input.height as number),3*(input.height as number)) ||
          !validColor(l.fill) || !finite(l.opacity ?? 1,0,1)) {
        throw new Error('R1 invalid layer attributes');
      }
      layerIds.add(l.id);
      if (geom) {
        if (!finite(l.width,1,3*(input.width as number)) ||
            !finite(l.height,1,3*(input.height as number))) throw new Error('R1 geometry invalid');
      } else if (typeof l.text !== 'string' || l.text.length < 1 || l.text.length > 240 ||
                 !integer(l.font_size,8,160)) {
        throw new Error('R1 text invalid');
      }
      if (l.keyframes !== undefined) {
        if (!object(l.keyframes) || Object.keys(l.keyframes).some((k) => !TRACKS.includes(k as Track))) {
          throw new Error('R1 unknown keyframe track');
        }
        for (const [key, points] of Object.entries(l.keyframes)) {
          if (!geom && (key === 'width' || key === 'height')) throw new Error('R1 text size track forbidden');
          if (!Array.isArray(points) || points.length < 1 || points.length > 50) {
            throw new Error('R1 track points invalid');
          }
          let prev = -1;
          for (const p of points as unknown[]) {
            if (!object(p)) throw new Error('R1 keyframe not object');
            exact(p, ['frame','value']);
            const bound = key === 'opacity' ? 1 :
              (key === 'x' || key === 'width' ? 3*(input.width as number) : 3*(input.height as number));
            const lower = key === 'opacity' ? 0 : key === 'width' || key === 'height' ? 1 : -bound;
            if (!integer(p.frame,0,(c.durationInFrames as number)-1) ||
                (p.frame as number) <= prev || !finite(p.value,lower,bound)) {
              throw new Error('R1 invalid keyframe value/time');
            }
            prev = p.frame as number;
          }
        }
      }
    }
  }
  if (cursor !== input.durationInFrames) throw new Error('R1 timeline not fully covered');
}

/** Matches R0's piecewise-linear, local-frame interpolation rule. */
export function evaluate(layer: Layer, field: Track, frame: number): number {
  const original = (layer as unknown as Record<string, unknown>)[field];
  const value = typeof original === 'number' ? original : field === 'opacity' ? 1 : 0;
  const points = layer.keyframes?.[field];
  if (!points || points.length === 0) return value;
  if (frame <= points[0].frame) return points[0].value;
  for (let i=0; i<points.length-1; i++) {
    const a=points[i]; const b=points[i+1];
    if (frame <= b.frame) return a.value + (b.value-a.value)*(frame-a.frame)/(b.frame-a.frame);
  }
  return points[points.length-1].value;
}
