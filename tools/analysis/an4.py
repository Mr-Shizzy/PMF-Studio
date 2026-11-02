import sys,os,importlib.util
spec=importlib.util.spec_from_file_location("an2",os.path.join(os.environ["TEMP"],"scr","an2.py")); a2=importlib.util.module_from_spec(spec); spec.loader.exec_module(a2)
h,b=a2.load(sys.argv[1]); secs=list(a2.sectors(b))
gop=[k for k,sc,s,it in secs if any(i["sid"]==0xBB for i in it)]
print("GOP sectors",gop)
for k,sc,s,items in secs:
    for it in items:
        if it["sid"]==0xBD:
            pay=it["pay"]
            print("BD sector",k,"scr",sc,"pts",it.get("pts"),"hl",it["hl"],"fl",hex(it["fl"]),"hdrbytes",s[it["off"]+6:it["off"]+9+it["hl"]].hex(' '),"ptr",int.from_bytes(pay[2:4],'big'),"padL",[i["L"] for i in items if i["sid"]==0xBE])
for k,sc,s,items in secs:
    for it in items:
        if it["sid"]==0xBF:
            body=s[it["off"]+6:it["off"]+6+it["L"]]; print("BF last entries:",body[-12:].hex(' '))
