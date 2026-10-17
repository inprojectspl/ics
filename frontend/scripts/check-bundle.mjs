// Bundle budget for `npm run build` output. Run after a build; exits 1 when
// the production bundle regresses past the limits below.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// Lazy chunks (PDF.js, the document-graph views, the notification screens,
// the graph explorer) count here although no page loads them eagerly.
const MAX_JS_FILES = 176;
const MAX_DIST_BYTES = 10 * 1024 * 1024;
const assets = new URL("../dist/assets/", import.meta.url).pathname;

const files = readdirSync(assets);
const js = files.filter((f) => f.endsWith(".js"));
const total = files.reduce((sum, f) => sum + statSync(join(assets, f)).size, 0);
const problems = [];

if (js.length > MAX_JS_FILES) problems.push(`${js.length} JS files (max ${MAX_JS_FILES})`);
if (total > MAX_DIST_BYTES) {
  problems.push(`${(total / 1048576).toFixed(1)} MiB of assets (max ${MAX_DIST_BYTES / 1048576})`);
}
// The Oniguruma engine means the full shiki bundle is back.
for (const f of files.filter((f) => /^wasm|\.wasm$/.test(f))) problems.push(`wasm asset ${f}`);
// React must live in its own chunk, not inside another vendor group.
for (const f of js.filter((f) => f.startsWith("vendor-react-"))) {
  const head = readFileSync(join(assets, f), "utf8").slice(0, 2000);
  for (const m of head.matchAll(/from"\.\/(vendor-[a-z]+)-/g)) {
    problems.push(`${f} imports from ${m[1]}`);
  }
}

if (problems.length) {
  console.error(`Bundle budget exceeded:\n- ${problems.join("\n- ")}`);
  process.exit(1);
}
console.log(`Bundle OK: ${js.length} JS files, ${(total / 1048576).toFixed(1)} MiB`);
