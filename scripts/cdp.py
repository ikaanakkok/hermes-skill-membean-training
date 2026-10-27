#!/usr/bin/env python3
"""Minimal, dependency-free Chrome DevTools Protocol CLI.

Built for agents that have a shell but no browser tool (Claude Code, Codex CLI,
plain scripts). Every command is a single process, so the whole point is that a
plain `Bash` call is enough to drive a signed-in Chrome profile.

No third-party packages: the WebSocket client below is implemented on top of
`socket`/`struct`, so `python3 scripts/cdp.py ...` works on any box with Python 3.8+.

Requires a Chrome started with --remote-debugging-port=9222.

Commands
  list                          page targets (id, url, title)
  state                         signed-in / login-page / google-login / unknown
  account [--expect EMAIL]      identity signals + gate verdict (exit 2 = mismatch)
  open URL                      open a new tab, print its target id
  close TARGET                  close a tab
  nav TARGET URL                navigate an existing tab
  reload TARGET                 reload
  eval TARGET EXPR              evaluate JS, print the JSON value
  eval-file TARGET PATH         evaluate JS read from a file (big snippets)
  probe TARGET                  Membean training-state probe (see references/dom-map.md)
  click TARGET SELECTOR|--text X   click by CSS selector or by exact innerText
  type TARGET TEXT [--selector CSS]  real key events, then Enter (--no-enter to skip)
  key TARGET ENTER|ESC|TAB      press one key
  shot TARGET OUT.png           screenshot the tab
  mapimg TARGET OUT.png         save the word-map PNG (fetched through the page)
  mapword TARGET                decode the word-map filename to the word (rot13)

TARGET is a target-id prefix, a URL substring, or the word `first`.
Exit codes: 0 ok, 1 error, 2 account-gate mismatch.
"""

import argparse
import base64
import codecs
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request

DEFAULT_PORT = int(os.environ.get("CDP_PORT", "9222"))
MEMBEAN_URL_HINT = "membean.com"


# ---------------------------------------------------------------- websocket

class WS:
    """Just enough RFC 6455 for CDP: client-masked text frames, no extensions."""

    def __init__(self, url, timeout=30.0):
        m = re.match(r"ws://([^/:]+):(\d+)(/.*)$", url)
        if not m:
            raise RuntimeError("bad websocket url: %s" % url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            "GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key)
        )
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake closed")
            head += chunk
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError("websocket handshake failed: %r" % head.split(b"\r\n")[0])
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        payload = text.encode()
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv(self):
        """Return the next text message, transparently handling ping/close/continuation."""
        data = b""
        opcode = None
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(ln)
            if op == 0x9:  # ping
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op == 0xA:  # pong
                continue
            if op == 0x8:  # close
                raise RuntimeError("websocket closed by peer")
            if op != 0x0:  # a new data frame (0x1 text / 0x2 binary)
                if data:
                    data = b""
                opcode = op
            data += payload
            if fin:
                return data.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------- cdp

def http_json(port, path, method="GET"):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else {}


class CDP:
    def __init__(self, port=DEFAULT_PORT):
        self.port = port
        self._id = 0
        self.browser_ws = None
        self.page_ws = None
        self.target = None

    # --- discovery
    def targets(self):
        return [t for t in http_json(self.port, "/json/list") if t.get("type") == "page"]

    def resolve(self, spec):
        pages = self.targets()
        if not pages:
            raise RuntimeError("no page targets on port %d" % self.port)
        if not spec or spec == "first":
            return pages[0]
        for t in pages:  # exact / prefix target id
            if t["id"] == spec or (len(spec) >= 4 and t["id"].startswith(spec)):
                return t
        for t in pages:  # url substring
            if spec.lower() in t.get("url", "").lower():
                return t
        raise RuntimeError("no target matches %r; try: cdp.py list" % spec)

    def membean_target(self):
        for t in self.targets():
            if MEMBEAN_URL_HINT in t.get("url", ""):
                return t
        raise RuntimeError("no Membean tab open; open https://membean.com/dashboard first")

    # --- connections
    def browser(self):
        if self.browser_ws is None:
            self.browser_ws = WS(http_json(self.port, "/json/version")["webSocketDebuggerUrl"])
        return self.browser_ws

    def page(self, spec=None):
        if self.page_ws is None:
            self.target = self.membean_target() if spec is None else self.resolve(spec)
            self.page_ws = WS(self.target["webSocketDebuggerUrl"], timeout=60.0)
        return self.page_ws

    def _call_on(self, ws, method, **params):
        self._id += 1
        mid = self._id
        ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s failed: %s" % (method, msg["error"]))
                return msg.get("result", {})

    # --- api
    def call(self, method, **params):
        return self._call_on(self.page(), method, **params)

    def evaluate(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True,
                      awaitPromise=True, userGesture=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("JS error: %s" % r["exceptionDetails"].get("text"))
        return r.get("result", {}).get("value")

    def activate(self, target):
        try:
            self._call_on(self.browser(), "Target.activateTarget", targetId=target["id"])
        except Exception:
            pass  # activation is a nicety; input still works on most builds
        time.sleep(0.4)

    def navigate(self, url, wait=3.0):
        self.call("Page.navigate", url=url)
        time.sleep(wait)

    def reload(self, wait=3.0):
        self.call("Page.reload", ignoreCache=False)
        time.sleep(wait)


# ---------------------------------------------------------------- js helpers

PROBE = r"""
(() => {
  const w = document.querySelector('#review-wrapper');
  const bar = document.querySelector('#timer-container .x-progress-bar');
  const img = document.querySelector('#constellation img');
  return JSON.stringify({
    url: location.href,
    growl: (document.querySelector('#user-growl') || {}).innerText || '',
    type: w ? w.className : null,
    text: (w ? w.innerText : document.body.innerText).slice(0, 1200),
    choices: [...document.querySelectorAll('li.choice')].map(e => e.innerText.trim()),
    wordmap: img ? img.src : null,
    textInputs: [...document.querySelectorAll('input[type=text],textarea')]
      .filter(e => e.offsetParent).map(e => e.name || e.id),
    submits: [...document.querySelectorAll('input[type=submit]')]
      .filter(e => e.offsetParent).map(e => e.value),
    timeout: (document.querySelector('#timer-container') || {dataset:{}}).dataset.timeout || null,
    bar: bar ? bar.style.width : null,
    doneBtn: (document.querySelector('#done-btn') || {}).value || '',
    status: (document.querySelector('#answer-status') || {}).innerText || ''
  });
})()
"""

ACCOUNT_SIGNALS = r"""
(async () => {
  const txt = (document.body.innerText || '');
  const html = document.documentElement.innerHTML || '';
  const wel = txt.match(/(?:Welcome|Hi|Hello)[,!]?\s+([A-Z][\w'’.-]{1,30})/);
  const cls = txt.match(/([A-Z][A-Za-z]+(?:\s+[A-Za-z]+){0,3}\s+L?\d+\s*\([IVX]+\))/)
           || txt.match(/([A-Z][A-Za-z ]{2,24}\s+(?:Grade|Level)\s+\d+)/);
  const mailtos = [...document.querySelectorAll('a[href^="mailto:"]')]
        .map(a => a.href.replace('mailto:', '').split('?')[0]);
  const bodyMails = html.match(/[A-Za-z0-9._%+-]+@(?!membean\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g) || [];
  // Membean puts a base64 user_id on outbound links; it is a stable account fingerprint.
  let fp = null, fpRaw = null;
  for (const a of document.querySelectorAll('a[href*="user_id="]')) {
    const m = a.getAttribute('href').match(/user_id=([^&]+)/);
    if (m) { fpRaw = m[1]; try { fp = atob(m[1]); } catch (e) { fp = null; } break; }
  }
  const links = [...document.querySelectorAll('a[href]')].map(a => a.href)
    .filter(h => /log ?out|sign ?out|setting|profile|account/i.test(h)).slice(0, 8);
  return JSON.stringify({
    url: location.href,
    title: document.title,
    welcome_name: wel ? wel[1] : null,
    class_label: cls ? cls[1] : null,
    emails: [...new Set(mailtos.concat(bodyMails))].slice(0, 5),
    password_field: !!document.querySelector('input[type=password]'),
    google_sso_btn: !!document.querySelector('a.sso-login-btn-google'),
    google_chooser: document.querySelectorAll('div[role=link][data-identifier]').length,
    identifiers: [...document.querySelectorAll('[data-identifier]')]
        .map(e => e.getAttribute('data-identifier')),
    user_id: fp,
    user_id_raw: fpRaw,
    head: txt.replace(/\s+/g, ' ').slice(0, 400),
    links: links
  });
})()
"""


def js_click_selector(sel):
    return "(function(){var el=document.querySelector(%s); if(!el) return 'NOT_FOUND'; el.click(); return 'CLICKED';})()" % json.dumps(sel)


def js_click_text(text):
    return ("(function(){var t=%s;var el=[...document.querySelectorAll('li.choice,a,button,input[type=submit]')]"
            ".find(e=>(e.innerText||'').trim()===t||(e.value||'')===t);"
            "if(!el) return 'NOT_FOUND'; el.click(); return 'CLICKED';})()" % json.dumps(text))


# --------------------------------------------------------------------- main

def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_list(c, a):
    out([{"id": t["id"], "url": t.get("url"), "title": t.get("title")} for t in c.targets()])


def _signals(c):
    return json.loads(c.evaluate(ACCOUNT_SIGNALS))


def _classify(sig):
    if sig["password_field"]:
        return "password-required"
    if sig["google_chooser"]:
        return "google-account-chooser"
    if sig["google_sso_btn"]:
        return "membean-login-page"
    if sig["welcome_name"]:
        return "signed-in"
    if "membean.com" in sig["url"] and "/login" not in sig["url"]:
        return "signed-in-unverified"
    return "unknown"


def cmd_state(c, a):
    sig = _signals(c)
    out({"state": _classify(sig), "signals": sig})


def cmd_account(c, a):
    """Identity gate: exit 0 only when the page matches the expected identity."""
    sig = _signals(c)
    state = _classify(sig)
    exp = (a.expect or "").strip()
    exp_class = (a.expect_class or "").strip().lower()
    hay = [x.lower() for x in ([sig["welcome_name"] or ""] + sig["emails"] + [sig["user_id"] or ""]) if x]
    verdict, why = "mismatch", ""

    if state in ("password-required", "membean-login-page", "google-account-chooser"):
        why = "not signed in (%s): run `cdp.py sso --expect <account>`" % state
    elif state == "unknown":
        why = "page is not a signed-in Membean page: %r" % sig["url"]
    elif not exp:
        verdict, why = "unknown", "no --expect given; state the expected account first (gate G1)"
    elif not any(exp.lower() in h for h in hay):
        why = ("expected %r not on page; page shows name=%r class=%r user_id=%r"
               % (exp, sig["welcome_name"], sig["class_label"], sig["user_id"]))
    elif exp_class and exp_class not in (sig["class_label"] or "").lower():
        why = "name matches but class is %r, expected %r" % (sig["class_label"], a.expect_class)
    else:
        verdict, why = "match", "name/email/fingerprint and class agree with the expectation"

    out({"verdict": verdict, "why": why, "expected": exp,
         "expected_class": a.expect_class, "state": state, "signals": sig})
    sys.exit(0 if verdict == "match" else 2)


def cmd_open(c, a):
    t = http_json(c.port, "/json/new?" + urllib.parse.quote(a.url, safe=":/?&=%#"), method="PUT")
    out({"id": t["id"], "url": t.get("url")})


def cmd_close(c, a):
    t = c.resolve(a.target)
    c._call_on(c.browser(), "Target.closeTarget", targetId=t["id"])
    out({"closed": t["id"]})


def cmd_nav(c, a):
    c.page(a.target)
    c.navigate(a.url, a.wait)
    out({"url": c.evaluate("location.href")})


def cmd_reload(c, a):
    c.page(a.target)
    c.reload(a.wait)
    out({"url": c.evaluate("location.href")})


def cmd_eval(c, a):
    c.page(a.target)
    print(json.dumps(c.evaluate(a.expr), indent=2, ensure_ascii=False, default=str))


def cmd_eval_file(c, a):
    c.page(a.target)
    with open(os.path.expanduser(a.path), encoding="utf-8") as fh:
        print(json.dumps(c.evaluate(fh.read()), indent=2, ensure_ascii=False, default=str))


def cmd_probe(c, a):
    c.page(a.target)
    out(json.loads(c.evaluate(PROBE)))


def cmd_click(c, a):
    c.page(a.target)
    if a.text:
        res = c.evaluate(js_click_text(a.text))
    else:
        res = c.evaluate(js_click_selector(a.selector))
    out({"result": res})


def cmd_type(c, a):
    text = a.text
    ws = c.page(a.target)
    c.activate(c.target)
    c.evaluate("(function(){var el=document.querySelector(%s); if(!el) throw 'no input'; el.focus(); return el.value})()" % json.dumps(a.selector))
    c.call("Runtime.evaluate", expression="1")  # keep the socket warm
    for ch in text:
        c.call("Input.dispatchKeyEvent", type="char", text=ch)
        time.sleep(0.12)
    if not a.no_enter:
        for t, extra in (("rawKeyDown", {"windowsVirtualKeyCode": 13, "key": "Enter", "code": "Enter"}),
                         ("char", {"text": "\r"}),
                         ("keyUp", {"windowsVirtualKeyCode": 13, "key": "Enter", "code": "Enter"})):
            c.call("Input.dispatchKeyEvent", type=t, **extra)
    value = c.evaluate("document.querySelector(%s).value" % json.dumps(a.selector))
    out({"typed_value": value, "expected": text})


KEYS = {"ENTER": 13, "TAB": 9, "ESC": 27, "SPACE": 32}


def cmd_key(c, a):
    name = a.key.upper()
    code = KEYS.get(name)
    if not code:
        raise SystemExit("unknown key %r (ENTER/TAB/ESC/SPACE)" % a.key)
    c.page(a.target)
    c.activate(c.target)
    for t, extra in (("rawKeyDown", {"windowsVirtualKeyCode": code, "key": name.title(), "code": name.title()}),
                     ("keyUp", {"windowsVirtualKeyCode": code, "key": name.title(), "code": name.title()})):
        c.call("Input.dispatchKeyEvent", type=t, **extra)
    out({"pressed": name})


def cmd_shot(c, a):
    c.page(a.target)
    data = c.call("Page.captureScreenshot", format="png")["data"]
    path = os.path.expanduser(a.path)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(data))
    out({"saved": path, "bytes": os.path.getsize(path)})


def fetch_through_page(c, js_url_expr, path):
    """Read a cross-origin image via fetch() inside the page, then write it locally."""
    code = ("fetch(%s).then(r=>r.blob()).then(b=>new Promise(res=>{const fr=new FileReader();"
            "fr.onload=()=>res(fr.result);fr.readAsDataURL(b);}))" % js_url_expr)
    data_url = c.evaluate(code)
    raw = base64.b64decode(data_url.split(",", 1)[1])
    with open(path, "wb") as fh:
        fh.write(raw)
    return len(raw)


def cmd_mapimg(c, a):
    c.page(a.target)
    src = c.evaluate("(document.querySelector('#constellation img')||{}).src || null")
    if not src:
        raise SystemExit("no #constellation img on this step")
    path = os.path.expanduser(a.path)
    n = fetch_through_page(c, json.dumps(src), path)
    fname = src.rsplit("/", 1)[-1].split(".")[0]
    cand = codecs.decode(fname, "rot13").replace("mem", "", 1).replace("bean", "")
    out({"saved": path, "bytes": n, "src": src, "filename_word_guess": cand})


def cmd_mapword(c, a):
    c.page(a.target)
    src = c.evaluate("(document.querySelector('#constellation img')||{}).src || null")
    if not src:
        raise SystemExit("no #constellation img on this step")
    fname = src.rsplit("/", 1)[-1].split(".")[0]
    out({"src": src, "filename_word_guess": codecs.decode(fname, "rot13").replace("mem", "", 1).replace("bean", "")})


def cmd_sso(c, a):
    """Membean 'Sign in with Google' -> pick the account by data-identifier."""
    c.page(a.target)
    expected = (a.expect or "").strip().lower()
    if not expected:
        raise SystemExit("--expect EMAIL is required (choose the account by identifier, never by position)")
    if c.evaluate("!!document.querySelector('a.sso-login-btn-google')"):
        c.evaluate(js_click_selector("a.sso-login-btn-google"))
        time.sleep(4)
    sig = _signals(c)
    if sig["password_field"] and not sig["google_chooser"]:
        raise SystemExit("password field appeared: STOP, hand the sign-in to the human")
    if sig["google_chooser"]:
        expr = ("(function(){var el=document.querySelector('[data-identifier=%s]');"
                "if(!el) return 'IDENTIFIER_NOT_IN_CHOOSER'; el.click(); return 'CLICKED';})()"
                % json.dumps(expected))
        res = c.evaluate(expr)
        if res != "CLICKED":
            raise SystemExit("expected account %s is not in the chooser; identifiers=%s"
                             % (expected, sig["identifiers"]))
        time.sleep(7)
    out({"url": c.evaluate("location.href"), "signals": _signals(c)})


def main(argv=None):
    p = argparse.ArgumentParser(description="dependency-free CDP CLI")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = p.add_subparsers(dest="cmd", required=True)

    def sub_target(name, fn, target_required=False, **extra):
        sp = sub.add_parser(name)
        if target_required:
            sp.add_argument("target", help="target id prefix or URL substring")
        else:
            sp.add_argument("target", nargs="?", default=None,
                            help="target id prefix or URL substring")
        for flag, kw in extra.items():
            sp.add_argument(flag, **kw)
        sp.set_defaults(func=fn)
        return sp

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub_target("state", cmd_state)
    sp = sub_target("account", cmd_account, **{"--expect": {"default": None},
                                                "--expect-class": {"dest": "expect_class", "default": None}})
    sp = sub.add_parser("open")
    sp.add_argument("url")
    sp.set_defaults(func=cmd_open)
    sub_target("close", cmd_close)
    sp = sub_target("nav", cmd_nav, **{"--wait": {"type": float, "default": 3.0}})
    sp.add_argument("url")
    sub_target("reload", cmd_reload, **{"--wait": {"type": float, "default": 3.0}})
    sp = sub_target("eval", cmd_eval)
    sp.add_argument("expr")
    sp = sub_target("eval-file", cmd_eval_file)
    sp.add_argument("path")
    sub_target("probe", cmd_probe)
    sp = sub_target("click", cmd_click, **{"--selector": {"default": None}, "--text": {"default": None}})
    sp = sub_target("type", cmd_type, target_required=True,
                    **{"--selector": {"default": "input[type=text]"},
                       "--no-enter": {"action": "store_true"}})
    sp.add_argument("text")
    sp = sub_target("key", cmd_key)
    sp.add_argument("key", choices=["enter", "tab", "esc", "space", "ENTER", "TAB", "ESC", "SPACE"])
    sp = sub_target("shot", cmd_shot)
    sp.add_argument("path")
    sp = sub_target("mapimg", cmd_mapimg)
    sp.add_argument("path", nargs="?", default="/tmp/wordmap.png")
    sub_target("mapword", cmd_mapword)
    sp = sub_target("sso", cmd_sso)
    sp.add_argument("--expect", default=None)

    a = p.parse_args(argv)
    try:
        c = CDP(a.port)
        a.func(c, a)
    except RuntimeError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
