/** Source-anchored EveDirector R1 candidate component. No remote assets or eval. */
import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {assertSafeBundle, evaluate, type Clip, type Palette, type VideoProps} from './SceneProgramCore';

// Own the color predicate locally: it is not exported by SceneProgramCore.
const HEX = /^#[0-9a-fA-F]{6}$/;

const ClipFrame: React.FC<{clip: Clip; palette: Palette}> = ({clip, palette}) => {
  // Children of a Sequence see scene-local frame 0..duration-1.
  const frame = useCurrentFrame();
  return <AbsoluteFill>
    {clip.layers.map((layer) => {
      const opacity = evaluate(layer, 'opacity', frame);
      if (opacity <= 0) return null;
      const fill = HEX.test(layer.fill) ? layer.fill : palette[layer.fill as keyof Palette];
      const common: React.CSSProperties = {
        position: 'absolute', left: Math.round(evaluate(layer,'x',frame)),
        top: Math.round(evaluate(layer,'y',frame)), opacity,
        boxSizing: 'border-box', pointerEvents: 'none',
      };
      if (layer.kind === 'text') {
        return <div key={layer.id} style={{...common, color: fill,
          fontSize: layer.font_size, whiteSpace: 'pre-wrap', lineHeight: 1.2,
          fontFamily: layer.font_profile === 'noto-cjk-tc-v1'
            ? '"Noto Sans CJK TC", sans-serif'
            : '"DejaVu Sans", Arial, sans-serif',
          ...(layer.font_profile === 'noto-cjk-tc-v1'
            ? {whiteSpace: 'pre' as const, wordBreak: 'normal' as const, overflowWrap: 'normal' as const}
            : {})}}>{layer.text}</div>;
      }
      return <div key={layer.id} style={{...common, backgroundColor: fill,
        width: Math.round(evaluate(layer,'width',frame)),
        height: Math.round(evaluate(layer,'height',frame)),
        borderRadius: layer.kind === 'ellipse' ? '50%' : 0}} />;
    })}
  </AbsoluteFill>;
};

export const SceneProgramVideo: React.FC<VideoProps> = ({bundle}) => {
  assertSafeBundle(bundle);
  return <AbsoluteFill style={{backgroundColor: bundle.palette.background}}>
    {bundle.clips.map((clip) =>
      <Sequence key={clip.id} name={clip.id} from={clip.from}
        durationInFrames={clip.durationInFrames}>
        <ClipFrame clip={clip} palette={bundle.palette} />
      </Sequence>
    )}
  </AbsoluteFill>;
};
