import sys,struct,glob,os,collections
root=sys.argv[1]
files=sorted(glob.glob(root+"/**/*.[pP][mM][fF]",recursive=True))
rows=[]
hdrs=collections.defaultdict(list)
for f in files:
    d=open(f,"rb").read()
    h=d[:2048]
    name=os.path.relpath(f,root)[:34]
    ver=h[4:8].decode("latin1")
    size=struct.unpack(">I",h[12:16])[0]
    tl=struct.unpack(">I",h[0x50:0x54])[0]
    p0=int.from_bytes(h[0x54:0x5a],"big"); p1=int.from_bytes(h[0x5a:0x60],"big")
    W=h[0x8e]*16;H=h[0x8f]*16
    # audio scan
    body=d[2048:]; i=0;n=len(body);a=bytearray();nb=0;kinds=collections.Counter();firstbd=None;nvid=0
    while i<n-6:
        if body[i:i+3]==b"\x00\x00\x01":
            s=body[i+3]
            if s==0xBA: i+=14+(body[i+13]&7);continue
            if s in(0xBB,0xBC,0xBD,0xBE,0xBF) or 0xE0<=s<=0xEF:
                L=struct.unpack(">H",body[i+4:i+6])[0]; kinds[s]+=1
                if s==0xBD:
                    hl=body[i+8]; pl=body[i+9+hl:i+6+L]; a+=pl[4:]; nb+=1
                i+=6+L;continue
        i+=1
    # find 0f d0 headers
    hd=collections.Counter(); k=0
    while True:
        k=a.find(b"\x0f\xd0",k)
        if k<0 or k>len(a)-8: break
        hd[bytes(a[k:k+8]).hex()]+=1; k+=2
    top=hd.most_common(1)[0] if hd else None
    fs=None;ch=None;kbps=None
    if top:
        b=bytes.fromhex(top[0]); fs=(((b[2]&3)<<8)|b[3])*8+8; ch=(b[2]>>2)&7; sr=(b[2]>>5)
    dur=(p1-p0)/90000
    if fs and dur>0: kbps=round((nb and len(a)/nb*nb)*8/dur/1000) 
    rows.append((name,ver,size+2048==len(d),tl,p0,p1,round(dur,2),W,H,len(d)//1024,nb,top,fs,kbps))
    hdrs[bytes(h[:0xB0])].append(name)
for r in rows: print(r)
print()
print("distinct header shapes (first 0xB0 bytes incl. size/PTS):",len(hdrs))
# header shapes ignoring size & PTS fields
sh=collections.Counter()
for f in files:
    h=bytearray(open(f,"rb").read(2048)); h[12:16]=b"\0"*4; h[0x54:0x60]=b"\0"*12; h[0x76:0x82]=b"\0"*12
    sh[bytes(h[:0xB0])]+=1
for k,v in sh.most_common(): print(v,k.hex(' '))
