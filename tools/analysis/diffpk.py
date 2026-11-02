import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pmfkit.demux import demux
from pmfkit import atrac3p
from pmfkit.mux import mux
f=sys.argv[1]
orig=open(f,"rb").read()
P,v,a,packs=demux(orig); au=atrac3p.from_units(a)
sysflag=[i.payload for pk in packs for i in pk.items if i.sid==0xBB][0][3]
new=mux(v,au,version=P.version,style='B' if sysflag==0x80 else 'A',header_kib=P.video_buffer_kib)
o=orig[2048:];n=new[2048:]
print(len(o)//2048,len(n)//2048)
for i in range(min(len(o),len(n))//2048):
    A=o[i*2048+14:(i+1)*2048]; B=n[i*2048+14:(i+1)*2048]
    if A!=B:
        d=[j for j in range(len(A)) if A[j]!=B[j]]
        print("pack",i,"first diff @",d[0]+14,"count",len(d),"orig",A[d[0]:d[0]+8].hex(' '),"new",B[d[0]:d[0]+8].hex(' '))
