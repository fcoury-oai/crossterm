from desktop import Window, configure_wt, layouts, scan, until
import json
from pathlib import Path
import sys
import time

scan["end"] = 0x14f
names = layouts()
klids = ("00000409", "00000419", "00020419", "0002042b", "0000042b", "00000415")
shortcuts = {"ctrl+c":"U+0063 02", "ctrl+d":"U+0064 02", "ctrl+r":"U+0072 02",
             "ctrl+t":"U+0074 02", "ctrl+z":"U+007A 02", "ctrl+shift+c":"U+0043 03",
             "ctrl+shift+z":"U+005A 03", "rc+c":"U+0063 02",
             "caps/ctrl+r":"U+0072 02", "caps/ctrl+shift+z":"U+005A 03"}
controls = ["d", "shift+d", "ctrl+alt+d", "ctrl+2", "backspace", "tab", "enter", "esc"]

def collect(side):
    log = Path.cwd() / f"{side}.txt"
    probe = [sys.executable, Path(__file__).with_name("desktop.py").resolve()] if side=="raw" else [Path.cwd()/f"{side}.exe"]
    marker = "vk=23 " if side=="raw" else "END"
    w = Window("probe-"+side, [*probe, log])
    rows = {}
    try:
        until(log.exists)
        for klid in klids:
            w.switch(klid)
            keys = ["altgr+a"] if klid=="00000415" else [*shortcuts,*controls]
            row = rows[klid] = {}
            for key in keys:
                caps = key.startswith("caps/")
                if caps:
                    w.press("caps")
                    time.sleep(.15)
                offset = len(log.read_text().splitlines())
                w.press(key.removeprefix("caps/"))
                w.press("end")
                def sample():
                    lines = log.read_text().splitlines()[offset:]
                    if lines and lines[-1].startswith(marker):
                        return lines
                records = until(sample, 4, f"missing end of input for {side}, {key}")
                if caps:
                    w.press("caps")
                    time.sleep(.15)
                row[key] = "; ".join(records[:-1]) or "no event"
            print(side, klid, names[klid], f"HKL {w.hkl&0xffffffff:08X}")
    finally:
        w.close()
    return rows

configure_wt()
raw, before, after = (collect(s) for s in ["raw","before","after"])
print("Columns: KLID, key, console key-down record, event::read press before, event::read press after")
print("Event modifiers: 01=Shift, 02=Ctrl, 03=Ctrl+Shift, 06=Ctrl+Alt")
for klid in klids:
    for key in raw[klid]:
        print(klid,key,raw[klid][key],before[klid][key],after[klid][key],sep=" | ")
        if key in shortcuts:
            assert after[klid][key] == shortcuts[key], (klid,key)
        else:
            assert before[klid][key] == after[klid][key], (klid,key)
assert before["00020419"]["ctrl+c"] == "no event"
assert before["0002042b"]["ctrl+c"] == "U+0581 02"
assert "u=0000" in raw["0002042b"]["ctrl+shift+c"]
assert after["00000415"]["altgr+a"] == "U+0105 06"
