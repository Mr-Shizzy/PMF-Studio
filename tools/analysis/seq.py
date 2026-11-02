import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfkit.demux import demux
from pmfkit import atrac3p
from pmfkit.mux import mux
f=sys.argv[1]
orig=open(f,"rb").read()
P,v,a,packs=demux(orig); au=atrac3p.from_units(a)
new=mux(v,au,version=P.version,video_kib=P.video_buffer_kib)
P2,v2,a2,packs2=demux(new)
def seq(pk): return "".join("A" if any(i.sid==0xBD for i in p.items) else "G" if any(i.sid==0xBB for i in p.items) else "v" for p in pk)
s1,s2=seq(packs),seq(packs2)
print(s1); print(s2)
print([ (p.index,round(p.scr27/300)) for p in packs if 'A'==seq([p])][:12])
print([ (p.index,round(p.scr27/300)) for p in packs2 if 'A'==seq([p])][:12])
