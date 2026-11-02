import struct,sys,collections
def pts(x): return (((x[0]>>1)&7)<<30)|(x[1]<<22)|((x[2]>>1)<<15)|(x[3]<<7)|(x[4]>>1)
def scr(h):
    v=int.from_bytes(h[4:10],'big'); return ((v>>43)&7)<<30|((v>>27)&0x7fff)<<15|((v>>11)&0x7fff)
def load(p):
    d=open(p,"rb").read(); return d[:2048],d[2048:]
def sectors(body):
    for k in range(len(body)//2048):
        s=body[k*2048:(k+1)*2048]; p=14+(s[13]&7); items=[]
        while p<2048:
            sid=s[p+3]; L=struct.unpack(">H",s[p+4:p+6])[0]
            it={"sid":sid,"L":L,"off":p}
            if sid in(0xE0,0xBD):
                fl=s[p+7]; hl=s[p+8]; it["fl"]=fl;it["hl"]=hl
                if fl&0x80: it["pts"]=pts(s[p+9:p+14])
                if fl&0x40: it["dts"]=pts(s[p+14:p+19])
                it["pay"]=s[p+9+hl:p+6+L]; it["ext"]=s[p+9+10:p+9+hl] if hl>10 else b""
            items.append(it); p+=6+L
        yield k,scr(s),s,items
if __name__=="__main__":
    h,b=load(sys.argv[1]); n=int(sys.argv[2]) if len(sys.argv)>2 else 40
    print("hdr nonzero:",h[:0xB0].hex(' '))
    # audio check
    units=[]; a=bytearray(); prev=None
    bd=[]
    for k,sc,s,items in sectors(b):
        for it in items:
            if it["sid"]==0xBD: bd.append((k,sc,it))
    print("BD packets",len(bd))
    # pointer test
    off=0; ok=bad=0; badl=[]
    for idx,(k,sc,it) in enumerate(bd):
        pay=it["pay"]; ptr=int.from_bytes(pay[2:4],'big')
        # find unit size from header
        if idx==0:
            fsz=((( pay[4+2]&3)<<8)|pay[4+3])*8+8
            U=fsz+8
        rem=(-off)%U
        exp=0 if idx==0 else rem+3
        if ptr==exp: ok+=1
        else: bad+=1; badl.append((idx,off,ptr,exp))
        off+=len(pay)-4
    print("unit",U,"pointer formula ok",ok,"bad",bad,badl[:5])
    # audio pts check
    print("first BD:",[(k,sc,it.get('pts'),it['hl'],it['ext'].hex(),it['pay'][:4].hex()) for k,sc,it in bd[:6]])
    # pts progression vs frame units: PTS per packet vs offset
    off=0; rows=[]
    for idx,(k,sc,it) in enumerate(bd):
        if "pts" in it: rows.append((idx,off,off/U,it["pts"],sc))
        off+=len(it["pay"])-4
    for r in rows[:8]: print("idx %d off %d unit %.3f pts %d scr %d"%r)
    print("... slope ticks/unit:",[(rows[i+1][3]-rows[i][3])/(rows[i+1][2]-rows[i][2]) for i in range(0,min(6,len(rows)-1))])
    # layout of first sectors
    for k,sc,s,items in list(sectors(b))[:n]:
        print(k,sc,[(hex(i["sid"]),i["L"],i.get("fl"),i.get("hl"),i.get("pts")) for i in items])
