'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {assertSafeBundle}=require(path.resolve(process.argv[2]));
const source=JSON.parse(fs.readFileSync(process.argv[3],'utf8')).bundle;
assert.doesNotThrow(()=>assertSafeBundle(source));
const clone=()=>JSON.parse(JSON.stringify(source));
const text=(b)=>b.clips[0].layers.find(l=>l.id==='cn_title');
const shape=(b)=>b.clips[0].layers.find(l=>l.id==='panel');
{
 const b=clone();delete text(b).font_profile;
 assert.throws(()=>assertSafeBundle(b),/non-ASCII.*CJK profile/);
}
{
 const b=clone();text(b).font_profile='http://external-font';
 assert.throws(()=>assertSafeBundle(b),/font_profile invalid/);
}
{
 const b=clone();shape(b).font_profile='noto-cjk-tc-v1';
 assert.throws(()=>assertSafeBundle(b),/unknown keys/);
}
{
 const b=clone();text(b).text='中文字\u202e';
 assert.throws(()=>assertSafeBundle(b),/control\/format/);
}
{
 const b=clone();text(b).text='中\n\n英';
 assert.throws(()=>assertSafeBundle(b),/unsupported explicit CJK layout/);
}
{
 const b=clone();text(b).text='中\n英';
 assert.doesNotThrow(()=>assertSafeBundle(b));
}
console.log('R5_FONT_PROFILE_CONTRACT PASS | 1 positive + 6 adversaries');
