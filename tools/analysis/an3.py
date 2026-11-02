import sys,os,struct,re,importlib.util
spec=importlib.util.spec_from_file_location("an2",os.path.join(os.environ["TEMP"],"scr","an2.py")); a2=importlib.util.module_from_spec(spec); spec.loader.exec_module(a2)
h,b=a2.load(sys.argv[1])
es=bytearray(); stamps=[]; secs=list(a2.sectors(b))
pos=0
sysh=None
for k,sc,s,items in secs:
    for it in items:
        if it["sid"]==0xBB: sysh=s[it["off"]:it["off"]+6+it["L"]]
        if it["sid"]==0xE0:
            if "pts" in it: stamps.append((k,pos,it["pts"],it.get("dts"),it["hl"],it["fl"],it["ext"].hex()))
            es+=it["pay"]; pos+=len(it["pay"])
aus=[m.start() for m in re.finditer(rb"\x00\x00\x00?\x01\x09",bytes(es))]
# normalize: AU start = index of leading zero(s)
aus=[m.start() for m in re.finditer(rb"(?:\x00)?\x00\x00\x01\x09",bytes(es))]
import bisect
print("sysheader:",sysh.hex(' ')); print("AUs",len(aus))
for k,p,pts,dts,hl,fl,ext in stamps:
    j=bisect.bisect_left(aus,p)
    print("sector",k,"esoff",p,"pts idx",(pts-90000)/3003,"dts",dts,"hl",hl,"fl",hex(fl),"ext",ext,"firstAUinPES",j, "au_off",aus[j]-p if j<len(aus) else None)
# first sector detail and last sectors
for k,sc,s,items in secs[:1]+secs[-3:]:
    print(k,[(hex(i["sid"]),i["L"],i.get("hl")) for i in items])
# BF body for first
for k,sc,s,items in secs:
    for it in items:
        if it["sid"]==0xBF: print("BF at sector",k,"len",it["L"],s[it["off"]+6:it["off"]+6+it["L"]].hex(' ')[:200]); break
# sizes of AUs
sz=[ (aus[i+1] if i+1<len(aus) else len(es))-aus[i] for i in range(len(aus))]
print("AU sizes first 6",sz[:6])
# idr positions
idr=[i for i,p in enumerate(aus) if bytes(es[p:p+12]).find(b"\x65")>=0 and (es[p+5+ (1 if es[p]==0 and es[p+1]==0 and es[p+2]==0 and es[p+3]==1 else 0)]&0x1f)==5] 
print("approx IDR/AU marks",idr[:6])
