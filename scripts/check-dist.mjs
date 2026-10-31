// Run after `npm run build`. Fails loudly if the build output cannot work offline.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const dist = new URL("../dist/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const problems = [];
const fail = (msg) => problems.push(msg);

const walk = (dir) =>
  readdirSync(dir).flatMap((n) => {
    const f = join(dir, n);
    return statSync(f).isDirectory() ? walk(f) : [f];
  });

if (!existsSync(dist)) {
  console.error("dist/ not found. Run npm run build first.");
  process.exit(1);
}

const html = readFileSync(join(dist, "index.html"), "utf8");
const swPath = join(dist, "sw.js");
if (!existsSync(swPath)) fail("dist/sw.js is missing");
const sw = existsSync(swPath) ? readFileSync(swPath, "utf8") : "";

// 1. placeholders replaced, version present, list parsed
if (sw.includes("__VERSION__") || sw.includes("__PRECACHE__")) fail("sw.js still contains template placeholders");
const version = /const VERSION = "([0-9a-f]{10})"/.exec(sw)?.[1];
if (!version) fail("sw.js has no 10-character version hash");
let precache = [];
try {
  const m = /const PRECACHE = (\[[\s\S]*?\]);/.exec(sw);
  precache = JSON.parse(m[1]);
} catch {
  fail("could not read the PRECACHE list from sw.js");
}

// 2. every file the page needs is cached
const refs = [...html.matchAll(/(?:src|href)="(\.\/[^"]+)"/g)].map((m) => m[1]);
for (const ref of refs) {
  if (!existsSync(join(dist, ref))) fail(`index.html references ${ref} but the file is not in dist/`);
  if (!precache.includes(ref)) fail(`index.html references ${ref} but it is not in the precache list`);
}
if (!precache.includes("./")) fail('precache list must include "./"');
for (const entry of precache) {
  if (entry !== "./" && !existsSync(join(dist, entry))) fail(`precache lists ${entry} but it does not exist`);
}
if (precache.some((e) => e.endsWith("index.html") || e.endsWith(".map") || e.includes("/_")))
  fail("precache list contains index.html, a source map, or a host config file");

// 3. dev panel and absolute URLs removed
if (html.includes('id="dev"') || html.includes("dev:start")) fail("dev panel is still in the production index.html");
if (/(?:src|href)="\/(?!\/)/.test(html)) fail("index.html has root-absolute URLs; the app would break in a sub-folder");

// 4. manifest + icons
const manifestPath = join(dist, "manifest.webmanifest");
if (!existsSync(manifestPath)) fail("manifest.webmanifest missing");
else {
  const m = JSON.parse(readFileSync(manifestPath, "utf8"));
  for (const key of ["name", "short_name", "start_url", "display", "icons"]) if (!m[key]) fail(`manifest missing ${key}`);
  if (m.display !== "standalone") fail("manifest display should be standalone");
  const sizes = new Map();
  for (const icon of m.icons ?? []) {
    const file = join(dist, icon.src);
    if (!existsSync(file)) { fail(`manifest icon ${icon.src} missing`); continue; }
    const buf = readFileSync(file);
    const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20); // PNG IHDR
    if (`${w}x${h}` !== icon.sizes) fail(`${icon.src} is ${w}x${h}, manifest says ${icon.sizes}`);
    sizes.set(`${icon.sizes}/${icon.purpose}`, true);
  }
  for (const need of ["192x192/any", "512x512/any", "512x512/maskable"]) if (!sizes.has(need)) fail(`manifest needs a ${need} icon`);
}

// 5. the gateway number is baked into the bundle (and is the one you expect)
const js = walk(join(dist, "assets")).filter((f) => f.endsWith(".js")).map((f) => readFileSync(f, "utf8")).join("\n");
let expected = process.env.VITE_GATEWAY_NUMBER?.trim();
const envFile = new URL("../.env.local", import.meta.url);
if (!expected && existsSync(envFile)) {
  expected = /^VITE_GATEWAY_NUMBER=(.*)$/m.exec(readFileSync(envFile, "utf8"))?.[1]?.trim();
}
if (!expected) fail("no VITE_GATEWAY_NUMBER found in the environment or .env.local to compare with");
else if (!js.includes(expected)) fail(`the built JavaScript does not contain the gateway number ${expected}`);
else console.log(`Gateway number in bundle: ${expected}`);

if (problems.length) {
  console.error("\nBUILD CHECK FAILED:\n - " + problems.join("\n - "));
  process.exit(1);
}
console.log(`Build check passed: version ${version}, ${precache.length} files cached, ${relative(process.cwd(), dist) || "dist"}${sep}`);
