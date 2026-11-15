"""Test-only stub of R9 EVOE CLI transport; NOT the actual EVOE rendering engine.

Installs a synthetic executable-module fixture for optional integration testing.
Do not copy into production deployments or treat its output as real EVOE pixels.
"""
from pathlib import Path

STUB = r'''import argparse, json, struct, zlib, os
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('cmd');p.add_argument('--scene');p.add_argument('--times');p.add_argument('--size',type=int)
p.add_argument('--samples');p.add_argument('--output')
a=p.parse_args()
assert a.cmd=='animate'
assert 'SECRET_GITHUB_TOKEN' not in os.environ
out=Path(a.output); out.mkdir()
times=[float(x) for x in a.times.split(',')]
def png(size,n):
 def chunk(tag,b):return struct.pack('>I',len(b))+tag+b+struct.pack('>I',zlib.crc32(tag+b)&0xffffffff)
 data=bytearray()
 for y in range(size):
  data.append(0)
  for x in range(size):
   # Moving gradient box is a STUB, not the true EVOE geometry operator.
   val=(x*3+n*5)%255
   data.extend([val,(y*2+60)%255,(n*4+180)%255])
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(data)))+chunk(b'IEND',b'')
for n,t in enumerate(times):
 (out/f'frame_{n:03d}.png').write_bytes(png(a.size,n))
(out/'frames.json').write_text(json.dumps({'schema':'evoe.anim-sequence.v0.1','frame_times':times,'receipts':[{} for _ in times]}),encoding='utf-8')
'''


def install(root:Path)->Path:
    package=root/'src'/'evoe'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('',encoding='utf-8')
    (package/'cli.py').write_text(STUB,encoding='utf-8')
    return root
