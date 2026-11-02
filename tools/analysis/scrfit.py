import sys, os,bisect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfkit.demux import demux
from pmfkit.h264 import split_access_units
orig=open(sys.argv[1],"rb").read()
P,v,a,packs=demux(orig)
aus=split_access_units(v,strip_x264_sei=False)
starts=[];o=0
for x in aus: starts.append(o); o+=len(x.data)
pos=0; rows=[]
for pk in packs:
    for it in pk.items:
        if it.sid==0xE0:
            k0=bisect.bisect_right(starts,pos)-1
            dts=90000+3003*(k0-1)
            rows.append((pk.index,k0,pk.scr27/300,dts-76850,pk.scr27/300-(dts-76850)))
            pos+=len(it.payload)
n=int(sys.argv[2]) if len(sys.argv)>2 else 40
prev=None
for r in rows[:n]:
    print("pack %3d au %3d scr %9.1f floor %9d  slack %9.1f  step %s"%(r+((round(r[2]-prev,1) if prev else None),))); prev=r[2]
# stats: how often slack==0 (floor binding), min slack
sl=[r[4] for r in rows]; print("min slack",min(sl),"binding(<5):",sum(1 for s in sl if s<5),"of",len(sl))
