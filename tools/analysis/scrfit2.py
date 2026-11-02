import sys, os,bisect,statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfkit.demux import demux
from pmfkit.h264 import split_access_units
orig=open(sys.argv[1],"rb").read()
P,v,a,packs=demux(orig)
aus=split_access_units(v,strip_x264_sei=False)
starts=[];ends=[];o=0
for x in aus: starts.append(o); o+=len(x.data); ends.append(o)
pos=0; rows=[]; prev=None
for pk in packs:
    for it in pk.items:
        if it.sid==0xE0:
            n=len(it.payload)
            kf=bisect.bisect_right(starts,pos)-1
            kl=bisect.bisect_right(starts,pos+n-1)-1
            kn=bisect.bisect_right(starts,pos+n)-1     # AU holding the byte after the pack
            s=pk.scr27/300
            binding = prev is not None and s-prev>400
            rows.append((pk.index,kf,kl,kn,s,binding))
            prev=s; pos+=n
        elif it.sid==0xBD: pass
    # keep prev updated for audio packs too
    if not any(i.sid==0xE0 for i in pk.items): prev=pk.scr27/300
for name,col in (("first",1),("last",2),("next",3)):
    L=[ (90000+3003*(r[col]-1))-r[4] for r in rows if r[5]]
    print(name,"binding n",len(L),"L mean %.0f sd %.0f min %.0f max %.0f"%(statistics.mean(L),statistics.pstdev(L),min(L),max(L)))
