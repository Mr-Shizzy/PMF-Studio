import sys,os,glob,traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfkit.demux import demux
from pmfkit import atrac3p
from pmfkit.mux import mux
root=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Mr. Shizzy - GameBoots Pack 1")
fs=sorted(glob.glob(root+"/**/*.[pP][mM][fF]",recursive=True))
tot_same=tot_bytes=tot=0
for f in fs:
    orig=open(f,"rb").read()
    try:
        P,v,a,packs=demux(orig)
        au=atrac3p.from_units(a)
        sysflag=[i.payload for pk in packs for i in pk.items if i.sid==0xBB][0][3]
        new=mux(v,au,version=P.version,style='B' if sysflag==0x80 else 'A',header_kib=P.video_buffer_kib)
        P2,v2,a2,packs2=demux(new)
        ok_v = v2==v; ok_a = a2==a
        n=min(len(packs),len(packs2)); same=byt=0
        o=orig[2048:]; nw=new[2048:]
        for i in range(n):
            if o[i*2048+14:(i+1)*2048]==nw[i*2048+14:(i+1)*2048]: byt+=1
            p1,p2=packs[i],packs2[i]
            if [(x.sid,x.length,x.flags,x.hl,x.pts,x.dts) for x in p1.items]==[(x.sid,x.length,x.flags,x.hl,x.pts,x.dts) for x in p2.items]: same+=1
        print("%-34s v:%s a:%s packs %3d/%3d struct %3d bytes %3d"%(os.path.relpath(f,root)[:34],ok_v,ok_a,len(packs),len(packs2),same,byt))
        tot+=n;tot_same+=same;tot_bytes+=byt
    except Exception as e:
        print("%-34s ERROR %r"%(os.path.relpath(f,root)[:34],e))
print("total struct %.1f%% bytes(excl SCR) %.1f%%"%(100*tot_same/tot,100*tot_bytes/tot))
