import { defineConfig, loadEnv, type Plugin } from "vite";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { basename, join, relative, sep } from "node:path";

const TUNNEL_HOSTS = [".trycloudflare.com", ".ngrok-free.app", ".ngrok-free.dev", ".loca.lt"];
const GATEWAY_PATTERN = /^\+?[0-9]{5,15}$/;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

/**
 * Build-only plugin:
 *  1. refuses to build without a valid gateway number (a wrong number would be
 *     cached on victims' phones),
 *  2. removes the dev panel from index.html,
 *  3. writes dist/sw.js from sw-template.js with a content-hash version and the
 *     full list of files to cache.
 */
function resqBuild(): Plugin {
  let root = process.cwd();
  let outDir = join(root, "dist");

  return {
    name: "resq-build",
    apply: "build",
    enforce: "post",

    configResolved(config) {
      root = config.root;
      outDir = join(config.root, config.build.outDir);
      const env = loadEnv(config.mode, config.root, "VITE_");
      const number = (env.VITE_GATEWAY_NUMBER ?? "").trim();
      if (!GATEWAY_PATTERN.test(number)) {
        throw new Error(
          "VITE_GATEWAY_NUMBER is missing or invalid. Put it in .env.local (local build) " +
            "or in the host's environment variables (Vercel/Netlify), digits with an optional leading +.",
        );
      }
    },

    transformIndexHtml(html) {
      return html.replace(/<!-- dev:start -->[\s\S]*?<!-- dev:end -->/g, "");
    },

    closeBundle() {
      if (!existsSync(outDir)) return;
      const files = walk(outDir)
        .map((full) => relative(outDir, full).split(sep).join("/"))
        .filter(
          (file) =>
            file !== "sw.js" &&
            file !== "index.html" && // cached as "./" so hosts that redirect /index.html cannot break it
            !file.endsWith(".map") &&
            !basename(file).startsWith("_"), // host config such as _headers
        )
        .sort();

      const hash = createHash("sha256");
      for (const file of files) {
        hash.update(file);
        hash.update(readFileSync(join(outDir, file)));
      }
      hash.update(readFileSync(join(outDir, "index.html")));
      const version = hash.digest("hex").slice(0, 10);

      const urls = ["./", ...files.map((file) => `./${file}`)];
      const template = readFileSync(join(root, "sw-template.js"), "utf8");
      if (!template.includes("__VERSION__") || !template.includes("__PRECACHE__")) {
        throw new Error("sw-template.js is missing the __VERSION__ or __PRECACHE__ placeholder.");
      }
      const sw = template
        .replace("__VERSION__", () => version)
        .replace("__PRECACHE__", () => JSON.stringify(urls, null, 2));
      writeFileSync(join(outDir, "sw.js"), sw);
      console.log(`resq: sw.js written, version ${version}, ${urls.length} files cached`);
    },
  };
}

export default defineConfig({
  base: "./", // relative URLs so the app works at a domain root or in a sub-folder
  plugins: [resqBuild()],
  // Vite blocks unknown Host headers; allow common HTTPS tunnel domains for
  // both `npm run dev` (server) and `npm run preview` (preview).
  server: { host: true, allowedHosts: TUNNEL_HOSTS },
  preview: { host: true, allowedHosts: TUNNEL_HOSTS },
});
