import sys, os,re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
class BR:
    def __init__(s,b):
        # remove emulation prevention
        s.b=re.sub(rb"\x00\x00\x03",b"\x00\x00",b); s.p=0
    def u(s,n):
        v=0
        for _ in range(n):
            v=(v<<1)|((s.b[s.p>>3]>>(7-(s.p&7)))&1); s.p+=1
        return v
    def ue(s):
        z=0
        while s.u(1)==0: z+=1
        return (1<<z)-1+(s.u(z) if z else 0)
    def se(s):
        k=s.ue(); return (k+1)//2 if k&1 else -(k//2)
def parse_sps(n):
    r=BR(n[1:]); d={}
    d["profile"]=r.u(8); d["cflags"]=r.u(8); d["level"]=r.u(8); d["sps_id"]=r.ue()
    if d["profile"] in (100,110,122,244,44,83,86,118,128): raise Exception("high profile")
    d["log2_max_frame_num"]=r.ue()+4; d["poc_type"]=r.ue()
    if d["poc_type"]==0: d["log2_max_poc_lsb"]=r.ue()+4
    d["num_ref_frames"]=r.ue(); d["gaps"]=r.u(1)
    d["w_mbs"]=r.ue()+1; d["h_map_units"]=r.ue()+1; d["frame_mbs_only"]=r.u(1)
    if not d["frame_mbs_only"]: d["mbaff"]=r.u(1)
    d["direct8x8"]=r.u(1); crop=r.u(1)
    if crop: d["crop"]=[r.ue() for _ in range(4)]
    vui=r.u(1); d["vui"]=vui
    if vui:
        if r.u(1):
            if r.u(8)==255: r.u(16);r.u(16)
        if r.u(1): r.u(1)
        if r.u(1):
            d["video_signal"]=(r.u(3),r.u(1)); 
            if r.u(1): r.u(24)
        if r.u(1): r.ue();r.ue()
        if r.u(1):
            nu=r.u(32);ts=r.u(32);d["timing"]=(nu,ts,r.u(1))
        nal=r.u(1); 
        if nal: d["nal_hrd"]=hrd(r)
        vcl=r.u(1)
        if vcl: d["vcl_hrd"]=hrd(r)
        if nal or vcl: r.u(1)
        d["pic_struct_present"]=r.u(1)
        if r.u(1):
            r.u(1); d["bsr"]=[r.ue() for _ in range(2)]+[r.u(0)]; 
            d["bsr"]=[r.ue(),r.ue()]; 
            d["num_reorder"]=r.ue(); d["max_dec_buf"]=r.ue()
    return d
def hrd(r):
    cnt=r.ue()+1; r.u(8); 
    for _ in range(cnt): r.ue();r.ue();r.u(1)
    r.u(20); return cnt
def parse_pps(n):
    r=BR(n[1:]); d={}
    d["pps_id"]=r.ue(); d["sps_id"]=r.ue(); d["cabac"]=r.u(1); d["bottom_field_poc"]=r.u(1)
    d["slice_groups"]=r.ue()+1
    d["ref_idx0"]=r.ue()+1; d["ref_idx1"]=r.ue()+1; d["weighted_pred"]=r.u(1); d["weighted_bipred"]=r.u(2)
    d["qp"]=r.se(); d["qs"]=r.se(); d["chroma_qp_off"]=r.se(); d["deblock_ctrl"]=r.u(1); d["constrained_intra"]=r.u(1); d["redundant_pic"]=r.u(1)
    return d
def nals(es):
    idx=[m.start() for m in re.finditer(rb"\x00\x00\x01",es)]
    for i,s in enumerate(idx):
        e=idx[i+1] if i+1<len(idx) else len(es)
        yield es[s+3:e].rstrip(b"\x00")
def info(es):
    sps=pps=None; types={}; sei=[]
    for i,n in enumerate(nals(es)):
        t=n[0]&0x1f; types[t]=types.get(t,0)+1
        if t==7 and sps is None: sps=n
        if t==8 and pps is None: pps=n
        if t==6 and len(sei)<6: sei.append((n[1],len(n)))
    return sps,pps,types,sei
if __name__=="__main__":
    from pmfkit.demux import demux
    for f in sys.argv[1:]:
        data=open(f,"rb").read()
        if data[:4]==b"PSMF": es=demux(data)[1]
        else: es=data
        sps,pps,types,sei=info(es)
        print("==",f.split("\\")[-1] if "\\" in f else f.split("/")[-1])
        print(" SPS",parse_sps(sps)); print(" PPS",parse_pps(pps)); print(" NAL counts",types,"first SEI (payloadtype,len):",sei)
