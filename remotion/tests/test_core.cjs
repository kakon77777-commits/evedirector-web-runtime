'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
if (process.argv.length < 4) throw Error('usage: node test_core.cjs <compiled_core.js> <props.json> [vectors.json]');
const {assertSafeBundle, evaluate} = require(path.resolve(process.argv[2]));
const props = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const b = props.bundle;
assert.doesNotThrow(() => assertSafeBundle(b));
const original = b.clips[0].layers[0];
assert.equal(evaluate(original, 'x', 0), 620);
assert.equal(evaluate(original, 'x', 29), 420);
assert.equal(evaluate(original, 'x', 14.5), 520);
assert.equal(evaluate(original, 'opacity', 10), 0.34);
const plain = {kind: 'rect', x: 15, y: 24, width: 12, height: 8, fill: 'primary', id: 'x'};
assert.equal(evaluate(plain, 'x', 7), 15);
assert.equal(evaluate(plain, 'opacity', 7), 1);
function bad(mutate, pattern) {
  const copy=JSON.parse(JSON.stringify(b));
  mutate(copy);
  assert.throws(() => assertSafeBundle(copy), pattern);
}
bad(x => {x.clips[0].layers[0].script='eval(1)'}, /unknown keys/);
bad(x => {x.clips[0].layers[0].src='https://example.com/x.png'}, /unknown keys/);
bad(x => {x.clips[1].from=29}, /timeline/);
bad(x => {x.clips[0].source.line_start=0}, /anchor/);
bad(x => {x.candidate_only=false}, /header/);
bad(x => {x.palette.text='url(https://evil.invalid)'}, /palette/);
bad(x => {x.clips[0].layers[0].keyframes.x[1].frame=2000}, /keyframe/);
bad(x => {x.clips[0].layers[0].kind='python'}, /kind/);
const vectorPath=process.argv[4] || path.resolve(path.dirname(process.argv[3]),'interpolation_vectors.json');
const vectors = JSON.parse(fs.readFileSync(vectorPath, 'utf8'));
assert.equal(vectors.schema, 'evedirector.interpolation_vectors.v0.1');
assert.equal(vectors.r0_program_sha256, b.program_sha256);
assert.equal(vectors.vectors.length, 175);
for (const v of vectors.vectors) {
  const clip=b.clips.find(c => c.id===v.scene);
  assert.ok(clip, 'missing clip '+v.scene);
  const layer=clip.layers.find(l => l.id===v.layer);
  assert.ok(layer, 'missing layer '+v.layer);
  assert.ok(Math.abs(evaluate(layer,v.field,v.frame)-v.value)<1e-9, JSON.stringify(v));
}
console.log('R1_NODE_CONTRACT: PASS | 12 structure checks + '+vectors.vectors.length+' R0↔TS vectors');
