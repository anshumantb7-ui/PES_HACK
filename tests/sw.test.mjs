// Runs the real sw-template.js inside a Node sandbox with a fake Cache API,
// so the install / activate / fetch logic is tested without a browser.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const TEMPLATE = readFileSync(new URL("../sw-template.js", import.meta.url), "utf8");
const SCOPE = "https://resq.example/";
const PRECACHE = ["./", "./assets/app.js", "./assets/app.css", "./manifest.webmanifest"];

function makeWorker({ version = "v1", server, precache = PRECACHE, existingCaches = {} } = {}) {
  const stores = new Map(Object.entries(existingCaches).map(([n, m]) => [n, new Map(Object.entries(m))]));
  const listeners = {};
  let online = true;
  let skipWaiting = false;
  let claimed = false;

  const fakeFetch = async (input) => {
    if (!online) throw new TypeError("Failed to fetch");
    const url = typeof input === "string" ? input : input.url;
    const hit = server[url];
    if (!hit) return new Response("not found", { status: 404 });
    return hit instanceof Response ? hit.clone() : new Response(hit);
  };

  const keyOf = (req, ignoreSearch) => {
    const u = new URL(typeof req === "string" ? req : req.url);
    if (ignoreSearch) u.search = "";
    return u.href;
  };

  const makeCache = (map) => ({
    async addAll(requests) {
      const responses = [];
      for (const r of requests) {
        const res = await fakeFetch(r);
        if (!res.ok) throw new TypeError(`addAll failed for ${r.url}: ${res.status}`);
        responses.push([r.url, res]);
      }
      for (const [url, res] of responses) map.set(url, res);
    },
    async match(req, opts = {}) {
      const want = keyOf(req, opts.ignoreSearch);
      for (const [url, res] of map) {
        if (keyOf(url, opts.ignoreSearch) === want) return res.clone();
      }
      return undefined;
    },
  });

  const sandbox = {
    URL, Request, Response, console,
    caches: {
      async open(name) {
        if (!stores.has(name)) stores.set(name, new Map());
        return makeCache(stores.get(name));
      },
      async keys() { return [...stores.keys()]; },
      async delete(name) { return stores.delete(name); },
    },
    fetch: fakeFetch,
  };
  sandbox.self = {
    registration: { scope: SCOPE },
    location: { origin: new URL(SCOPE).origin },
    clients: { async claim() { claimed = true; } },
    skipWaiting: async () => { skipWaiting = true; },
    addEventListener: (type, fn) => { listeners[type] = fn; },
  };
  const code = TEMPLATE.replace("__VERSION__", () => version).replace("__PRECACHE__", () => JSON.stringify(precache));
  vm.runInNewContext(code, sandbox);

  const dispatchLifecycle = async (type) => {
    let pending;
    listeners[type]({ waitUntil: (p) => { pending = p; } });
    await pending;
  };
  const dispatchFetch = async (request) => {
    let responded;
    let called = false;
    const pending = [];
    listeners.fetch({
      request,
      respondWith: (p) => { called = true; responded = p; },
      waitUntil: (p) => { pending.push(p); },
    });
    const result = called ? await responded : null;
    await Promise.all(pending);
    return result;
  };

  return {
    install: () => dispatchLifecycle("install"),
    activate: () => dispatchLifecycle("activate"),
    fetch: dispatchFetch,
    cacheNames: () => [...stores.keys()],
    wipeAllCaches: () => stores.clear(),
    cacheUrls: (name) => [...(stores.get(name)?.keys() ?? [])],
    setOnline: (v) => { online = v; },
    flags: () => ({ skipWaiting, claimed }),
  };
}

const goodServer = () => ({
  [SCOPE]: new Response("<html>INDEX</html>", { headers: { "Content-Type": "text/html" } }),
  [`${SCOPE}assets/app.js`]: "console.log(1)",
  [`${SCOPE}assets/app.css`]: "body{}",
  [`${SCOPE}manifest.webmanifest`]: "{}",
});

const navigate = (url) => {
  const r = new Request(url);
  Object.defineProperty(r, "mode", { value: "navigate" });
  return r;
};

describe("service worker", () => {
  it("install caches every file under a versioned name and activates immediately", async () => {
    const w = makeWorker({ version: "abc123", server: goodServer() });
    await w.install();
    expect(w.cacheNames()).toEqual(["resq-sos-abc123"]);
    expect(w.cacheUrls("resq-sos-abc123").sort()).toEqual(
      [SCOPE, `${SCOPE}assets/app.js`, `${SCOPE}assets/app.css`, `${SCOPE}manifest.webmanifest`].sort(),
    );
    expect(w.flags().skipWaiting).toBe(true);
  });

  it("install fails (keeping the old worker) if any file is missing", async () => {
    const server = goodServer();
    delete server[`${SCOPE}assets/app.js`];
    const w = makeWorker({ server });
    await expect(w.install()).rejects.toThrow();
  });

  it("activate deletes old resq caches only, then claims clients", async () => {
    const w = makeWorker({
      version: "new",
      server: goodServer(),
      existingCaches: { "resq-sos-old": {}, "other-app-cache": {}, "resq-sos-new": {} },
    });
    await w.activate();
    expect(w.cacheNames().sort()).toEqual(["other-app-cache", "resq-sos-new"]);
    expect(w.flags().claimed).toBe(true);
  });

  it("serves files from the cache when offline", async () => {
    const w = makeWorker({ server: goodServer() });
    await w.install();
    w.setOnline(false);
    const js = await w.fetch(new Request(`${SCOPE}assets/app.js`));
    expect(await js.text()).toBe("console.log(1)");
    const css = await w.fetch(new Request(`${SCOPE}assets/app.css`));
    expect(await css.text()).toBe("body{}");
  });

  it("serves the saved page for any navigation when offline, including query strings", async () => {
    const w = makeWorker({ server: goodServer() });
    await w.install();
    w.setOnline(false);
    for (const url of [SCOPE, `${SCOPE}?source=pwa`, `${SCOPE}index.html`, `${SCOPE}anything/else`]) {
      const res = await w.fetch(navigate(url));
      expect(await res.text()).toContain("INDEX");
    }
  });

  it("strips the redirected flag so a cached page can answer a navigation", async () => {
    const redirected = new Response("<html>INDEX</html>");
    Object.defineProperty(redirected, "redirected", { value: true });
    const server = { ...goodServer(), [SCOPE]: redirected };
    const w = makeWorker({ server });
    await w.install();
    const res = await w.fetch(navigate(SCOPE));
    expect(res.redirected).toBe(false);
    expect(await res.text()).toContain("INDEX");
  });

  it("returns a clear 503 when offline and the file was never cached", async () => {
    const w = makeWorker({ server: goodServer() });
    await w.install();
    w.setOnline(false);
    const res = await w.fetch(new Request(`${SCOPE}assets/never-saved.js`));
    expect(res.status).toBe(503);
  });

  it("rebuilds a wiped cache on the next online page load", async () => {
    const w = makeWorker({ version: "abc123", server: goodServer() });
    await w.install();
    w.wipeAllCaches();                                 // storage cleared / evicted
    const res = await w.fetch(navigate(SCOPE));          // online: served from the network
    expect(await res.text()).toContain("INDEX");
    expect(w.cacheUrls("resq-sos-abc123").length).toBe(PRECACHE.length);
    w.setOnline(false);                                // and now it works offline again
    const offline = await w.fetch(navigate(SCOPE));
    expect(await offline.text()).toContain("INDEX");
  });

  it("when wiped AND offline, answers with help text instead of a blank page", async () => {
    const w = makeWorker({ server: goodServer() });
    await w.install();
    w.wipeAllCaches();
    w.setOnline(false);
    const res = await w.fetch(navigate(SCOPE));
    expect(res.status).toBe(503);
    expect(await res.text()).toContain("112");
  });

  it("does not touch POST requests or other origins", async () => {
    const w = makeWorker({ server: goodServer() });
    await w.install();
    expect(await w.fetch(new Request(`${SCOPE}sms`, { method: "POST", body: "x" }))).toBeNull();
    expect(await w.fetch(new Request("https://elsewhere.example/x.js"))).toBeNull();
  });
});
