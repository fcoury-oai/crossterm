from desktop import Window, configure_wt, layouts, until
import contextlib
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

def pilot(binary):
    root = Path(os.environ["RUNNER_TEMP"]) / "pilot"
    server = ThreadingHTTPServer(("127.0.0.1",0), Fixture)
    server.stop, server.active, server.disconnected = [threading.Event() for _ in range(3)]
    threading.Thread(target=server.serve_forever,daemon=True).start()
    configure(root,server.server_port)
    configure_wt()
    w = Window("codex-pilot",[sys.executable,Path(__file__).resolve(),"launch",binary,root])
    screen = Screen(w)
    time.sleep(4)
    print("startup",screen.read())
    w.switch(us)
    for key in ["d","shift+d","ctrl+c","ctrl+r","esc","ctrl+t","esc","h","o","l","d","enter","ctrl+c","ctrl+d"]:
        if (root/"exit").exists():
            print("exited",(root/"exit").read_text())
            break
        w.press(key)
        time.sleep(.52 if key!="enter" else 3)
        print(key,repr(screen.read()))
    print("response",server.active.is_set(),server.disconnected.is_set())
    screen.close()
    w.close()
    server.stop.set()

if __name__ == "__main__":
    if sys.argv[1] == "launch":
        launch(sys.argv[2], Path(sys.argv[3]))
    else:
        pilot(Path(sys.argv[1]).resolve())
