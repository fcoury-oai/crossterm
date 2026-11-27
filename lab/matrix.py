from desktop import Window, configure_wt, layouts, until
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

us = "00000409"
regular = {us:"dD", "00000419":"вВ", "00020419":"дД", "0002042b":"դԴ", "0000042b":"դԴ"}

def launch(binary, root):
    home = root / "home"
    env = dict(os.environ, CODEX_HOME=str(home), OPENAI_API_KEY="dummy", RUST_LOG="trace")
    (root / "wrapper").touch()
    code = subprocess.call([binary, "--no-daemon", "-C", root / "workspace"], env=env, cwd=root / "workspace")
    (root / "exit").write_text(str(code))
    if code:
        time.sleep(20)

class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"models":[]}')
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path != "/v1/responses":
            self.send_error(404)
            return
        contents = json.loads(body)["input"]
        messages = [block.get("text") for item in contents if item.get("role") == "user"
                    for block in item.get("content", []) if block.get("type") == "input_text"]
        if "hold" not in messages:
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_hold"}}\n\n')
        self.wfile.flush()
        self.server.active.set()
        try:
            while not self.server.stop.wait(.08):
                self.wfile.write(b": waiting\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            self.server.disconnected.set()

def configure(root, port):
    (root / "workspace").mkdir(parents=True)
    home = root / "home"
    home.mkdir()
    config = f"""model = 'gpt-6-sol'
model_provider = 'fixture'
log_dir = '{root / "log"}'
check_for_update_on_startup = false
suppress_unstable_features_warning = true
[model_providers.fixture]
name = 'Fixture'
base_url = 'http://127.0.0.1:{port}/v1'
wire_api = 'responses'
requires_openai_auth = false
supports_websockets = false
[projects.'{root / "workspace"}']
trust_level = 'trusted'
[tui]
fullscreen_transcript = false
alternate_screen = 'always'
[analytics]
enabled = false
"""
    (home / "config.toml").write_text(config, encoding="utf-8")
    (home / "auth.json").write_text('{"OPENAI_API_KEY":"dummy"}')

class Screen:
    def __init__(self, window):
        self.handle = window.handle
        self.process = subprocess.Popen(
            ["powershell.exe","-NoProfile","-File",Path(__file__).with_name("screen.ps1").resolve()],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,encoding="utf-8")
    def read(self):
        self.process.stdin.write(str(self.handle)+"\n")
        self.process.stdin.flush()
        raw = json.loads(self.process.stdout.readline())
        return "\n".join(x.rstrip() for x in raw.splitlines() if x.strip())
    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)

c_pair = {us:"cC", "00000419":"сС", "00020419":"цЦ", "0002042b":"ցՑ", "0000042b":"գԳ"}
placeholder = "Ask Codex to do anything"
search = "reverse-i-search"
transcript = "T R A N S C R I P T"
working = "esc to interrupt"
interrupted = "Conversation interrupted"

def composer(text):
    for line in reversed(text.splitlines()):
        if line.strip().startswith("› "):
            return line.strip()[2:]
    return None

def abort_reason(root):
    for path in (root / "home" / "sessions").rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line).get("payload", {})
            except json.JSONDecodeError:
                continue
            if record.get("type") == "turn_aborted":
                return record.get("reason")
    return None

class Comparison:
    def __init__(self, side, klid):
        self.side, self.klid = side, klid
        self.root = Path(os.environ["RUNNER_TEMP"]) / (side+"-"+klid)
        self.server = ThreadingHTTPServer(("127.0.0.1",0), Fixture)
        self.server.stop, self.server.active, self.server.disconnected = [threading.Event() for _ in range(3)]
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        configure(self.root,self.server.server_port)
        binary = Path(f"pair/{side}/codex.exe").resolve()
        with binary.open("rb") as f:
            self.digest = hashlib.file_digest(f,"sha256").hexdigest()
        version = subprocess.check_output([binary,"--version"], text=True).strip()
        print(f"{side} {version} SHA256 {self.digest}")
        self.window = Window("codex-"+side,[sys.executable,Path(__file__).resolve(),"launch",binary,self.root])
        self.screen = Screen(self.window)
        self.results = {}
        self.exit = self.root/"exit"

    def wait(self, check, timeout=5):
        def poll():
            if self.exit.exists():
                raise RuntimeError(f"unexpected exit {self.exit.read_text()}")
            text = self.screen.read()
            if text.startswith("UIA:"):
                raise RuntimeError(text)
            return text if check(text) else None
        return until(poll, timeout=timeout)

    def draft(self, value, timeout=5):
        return self.wait(lambda text: composer(text)==value, timeout)

    def press(self, chord):
        self.window.press(chord)

    def us(self, chord):
        self.window.switch(us)
        self.press(chord)
        time.sleep(.24)
        self.window.switch(self.klid)

    def record(self, label, success, outcome):
        w = self.window
        self.results[(w.klid,label)] = (success,outcome)
        print(f"{self.side} {w.klid} HKL {w.hkl&0xffffffff:08X} | {label} | {outcome}")

    def clear(self):
        self.us("ctrl+c")
        self.draft(placeholder)

    def transition(self, label, chord, expected, original, effect, fallback):
        self.press(chord)
        try:
            self.wait(expected, 1.8)
        except TimeoutError:
            assert original(self.screen.read()), f"unexpected effect of {label}"
            self.record(label, False, fallback)
            return False
        self.record(label, True, effect)
        return True

    def regular_text(self):
        self.press("d")
        self.press("shift+d")
        self.draft(regular[self.klid])
        for key in ["c","shift+c"]:
            self.press(key)
            if self.klid=="00020419":
                self.press("space")
        expected = regular[self.klid] + c_pair[self.klid]
        self.draft(expected)
        self.record("Text (D, Shift+D, C, Shift+C)", True, expected)
        return expected

    def clear_chords(self, first):
        empty = lambda t: composer(t)==placeholder
        for label,key in [("Ctrl+C · draft","ctrl+c"),("Ctrl+Shift+C · draft","ctrl+shift+c"),("Right Ctrl+C · draft","rc+c")]:
            if key=="ctrl+c":
                draft = first
            else:
                self.press("d")
                draft = regular[self.klid][0]
            self.draft(draft)
            if not self.transition(label,key,empty,lambda t: composer(t)==draft,"Cleared draft",f"Retained {draft}"):
                self.clear()
                print(f"  Switching to US and pressing Ctrl+C cleared the same draft {draft}")

    def views(self):
        empty = lambda t: composer(t)==placeholder and search not in t and transcript not in t
        for label,key,marker,outcome in [
            ("Ctrl+R","ctrl+r",search,"Opened history search"),
            ("Ctrl+T","ctrl+t",transcript,"Opened transcript"),
            ("Ctrl+R · Caps Lock on","ctrl+r",search,"Opened history search")
        ]:
            self.wait(empty)
            caps = "Caps Lock" in label
            if caps:
                self.press("caps")
            opened = self.transition(label,key,lambda text: marker in text,empty,outcome,"Stayed in composer")
            if caps:
                self.press("caps")
            if opened:
                if marker==transcript:
                    self.us("q")
                else:
                    self.press("esc")
                self.wait(empty)

    def edit_history(self):
        self.draft(placeholder)
        self.press("d")
        token = regular[self.klid][0]
        self.draft(token)
        empty = lambda t: composer(t)==placeholder
        typed = lambda t: composer(t)==token
        if not self.transition("Ctrl+Z","ctrl+z",empty,typed,"Undid insertion",f"Retained {token}"):
            self.us("ctrl+z")
            self.draft(placeholder)
        if self.transition("Ctrl+Shift+Z","ctrl+shift+z",typed,empty,f"Restored {token}","Stayed empty"):
            self.clear()

    def altgr(self):
        self.window.switch("00000415")
        self.draft(placeholder)
        self.press("altgr+a")
        self.draft("ą")
        self.record("AltGr+A · Polish (Programmers)",True,"Typed ą (U+0105)")
        self.clear()

    def turn(self):
        self.window.switch(us)
        self.draft(placeholder)
        for k in "hold":
            self.press(k)
        self.draft("hold")
        time.sleep(.18)
        self.press("enter")
        until(self.server.active.is_set,30,"loopback POST containing hold")
        self.wait(lambda t: working in t,10)
        self.window.switch(self.klid)
        assert not self.server.disconnected.is_set()
        stopped = lambda t: interrupted in t and working not in t
        active = lambda t: working in t and not self.server.disconnected.is_set() and not abort_reason(self.root)
        if not self.transition("Ctrl+C · held turn","ctrl+c",stopped,active,"Conversation interrupted","Still working, stream open"):
            self.us("ctrl+c")
            self.wait(stopped)
            print("  Switching to US and pressing Ctrl+C interrupted the same turn")
        until(self.server.disconnected.is_set,5,"SSE client disconnect")
        self.draft(placeholder)
        print("  Fixture received user message 'hold', sent response.created, held stream, observed disconnect")

    def quit(self):
        self.draft(placeholder)
        self.press("ctrl+d")
        try:
            until(self.exit.exists,3,"exit")
        except TimeoutError:
            self.draft(placeholder)
            self.press("d")
            self.draft(regular[self.klid][0])
            self.record("Ctrl+D · empty",False,"Stayed open, next key typed")
            self.clear()
            self.window.switch(us)
            self.press("ctrl+d")
            until(self.exit.exists)
        else:
            self.record("Ctrl+D · empty",True,"Exited (0)")
        assert self.exit.read_text()=="0"
        reason = abort_reason(self.root)
        print("  Persisted turn_aborted reason",reason)
        assert reason=="interrupted"

    def run(self):
        try:
            self.draft(placeholder,30)
            self.window.switch(self.klid)
            self.clear_chords(self.regular_text())
            self.views()
            self.edit_history()
            if self.klid==us:
                self.altgr()
            self.turn()
            self.quit()
            return self.results
        except Exception:
            print("Last terminal view",self.screen.read())
            raise
        finally:
            self.screen.close()
            self.window.close()
            self.server.stop.set()
            self.server.shutdown()

def matrix(klid):
    configure_wt()
    name = layouts()[klid]
    print(f"Windows {platform.version()} {platform.machine()} Terminal 1.24.12741.0 layout {name}")
    sides = ["before","after"] if Path("pair/after").exists() else ["before"]
    rows = {}
    for side in sides:
        rows[side] = Comparison(side,klid).run()
    with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as out:
        print(f"### {name} ({klid})\n",file=out)
        print("| Layout | Key | "+" | ".join(sides)+" |",file=out)
        print("| --- | --- |"+" --- |"*len(sides),file=out)
        for key in rows["before"]:
            print("| "+" | ".join((*key,*(rows[s][key][1] for s in sides)))+" |",file=out)
    for side in sides:
        for key,(success,_) in rows[side].items():
            if side=="after" or (klid==us and "Caps Lock" not in key[1]):
                assert success,(side,key)
            if side=="before" and klid!=us and key[1].startswith(("Ctrl+C","Ctrl+D")):
                assert not success,(side,key)

if __name__ == "__main__":
    if sys.argv[1] == "launch":
        launch(sys.argv[2], Path(sys.argv[3]))
    else:
        matrix(sys.argv[1])
