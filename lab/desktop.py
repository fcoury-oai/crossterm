import ctypes as ct
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg

user = ct.WinDLL("user32", use_last_error=True)
kernel = ct.WinDLL("kernel32", use_last_error=True)
hwnd = wt.HWND
hkl = wt.HANDLE
for method, types, returns in [
    ("GetForegroundWindow", [], hwnd),
    ("SetForegroundWindow", [hwnd], wt.BOOL),
    ("GetWindowThreadProcessId", [hwnd, ct.POINTER(wt.DWORD)], wt.DWORD),
    ("GetKeyboardLayout", [wt.DWORD], hkl),
    ("LoadKeyboardLayoutW", [wt.LPCWSTR, wt.UINT], hkl),
    ("PostMessageW", [hwnd, wt.UINT, wt.WPARAM, wt.LPARAM], wt.BOOL),
    ("GetWindowTextW", [hwnd, wt.LPWSTR, ct.c_int], ct.c_int),
    ("IsWindow", [hwnd], wt.BOOL),
    ("GetKeyState", [ct.c_int], ct.c_short),
]:
    fn = getattr(user, method)
    fn.argtypes, fn.restype = types, returns

class KeyboardInput(ct.Structure):
    _fields_ = [("vk", wt.WORD), ("scan", wt.WORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("extra", ct.c_size_t)]

class Payload(ct.Union):
    _fields_ = [("key", KeyboardInput), ("padding", ct.c_byte * 32)]

class Input(ct.Structure):
    _fields_ = [("type", wt.DWORD), ("payload", Payload)]

user.SendInput.argtypes = [wt.UINT, ct.POINTER(Input), ct.c_int]
scan = {"esc":1, "2":3, "backspace":14, "tab":15, "r":19, "t":20, "q":16, "o":24,
        "enter":28, "ctrl":29, "a":30, "s":31, "d":32, "f":33, "h":35, "j":36,
        "k":37, "l":38, "shift":42, "z":44, "x":45, "c":46, "v":47, "b":48,
        "n":49, "m":50, "alt":56, "space":57, "caps":58, "rc":0x11d, "altgr":0x138}

def send(chord):
    keys = [scan[k] for k in chord.split("+")]
    for seq, flags in ((keys, 8), (reversed(keys), 10)):
        for s in seq:
            ev = Input(1, Payload(key=KeyboardInput(0, s & 255, flags | (s >> 8), 0, 0)))
            if user.SendInput(1, ct.byref(ev), ct.sizeof(ev)) != 1:
                raise ct.WinError(ct.get_last_error())
            time.sleep(.026)

def until(check, timeout=10, name="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        val = check()
        if val:
            return val
        time.sleep(.05)
    raise TimeoutError(name)

def layouts():
    path = r"SYSTEM\CurrentControlSet\Control\Keyboard Layouts"
    names = {}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
        for i in range(winreg.QueryInfoKey(key)[0]):
            klid = winreg.EnumKey(key, i)
            with winreg.OpenKey(key, klid) as sub:
                names[klid.lower()] = winreg.QueryValueEx(sub, "Layout Text")[0]
    return names

def title(handle):
    buf = ct.create_unicode_buffer(512)
    user.GetWindowTextW(handle, buf, len(buf))
    return buf.value

def get_layout(handle):
    tid = user.GetWindowThreadProcessId(handle, None)
    return user.GetKeyboardLayout(tid)

def configure_wt():
    exe = Path(os.environ["WT_EXE"])
    settings = exe.parent / "settings" / "settings.json"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(json.dumps({
        "initialCols": 99, "initialRows": 32,
        "keybindings": [{"id":None, "keys":"ctrl+shift+c"}],
        "profiles":{"defaults":{"closeOnExit":"always","suppressApplicationTitle":True}}
    }), encoding="utf-8")

class Window:
    def __init__(self, name, command):
        assert Path(command[0]).is_file(), command
        self.name = name
        self.proc = subprocess.Popen([os.environ["WT_EXE"], "-w", "new", "new-tab",
                          "--title", name, "--suppressApplicationTitle", "-d", os.getcwd(),
                          *map(str, command)])
        def find():
            matches = []
            @ct.WINFUNCTYPE(wt.BOOL, hwnd, wt.LPARAM)
            def enum(h, _):
                if title(h) in (name, "Administrator: "+name):
                    matches.append(h)
                return True
            user.EnumWindows(enum, 0)
            return matches[0] if matches else None
        self.handle = until(find, 20, name)
        user.SetForegroundWindow(self.handle)
        until(lambda: user.GetForegroundWindow() == self.handle, 5, "focus")
        self.hkl = get_layout(self.handle)

    def switch(self, klid):
        h = user.LoadKeyboardLayoutW(klid, 0)
        if not h or h & 0xffff != int(klid[-4:],16):
            raise RuntimeError(f"failed to load {klid}: {h}")
        user.PostMessageW(self.handle, 0x50, 0, ct.c_ssize_t(h).value)
        until(lambda: get_layout(self.handle)==h, 3, "layout "+klid)
        self.hkl, self.klid = h, klid
        time.sleep(.1)

    def press(self, chord):
        fg = user.GetForegroundWindow()
        if fg != self.handle or get_layout(fg) != self.hkl:
            raise RuntimeError(f"wrong foreground or layout for {chord}: {self.handle} vs {fg}")
        send(chord)

    def close(self):
        if user.IsWindow(self.handle):
            user.PostMessageW(self.handle, 0x10, 0, 0)
            until(lambda: not user.IsWindow(self.handle), 8, "close WT")
        self.proc.wait(timeout=8)

def read_records(path):
    kernel.GetStdHandle.restype = wt.HANDLE
    con = kernel.GetStdHandle(-10)
    kernel.SetConsoleMode.argtypes = [wt.HANDLE, wt.DWORD]
    kernel.ReadConsoleInputW.argtypes = [wt.HANDLE, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD)]
    if not kernel.SetConsoleMode(con, 0x80):
        raise ct.WinError(ct.get_last_error())
    import struct
    with open(path, "w", encoding="utf-8", buffering=1) as out:
        while True:
            data = ct.create_string_buffer(20)
            n = wt.DWORD()
            if not kernel.ReadConsoleInputW(con, data, 1, ct.byref(n)):
                raise ct.WinError(ct.get_last_error())
            if n.value:
                kind, down, repeat, vk, sc, code, state = struct.unpack("<H2xiHHHHI", data.raw)
                if kind == 1 and down and vk not in (16,17,18):
                    print(f"vk={vk:02X} sc={sc:02X} u={code:04X} state={state:03X}",file=out)

def pilot():
    configure_wt()
    path = Path.cwd() / "raw.txt"
    w = Window("records-test", [sys.executable, Path(__file__).resolve(), path])
    try:
        until(path.exists)
        for klid, name in layouts().items():
            if klid not in ("00000409","00000415") and "Russian" not in name and "Armenian" not in name:
                continue
            w.switch(klid)
            print(f"{klid} {w.hkl&0xffffffff:08X} {name}", flush=True)
            for key in ["d","c","space","ctrl+c","ctrl+d","ctrl+r","ctrl+t","ctrl+z","ctrl+shift+c","ctrl+shift+z","altgr+a"]:
                size = path.stat().st_size
                w.press(key)
                time.sleep(.14)
                with open(path,"rb") as log:
                    log.seek(size)
                    print(key, log.read().decode().strip())
    finally:
        w.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        read_records(sys.argv[1])
    else:
        pilot()
