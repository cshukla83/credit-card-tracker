"""Drive a headless Chrome over the DevTools protocol -- stdlib only.

Written in Session 93 to replace "traced, not seen" with an actual live
check of DOM / scroll / rendering behaviour when the Claude-in-Chrome
extension is not connected. Needs a real Chrome or Chromium binary (the
path below is the macOS default) and nothing else: the websocket client
is hand-rolled on `socket`, so no package is installed for it.

It is a library, not a command: a verification script imports it, points
a browser at a locally running app, and evaluates JavaScript in the page.

Typical use, from the project root with the venv active, with the app
running on a scratchpad COPY of the database (never data/tracker.db):

    DB_PATH=/path/to/copy.db venv/bin/uvicorn main:app --port 8765

    from scripts.headless_chrome import launch, evaluate
    proc, ws = launch("/path/to/scratch/profile")     # any writable dir
    try:
        ws.call("Page.enable")
        ws.call("Page.navigate", url="http://localhost:8765/")
        # ... time.sleep for the load, then measure anything the page can:
        print(evaluate(ws, "scrollY"))
        print(evaluate(ws, "document.querySelector('#selection-bar').getBoundingClientRect().top"))
    finally:
        proc.terminate()

`evaluate` returns the value of the last expression (JSON-serialisable,
promises awaited); a page-side exception is raised here. Session 93's
scroll-reset measurement was ~30 lines on top of this: scroll deep,
click a checkbox, read scrollY and a row's bounding rect before/after.

Committed as written and verified in Session 93 -- not generalised.
"""
import base64, json, os, socket, struct, subprocess, sys, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

class WS:
    def __init__(self, url):
        _, rest = url.split("://", 1)
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf: buf += self.s.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.n = 0
    def send(self, method, **params):
        self.n += 1
        data = json.dumps({"id": self.n, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        hdr = bytes([0x81])
        L = len(data)
        if L < 126: hdr += bytes([0x80 | L])
        elif L < 65536: hdr += bytes([0x80 | 126]) + struct.pack(">H", L)
        else: hdr += bytes([0x80 | 127]) + struct.pack(">Q", L)
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        return self.n
    def _read(self, n):
        while len(self.buf) < n: self.buf += self.s.recv(65536)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out
    def recv(self):
        b0, b1 = self._read(2)
        L = b1 & 0x7f
        if L == 126: L = struct.unpack(">H", self._read(2))[0]
        elif L == 127: L = struct.unpack(">Q", self._read(8))[0]
        return json.loads(self._read(L))
    def call(self, method, **params):
        i = self.send(method, **params)
        while True:
            m = self.recv()
            if m.get("id") == i: return m.get("result", m)

def launch(profile):
    p = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={profile}",
                          "--window-size=1200,800", "--no-first-run", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
            page = next(t for t in tabs if t["type"] == "page")
            return p, WS(page["webSocketDebuggerUrl"])
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("chrome did not start")

def evaluate(ws, expr):
    r = ws.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
    if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("text"))
    return r["result"].get("value")
