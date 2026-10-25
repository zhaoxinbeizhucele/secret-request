/** Local Miniflare fixture shared by Vitest and Python integration tests. */
import { build } from "esbuild";
import { Miniflare, Log, LogLevel } from "miniflare";
import { fileURLToPath } from "node:url";
export async function fixture({ port = 0, persist = false, base = "https://relay.example" } = {}) {
  const result = await build({ entryPoints: ["worker/tests/harness.ts"], bundle: true, write: false, format: "esm", platform: "neutral", target: "es2022", external: ["cloudflare:workers"], loader: { ".html": "text", ".css": "text", ".js": "text" } });
  const mf = new Miniflare({ modules: true, script: result.outputFiles[0].text, compatibilityDate: "2026-07-30", host: "127.0.0.1", port,
    bindings: { BASE_URL: base }, durableObjects: { RELAY: { className: "TestRelay", useSQLite: true } }, durableObjectsPersist: persist, log: new Log(LogLevel.ERROR), cf: false });
  await mf.ready;
  return mf;
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.argv[2]);
  const mf = await fixture({ port, base: `http://127.0.0.1:${port}` });
  process.stdout.write("ready\n");
  process.stdin.resume();
  process.stdin.on("end", async () => { await mf.dispose(); process.exit(0); });
}
