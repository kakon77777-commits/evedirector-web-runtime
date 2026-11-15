import React from 'react';
import {Composition} from 'remotion';
import props from '../../generated/remotion-props.json';
import {SceneProgramVideo} from './SceneProgramVideo';
import {assertSafeBundle, type VideoProps} from './SceneProgramCore';

const defaultProps = props as unknown as VideoProps;
assertSafeBundle(defaultProps.bundle);

/** Additive isolated composition; no changes to an existing EveDirector composer. */
export const RemotionRoot: React.FC = () => <Composition
  id="EveDirectorNativeR1"
  component={SceneProgramVideo}
  durationInFrames={defaultProps.bundle.durationInFrames}
  fps={defaultProps.bundle.fps}
  width={defaultProps.bundle.width}
  height={defaultProps.bundle.height}
  defaultProps={defaultProps}
/>;
