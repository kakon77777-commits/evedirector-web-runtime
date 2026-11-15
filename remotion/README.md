# EveDirector R1 — Programmatic Remotion adapter

This candidate-only package is a second rendering backend for the strict R0 Scene Program. It is additive: it does not replace OpenMontage's existing remotion-composer, Backlot, or the L0–L6 review/apply controls. No network assets, arbitrary code, or implicit approval.

## Reproducible local steps

From the repository root, with Python 3.10+, Pillow and PyYAML:

1. Export props and a receipt from the real R0 demo source (not from model-authored executable code):

       python scripts/evedirector_remotion_bridge.py export --plan examples/native-video/program.json --source examples/native-video/source/README.md --props generated/remotion-props.json --receipt generated/remotion-bridge-receipt.json

2. Verify before each render:

       python scripts/evedirector_remotion_bridge.py verify --plan examples/native-video/program.json --source examples/native-video/source/README.md --props generated/remotion-props.json --receipt generated/remotion-bridge-receipt.json

3. Generate independent R0 interpolation reference data:

       python scripts/evedirector_r1_vectors.py

4. Run isolated Remotion from the new folder:

       cd remotion
       npm install --no-audit --no-fund
       npm run typecheck
       npm run render

5. Validate the H.264 MP4 with ffprobe. The render is a candidate, not an approved or externally publishable artifact.

The CI pipeline executes these steps in order. It also compares 175 interpolation values from the R0 Python evaluator with the dependency-free R1 TypeScript evaluator. This does not imply pixel-identical Pillow and Chromium frames.

If source, plan, or style changes, regenerate props and receipt; verification rejects reuse of stale data. Generated files are deliberately not authoritative and should not be reviewed or published without an explicit human gate.
