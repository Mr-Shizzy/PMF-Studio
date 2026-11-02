"""Opens every PMF Studio page, checks nothing raises, saves screenshots (Windows, needs Pillow only for the pictures)."""
import sys
sys.path.insert(0, ".")
from pmfstudio.app import App
a = App()
a.settings["auto_update"] = False
shots = len(sys.argv) > 1
if shots:
    from PIL import ImageGrab
for k in ("gameboot", "cintro", "icon", "shrink", "at3", "extract", "player", "help", "about", "options", "gameboot"):
    a.show(k)
    if k == "gameboot" and "ctf" in a.vars:
        a.vars["ctf"].set(True)
        a.vars["sep"].set(True)
        a.gb_sub()
    if k == "at3" and len(sys.argv) > 2:
        a.vars["task"].set("shrink"); a.at3_refresh()
    if k == "icon":
        a.vars["sep"].set(True)
        a.icon_refresh()
    import time
    for _ in range(15):
        a.update(); time.sleep(0.02)
    if shots:
        a.lift(); a.attributes("-topmost", True); a.update()
        x, y, w, h = a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(), a.winfo_height()
        ImageGrab.grab((x, y, x + w, y + h), all_screens=True).save("test_output/gb_build/shot_%s.png" % k)
print("ok")
a.destroy()
