import sys,os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfkit.demux import demux
from pmfkit import atrac3p
from pmfkit.mux import mux
from pmfkit.h264 import split_access_units
f=sys.argv[1]
orig=open(f,"rb").read()
P,v,a,packs=demux(orig)
au=atrac3p.from_units(a)
print("video ES",len(v),"audio units",len(au.frames),"frame",au.frame_bytes,"kbps",round(au.kbps))
new=mux(v,au,version=P.version,video_kib=P.video_buffer_kib)
print("orig",len(orig),"new",len(new),"hdr equal (except fake pts/size):",orig[:12]==new[:12])
P2,v2,a2,packs2=demux(new)
print("video ES identical:",v2==v if True else None)
print("audio ES identical:",a2==a[:len(a2)] , len(a),len(a2))
print("packs",len(packs),len(packs2))
# structural compare pack by pack
same=0;diff=[]
for p1,p2 in zip(packs,packs2):
    k1=[(i.sid,i.length,i.flags,i.hl,i.pts,i.dts) for i in p1.items]; k2=[(i.sid,i.length,i.flags,i.hl,i.pts,i.dts) for i in p2.items]
    if k1==k2: same+=1
    else: diff.append((p1.index,k1[:3],k2[:3]))
print("structurally identical packs",same,"of",min(len(packs),len(packs2)))
for d in diff[:5]: print(d)
