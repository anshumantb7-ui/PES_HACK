"""
Full regression of the offline SOS page in a real Chromium browser.

  npm run build                       (once, so dist/ exists)
  pip install playwright && playwright install chromium     (once)
  python tests/e2e/regression.py

Covers Stage 1 (message), Stage 2 (GPS), Stage 3 (offline), Stage 4 (install, readiness)
and the error paths. Takes about two minutes. Exit code 0 means everything passed.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
SERVE = Path(__file__).with_name("serve_dist.py")

def gateway_number():
    n = os.environ.get("VITE_GATEWAY_NUMBER", "").strip()
    env = ROOT / ".env.local"
    if not n and env.exists():
        m = re.search(r"^VITE_GATEWAY_NUMBER=(.*)$", env.read_text(), re.M)
        n = m.group(1).strip() if m else ""
    return n

NUM = gateway_number()
if not (DIST / "index.html").exists() or not NUM:
    sys.exit("Need a built dist/ (npm run build) and VITE_GATEWAY_NUMBER in .env.local")

GEO = {"latitude": 12.9345, "longitude": 77.6123, "accuracy": 8}
MSG = "FLOOD | TRAPPED | 12.93450,77.61230"
ENC = "FLOOD%20%7C%20TRAPPED%20%7C%2012.93450%2C77.61230"
ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/141 Mobile Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1"
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""), flush=True)

def serve(directory, port, redirect=False):
    cmd = [sys.executable, str(SERVE), "--dir", str(directory), "--port", str(port)] + (["--redirect-index"] if redirect else [])
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    return p

def stop(p):
    p.terminate()
    p.wait()

def text(page, sel):
    return page.locator(sel).inner_text()

def wait_ready(page):
    page.wait_for_function("document.getElementById('st-cache').textContent.startsWith('Yes')", timeout=15000)

def wait_msg(page):
    page.wait_for_function("document.getElementById('preview').textContent.includes('|')", timeout=10000)

def poll(fn, tries=30, delay=0.5):
    value = None
    for _ in range(tries):
        value = fn()
        if value:
            return value
        time.sleep(delay)
    return value

MOCK_GEO = """
(() => {
  const watchers = [];
  const geo = {
    watchPosition(ok, err) { watchers.push({ ok, err }); return watchers.length; },
    clearWatch() {},
    getCurrentPosition(ok, err) { watchers.push({ ok, err }); },
  };
  Object.defineProperty(navigator, 'geolocation', { value: geo, configurable: true });
  window.__fix = (lat, lon, acc) => watchers.forEach(w => w.ok({ coords: { latitude: lat, longitude: lon, accuracy: acc }, timestamp: Date.now() }));
  window.__err = (code) => watchers.forEach(w => w.err({ code }));
})();
"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # ===== A. Stages 1-4: first visit online, then fully offline =====
    srv = serve(DIST, 4173)
    ctx = browser.new_context(permissions=["geolocation"], geolocation=GEO, viewport={"width": 390, "height": 844}, user_agent=ANDROID)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto("http://localhost:4173/")
    wait_ready(page)
    check("A1 first visit: service worker active, page saved", text(page, "#st-cache").startswith("Yes"), text(page, "#st-cache"))
    page.wait_for_function("document.getElementById('ready').textContent.startsWith('Ready')", timeout=10000)
    items = page.locator("#checklist li").all_inner_texts()
    check("A2 readiness: Ready, 3-item checklist, home screen optional", len(items) == 3 and "(optional)" in items[2] and items[0].startswith("✓") and items[1].startswith("✓"), str(items))
    wait_msg(page)
    check("A3 live GPS gives the exact message format", text(page, "#preview") == MSG, text(page, "#preview"))
    check("A4 coordinates line shows GPS accuracy", "GPS ±8 m" in text(page, "#coords"), text(page, "#coords"))
    link = page.locator("#sos").get_attribute("data-link")
    check("A5 SOS enabled with the Android sms link", page.locator("#sos").is_enabled() and link == f"sms:{NUM}?body={ENC}", link)
    check("A6 dev panel absent from the production page", page.locator("#dev").count() == 0 and page.locator("#useTest").count() == 0)
    check("A7 'send without location' hidden while GPS works", page.locator("#nogps").is_hidden())
    check("A8 length line shows GSM-7 count", "GSM-7 units" in text(page, "#meta"), text(page, "#meta"))
    cdp = ctx.new_cdp_session(page)
    inst = cdp.send("Page.getInstallabilityErrors")
    check("A9 Chrome reports no installability errors", inst.get("installabilityErrors") == [], json.dumps(inst))
    check("A10 manifest parsed without errors", not cdp.send("Page.getAppManifest").get("errors"))
    keys = page.evaluate("caches.keys()")
    check("A11 exactly one resq cache", len(keys) == 1 and keys[0].startswith("resq-sos-"), str(keys))
    count = page.evaluate("caches.open(%s).then(c => c.keys()).then(k => k.length)" % json.dumps(keys[0]))
    check("A12 cache holds every built file", count == len(json.loads(re.search(r"const PRECACHE = (\[[\s\S]*?\]);", (DIST / 'sw.js').read_text()).group(1))), str(count))
    page.reload()
    wait_ready(page)
    check("A13 after reload the page is controlled by the worker", page.evaluate("!!navigator.serviceWorker.controller"))

    stop(srv)                       # the server is really dead...
    ctx.set_offline(True)           # ...and the browser has no network
    time.sleep(0.5)
    page.reload()
    wait_msg(page)
    check("A14 OFFLINE reload (server dead) still loads the app", text(page, "h1") == "RESQ Emergency SOS")
    check("A15 OFFLINE live GPS gives the message", text(page, "#preview") == MSG, text(page, "#preview"))
    check("A16 OFFLINE network line says no internet", "No internet" in text(page, "#st-network"), text(page, "#st-network"))
    page.wait_for_function("document.getElementById('ready').textContent.startsWith('Ready')", timeout=10000)
    check("A17 OFFLINE readiness still Ready", text(page, "#ready").startswith("Ready"), text(page, "#ready"))
    check("A18 OFFLINE SOS enabled with sms link", page.locator("#sos").is_enabled() and page.locator("#sos").get_attribute("data-link").startswith(f"sms:{NUM}?body="))
    page.select_option("#type", "FIRE")
    page.select_option("#status", "UNCONSCIOUS")
    check("A19 OFFLINE type/status changes rebuild the message", text(page, "#preview") == "FIRE | UNCONSCIOUS | 12.93450,77.61230", text(page, "#preview"))
    ctx.set_geolocation({"latitude": 12.94, "longitude": 77.62, "accuracy": 12})
    page.wait_for_function("document.getElementById('preview').textContent.includes('12.94000')", timeout=8000)
    check("A20 live GPS watch: moving updates the message", "12.94000,77.62000" in text(page, "#preview"), text(page, "#preview"))
    check("A21 no JavaScript errors in run A", not errors, str(errors))
    ctx.close()

    # ===== B. iPhone link style =====
    srv = serve(DIST, 4173)
    ctx = browser.new_context(permissions=["geolocation"], geolocation=GEO, user_agent=IPHONE)
    page = ctx.new_page()
    page.goto("http://localhost:4173/")
    wait_msg(page)
    link = page.locator("#sos").get_attribute("data-link")
    check("B1 iPhone user agent builds the &body= link", link == f"sms:{NUM}&body={ENC}", link)
    check("B2 iPhone sees the Add to Home Screen hint", page.locator("#ios-hint").is_visible())
    ctx.close()

    # ===== C. GPS permission denied =====
    ctx = browser.new_context(permissions=[])
    page = ctx.new_page()
    page.goto("http://localhost:4173/")
    page.wait_for_function("document.getElementById('nogps').hidden === false", timeout=10000)
    check("C1 denied: SOS disabled and the reason is shown", page.locator("#sos").is_disabled() and "permission" in text(page, "#coords").lower(), text(page, "#coords"))
    check("C2 denied: readiness says Not ready with a settings hint", text(page, "#ready").startswith("Not ready") and "settings" in text(page, "#checklist"), text(page, "#ready"))
    page.click("#nogps")
    check("C3 fallback message uses LOC:UNKNOWN", text(page, "#preview") == "FLOOD | TRAPPED | LOC:UNKNOWN", text(page, "#preview"))
    check("C4 fallback enables SOS", page.locator("#sos").is_enabled() and "LOC%3AUNKNOWN" in page.locator("#sos").get_attribute("data-link"))
    ctx.close()

    # ===== D. GPS error paths (mocked GPS chip) =====
    ctx = browser.new_context(permissions=[])
    page = ctx.new_page()
    page.add_init_script(MOCK_GEO)
    page.goto("http://localhost:4173/")
    page.wait_for_function("document.getElementById('coords').textContent.includes('getting GPS')", timeout=8000)
    page.evaluate("__err(2)")
    check("D1 'no GPS signal' shows advice, SOS stays disabled, fallback offered", "No GPS signal" in text(page, "#coords") and page.locator("#sos").is_disabled() and page.locator("#nogps").is_visible(), text(page, "#coords"))
    page.evaluate("__err(3)")
    check("D2 GPS timeout shows 'still looking' advice", "Still looking" in text(page, "#coords"), text(page, "#coords"))
    page.click("#nogps")
    check("D3 fallback chosen while GPS is missing", text(page, "#preview").endswith("LOC:UNKNOWN") and page.locator("#sos").is_enabled())
    page.evaluate("__fix(12.9345, 77.6123, 8)")
    check("D4 a GPS fix arriving later replaces the fallback", text(page, "#preview") == MSG and page.locator("#nogps").is_hidden(), text(page, "#preview"))
    page.evaluate("__err(3)")
    check("D5 a temporary GPS error keeps the last good fix", text(page, "#preview") == MSG and page.locator("#sos").is_enabled())
    page.evaluate("__fix(12.9345, 77.6123, 120)")
    check("D6 poor accuracy (120 m) shows a warning", "low accuracy" in text(page, "#coords"), text(page, "#coords"))
    page.evaluate("__err(1)")
    check("D7 permission revoked clears the fix and disables SOS", page.locator("#sos").is_disabled() and "permission" in text(page, "#coords").lower(), text(page, "#coords"))
    page.click("#locate")
    page.evaluate("__fix(12.9345, 77.6123, 8)")
    check("D8 'Update my location' recovers after an error", text(page, "#preview") == MSG and page.locator("#sos").is_enabled())
    ctx.close()

    # ===== E. Page opened over plain http (not a secure context) =====
    b2 = pw.chromium.launch(args=["--host-resolver-rules=MAP insecure.test 127.0.0.1"])
    ctx = b2.new_context(permissions=["geolocation"], geolocation=GEO)
    page = ctx.new_page()
    page.goto("http://insecure.test:4173/")
    page.wait_for_function("document.getElementById('coords').textContent.length > 0 && !document.getElementById('coords').textContent.includes('getting')", timeout=10000)
    check("E1 plain http: clear 'not HTTPS' message, SOS disabled", "not HTTPS" in text(page, "#coords") and page.locator("#sos").is_disabled(), text(page, "#coords"))
    check("E2 plain http: offline line explains it needs https", "https" in text(page, "#st-cache"), text(page, "#st-cache"))
    check("E3 plain http: readiness is Not ready", text(page, "#ready").startswith("Not ready"), text(page, "#ready"))
    ctx.close()
    b2.close()

    # ===== F. Saved copy wiped (storage cleared or evicted) and recovery =====
    ctx = browser.new_context(permissions=["geolocation"], geolocation=GEO)
    page = ctx.new_page()
    page.goto("http://localhost:4173/")
    wait_ready(page)
    page.evaluate("caches.keys().then(k => Promise.all(k.map(n => caches.delete(n))))")
    stop(srv)                                   # really offline: the server is gone too
    ctx.set_offline(True)
    resp = page.goto("http://localhost:4173/")
    body = page.content()
    check("F1 wiped + offline: help text with 112 instead of a blank page", resp.status == 503 and "112" in body, f"{resp.status}")
    ctx.set_offline(False)
    srv = serve(DIST, 4173)                     # internet is back
    page.goto("http://localhost:4173/")
    rebuilt = poll(lambda: page.evaluate("caches.keys().then(async k => k.length ? (await (await caches.open(k[0])).keys()).length : 0)") > 5)
    check("F2 back online: the saved copy is rebuilt automatically", rebuilt)
    page.wait_for_function("document.getElementById('st-cache').textContent.startsWith('Yes')", timeout=15000)
    check("F3 status line recovers to 'saved' without a manual reload", text(page, "#st-cache").startswith("Yes"), text(page, "#st-cache"))
    ctx.close()

    # ===== G. Install prompt, installed mode, live network changes =====
    ctx = browser.new_context(permissions=["geolocation"], geolocation=GEO)
    page = ctx.new_page()
    page.goto("http://localhost:4173/")
    wait_ready(page)
    page.evaluate("""() => { const e = new Event('beforeinstallprompt'); e.prompt = () => { window.__prompted = true; return Promise.resolve(); }; e.userChoice = Promise.resolve({ outcome: 'accepted' }); window.dispatchEvent(e); }""")
    check("G1 install prompt available: Install button appears", page.locator("#install").is_visible())
    page.click("#install")
    check("G2 Install button uses the browser prompt and hides", page.evaluate("window.__prompted === true") and page.locator("#install").is_hidden())
    ctx.set_offline(True)
    page.wait_for_function("document.getElementById('st-network').textContent.includes('No internet')", timeout=5000)
    ctx.set_offline(False)
    page.wait_for_function("document.getElementById('st-network').textContent === 'Connected'", timeout=5000)
    check("G3 network line updates live when the connection drops and returns", True)
    # Chromium cannot emulate the installed display mode, so make matchMedia answer "standalone".
    standalone = ctx.new_page()
    standalone.add_init_script("""
      const original = window.matchMedia.bind(window);
      window.matchMedia = (q) => q.includes('display-mode: standalone')
        ? { matches: true, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return false; } }
        : original(q);
    """)
    standalone.goto("http://localhost:4173/")
    wait_ready(standalone)
    check("G4 installed (standalone) mode is detected", text(standalone, "#st-app") == "Installed app" and text(standalone, "#checklist li:nth-child(3)").startswith("✓"), text(standalone, "#st-app"))
    ctx.close()
    stop(srv)

    # ===== H. Sub-folder hosting and a host that redirects /index.html =====
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(DIST, tmp / "site" / "resq")
    srv = serve(tmp / "site", 4174, redirect=True)
    ctx = browser.new_context(permissions=["geolocation"], geolocation=GEO)
    page = ctx.new_page()
    page.goto("http://localhost:4174/resq/")
    wait_ready(page)
    scope = page.evaluate("navigator.serviceWorker.getRegistration().then(r => r.scope)")
    check("H1 works in a sub-folder (scope /resq/)", scope == "http://localhost:4174/resq/", scope)
    page.goto("http://localhost:4174/resq/index.html")
    wait_msg(page)
    stop(srv)
    ctx.set_offline(True)
    page.goto("http://localhost:4174/resq/")
    wait_msg(page)
    check("H2 sub-folder app loads offline", text(page, "h1") == "RESQ Emergency SOS" and text(page, "#preview") == MSG, text(page, "#preview"))
    ctx.close()

    # ===== I. A new deployment replaces the old saved copy =====
    v2 = tmp / "dist_v2"
    shutil.copytree(DIST, v2)
    index = (v2 / "index.html").read_text()
    (v2 / "index.html").write_text(index.replace("RESQ Emergency SOS</h1>", "RESQ Emergency SOS v2</h1>"))
    sw = (v2 / "sw.js").read_text()
    (v2 / "sw.js").write_text(re.sub(r'const VERSION = "[0-9a-f]{10}"', 'const VERSION = "00000000v2"', sw))
    srv = serve(DIST, 4175)
    ctx = browser.new_context(permissions=["geolocation"], geolocation=GEO)
    page = ctx.new_page()
    page.goto("http://localhost:4175/")
    wait_ready(page)
    v1 = page.evaluate("caches.keys()")[0]
    stop(srv)
    srv = serve(v2, 4175)
    page.reload()
    keys = poll(lambda: (lambda k: k if len(k) == 1 and k[0] != v1 else None)(page.evaluate("caches.keys()")), tries=40)
    check("I1 update: old cache deleted, one new cache", bool(keys), f"{v1} -> {page.evaluate('caches.keys()')}")
    page.reload()
    page.wait_for_selector("h1")
    check("I2 update: the next reload shows the new version", text(page, "h1").endswith("v2"), text(page, "h1"))
    ctx.close()
    stop(srv)
    shutil.rmtree(tmp, ignore_errors=True)
    browser.close()

fails = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} checks passed")
if fails:
    print("FAILED: " + "; ".join(fails))
sys.exit(1 if fails else 0)
