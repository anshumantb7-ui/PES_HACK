// Usage: npm run check:live -- https://your-site.vercel.app [+91XXXXXXXXXX]
// Tests a DEPLOYED copy of the app the way a phone's browser will load it.
const [, , rawUrl, numberArg] = process.argv;
if (!rawUrl) {
  console.error("Usage: npm run check:live -- https://your-site.example [gateway number]");
  process.exit(1);
}
const base = new URL(rawUrl.endsWith("/") ? rawUrl : rawUrl + "/");
const local = ["localhost", "127.0.0.1"].includes(base.hostname);
const problems = [];
const warnings = [];
const fail = (m) => problems.push(m);
const warn = (m) => warnings.push(m);
const ok = (m) => console.log("  ok   " + m);

async function get(url, init) {
  try {
    return await fetch(url, { redirect: "follow", ...init });
  } catch (e) {
    fail(`${url} could not be reached (${e.cause?.code ?? e.message})`);
    return null;
  }
}

if (base.protocol !== "https:" && !local) fail("the site is not https:// (GPS and the service worker will not work)");

const home = await get(base);
if (!home) finish();
if (home.status !== 200) fail(`home page returned ${home.status}`);
const html = await home.text();
if (!html.includes('rel="manifest"')) fail("home page has no manifest link");
if (html.includes('id="dev"')) fail("the dev panel is in the deployed page");
if (/(?:src|href)="\/(?!\/)/.test(html)) fail("page uses root-absolute URLs (breaks in a sub-folder)");
ok("home page loads");

// every asset the page references
const refs = [...html.matchAll(/(?:src|href)="(\.\/[^"]+)"/g)].map((m) => new URL(m[1], base).href);
for (const url of refs) {
  const r = await get(url);
  if (r && r.status !== 200) fail(`${url} returned ${r.status}`);
}
ok(`${refs.length} files referenced by the page are reachable`);

// service worker file + caching headers
const swUrl = new URL("sw.js", base).href;
const sw = await get(swUrl);
let precache = [];
if (sw) {
  if (sw.status !== 200) fail(`sw.js returned ${sw.status}`);
  const type = sw.headers.get("content-type") ?? "";
  if (!/javascript/.test(type)) fail(`sw.js content-type is "${type}", expected JavaScript`);
  const cc = (sw.headers.get("cache-control") ?? "").toLowerCase();
  if (!cc) warn("sw.js has no Cache-Control header; updates may reach phones up to 24 h late");
  else if (!/no-cache|no-store|max-age=0/.test(cc)) fail(`sw.js Cache-Control is "${cc}"; it must be no-cache so updates reach phones`);
  else ok(`sw.js Cache-Control: ${cc}`);
  const text = await sw.text();
  const version = /const VERSION = "([0-9a-f]{10})"/.exec(text)?.[1];
  if (!version) fail("sw.js has no version hash (was it built with npm run build?)");
  else ok(`service worker version ${version}`);
  try {
    precache = JSON.parse(/const PRECACHE = (\[[\s\S]*?\]);/.exec(text)[1]);
  } catch {
    fail("could not read the cache list from sw.js");
  }
}

// every file the worker will save must exist, otherwise install fails on phones
let missing = 0;
for (const entry of precache) {
  const r = await get(new URL(entry, new URL("sw.js", base)).href);
  if (r && r.status !== 200) {
    fail(`cache list file ${entry} returned ${r.status}`);
    missing++;
  }
}
if (precache.length && !missing) ok(`all ${precache.length} files in the offline cache list are reachable`);

// manifest + icons
const mUrl = new URL("manifest.webmanifest", base);
const m = await get(mUrl.href);
if (m && m.status === 200) {
  try {
    const manifest = await m.json();
    for (const icon of manifest.icons ?? []) {
      const r = await get(new URL(icon.src, mUrl).href);
      if (r && r.status !== 200) fail(`manifest icon ${icon.src} returned ${r.status}`);
    }
    if (manifest.display !== "standalone") fail("manifest display is not standalone");
    ok("manifest and icons are reachable");
  } catch {
    fail("manifest.webmanifest is not valid JSON");
  }
} else if (m) fail(`manifest returned ${m.status}`);

// the gateway number baked into the app
const jsRef = refs.find((u) => u.endsWith(".js") && u.includes("/assets/"));
if (jsRef) {
  const js = await (await get(jsRef))?.text();
  const found = [...new Set((js ?? "").match(/["'`]\+?[0-9]{8,15}["'`]/g) ?? [])].map((s) => s.slice(1, -1));
  const expected = (numberArg ?? process.env.VITE_GATEWAY_NUMBER ?? "").trim();
  if (!found.length) fail("no phone number found inside the app");
  else if (expected && !found.includes(expected)) fail(`the app contains ${found.join(", ")} but you expected ${expected}`);
  else ok(`gateway number in the app: ${found.join(", ")}${expected ? " (matches)" : " (pass it as the 2nd argument to compare)"}`);
}

finish();

function finish() {
  for (const w of warnings) console.log("  warn " + w);
  if (problems.length) {
    console.error("\nLIVE CHECK FAILED:\n - " + problems.join("\n - "));
    process.exit(1);
  }
  console.log(`\nLive check passed for ${base.href}`);
  process.exit(0);
}
