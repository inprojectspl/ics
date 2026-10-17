import { defineConfig, transformWithOxc } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import type { Plugin } from "vite";
import { readdir, readFile } from "node:fs/promises";


// KaTeX lists every font as woff2, woff and ttf. Every supported browser takes
// woff2, so the other two only add about a megabyte of never-fetched assets.
function katexWoff2Only(): Plugin {
  return {
    name: "katex-woff2-only",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("katex/dist/katex") || !id.endsWith(".css")) return;
      return code.replace(/,url\([^)]+\.(?:woff|ttf)\) format\("(?:woff|truetype)"\)/g, "");
    },
  };
}

// pdf.js reads decoders (JBIG2, JPEG 2000, colour profiles), CMaps and the
// standard fonts from directories at run time (`wasmUrl`, `cMapUrl`, ...).
// They are served from `/pdfjs/<version>/` in dev and emitted there by the
// build: outside `assets/`, whole directories, the version keeping caches honest.
const PDFJS_DIRS = ["wasm", "cmaps", "standard_fonts", "iccs"];
const PDFJS_TYPES: Record<string, string> = {
  wasm: "application/wasm",
  js: "text/javascript",
};

function pdfjsAssets(): Plugin {
  // Vite runs from the frontend directory, in compose and locally.
  const root = `${process.cwd()}/node_modules/pdfjs-dist`;
  const version = readFile(`${root}/package.json`, "utf8").then((raw) => String(JSON.parse(raw).version));
  return {
    name: "pdfjs-assets",
    async configureServer(server) {
      const base = `/pdfjs/${await version}/`;
      server.middlewares.use(async (req, res, next) => {
        const path = req.url?.split("?")[0] ?? "";
        const [dir, file, ...rest] = path.startsWith(base) ? path.slice(base.length).split("/") : [];
        if (!dir || !file || rest.length || !PDFJS_DIRS.includes(dir) || file.includes("..")) {
          next();
          return;
        }
        try {
          const body = await readFile(`${root}/${dir}/${file}`);
          res.setHeader("Content-Type", PDFJS_TYPES[file.split(".").pop() ?? ""] ?? "application/octet-stream");
          res.end(body);
        } catch {
          next();
        }
      });
    },
    async generateBundle() {
      const base = `pdfjs/${await version}`;
      for (const dir of PDFJS_DIRS) {
        for (const file of await readdir(`${root}/${dir}`)) {
          if (file.startsWith("LICENSE") || file.startsWith("quickjs")) continue;
          const source = await readFile(`${root}/${dir}/${file}`);
          this.emitFile({ type: "asset", fileName: `${base}/${dir}/${file}`, source });
        }
      }
    },
  };
}

// The Web Push service worker (ADR-0023) must sit at the site root under a
// fixed name: `/sw.js` scopes it to the whole app, and a hashed name would
// change the worker on every release. `src/sw.ts` is a plain script without
// imports, so stripping the types is the whole build; it is emitted beside
// index.html (not in `assets/`) and served by the dev server at the same URL.
function serviceWorker(): Plugin {
  const source = `${process.cwd()}/src/sw.ts`;
  const compile = async () => {
    const result = await transformWithOxc(await readFile(source, "utf8"), source, { lang: "ts" });
    return result.code;
  };
  return {
    name: "ics-service-worker",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.url?.split("?")[0] !== "/sw.js") {
          next();
          return;
        }
        try {
          res.setHeader("Content-Type", "text/javascript");
          res.setHeader("Cache-Control", "no-cache");
          res.end(await compile());
        } catch (err) {
          next(err);
        }
      });
    },
    async generateBundle() {
      this.emitFile({ type: "asset", fileName: "sw.js", source: await compile() });
    },
  };
}

// Outside compose (e2e in CI, local runs) the backend is not "backend".
const API_TARGET = process.env.ICS_API_PROXY_TARGET ?? "http://backend:8000";
const VIEWER_PREFIX = "/__html-viewer";

/**
 * Dev stand-in for the proxy rule that serves HTML bundles from their own
 * origin (the `html-ics` block in docs/deploy/nginx.example.conf): every
 * request on an `html.*` host goes to the backend as `/html{path}`. The app
 * host never reaches that path, so bundle code cannot run on its origin.
 */
function htmlViewerHost(): Plugin {
  return {
    name: "ics-html-viewer-host",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if ((req.headers.host ?? "").startsWith("html.")) {
          req.url = `${VIEWER_PREFIX}${req.url ?? "/"}`;
        } else if (req.url?.startsWith(VIEWER_PREFIX)) {
          res.statusCode = 404;
          res.end();
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), katexWoff2Only(), pdfjsAssets(), serviceWorker(), htmlViewerHost()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      [VIEWER_PREFIX]: { target: API_TARGET, rewrite: (path) => `/html${path.slice(VIEWER_PREFIX.length)}` },
    },
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
  build: {
    // Vite warns on chunks >500KB by default. Rollup splits dynamic imports
    // into separate chunks (mermaid, shiki per language); those
    // can exceed 500KB but load on demand (e.g. only for markdown with a
    // `cpp` block) and never reach the initial paint. The 1MB limit silences
    // warnings for these legitimate on-demand bundles.
    chunkSizeWarningLimit: 1024,
    rolldownOptions: {
      output: {
        // Split core framework deps into stable chunks so the browser caches
        // them across releases (a change in our code does not invalidate React
        // or TanStack). Do not add groups for mermaid/shiki: they are
        // loaded via dynamic import and already get their own chunks; a group
        // would glue them back into one huge vendor chunk.
        //
        // A group also captures the dependencies of its modules, so React must
        // be claimed first (highest priority), otherwise it lands in whichever
        // group pulled it in, e.g. lucide-react.
        codeSplitting: {
          groups: [
            {
              name: "vendor-react",
              test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/,
              priority: 40,
            },
            { name: "vendor-tanstack", test: /node_modules[\\/]@tanstack[\\/]/, priority: 30 },
            { name: "vendor-lucide", test: /node_modules[\\/]lucide-react[\\/]/, priority: 20 },
            {
              name: "vendor-markdown",
              test: /node_modules[\\/](markdown-it|rehype-[^/\\]+|remark-[^/\\]+)[\\/]/,
              priority: 10,
            },
          ],
        },
      },
    },
  },
});
