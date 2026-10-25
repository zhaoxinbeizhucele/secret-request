import { beforeEach, afterAll, beforeAll, test, expect } from "vitest";
import { fixture } from "../../scripts/worker_fixture.mjs";
import { createBody, decode, validEnvelope, validJwk } from "../schema";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Miniflare } from "miniflare";
let mf: Miniflare;
const n = Buffer.alloc(384, 200).toString("base64url");
const jwk = { kty: "RSA", e: "AQAB", n };
const envelope = { v: 1, wrapped_key: Buffer.alloc(384, 1).toString("base64url"), nonce: Buffer.alloc(12, 2).toString("base64url"), ciphertext: Buffer.alloc(32, 3).toString("base64url") };
async function req(path: string, method = "GET", data?: unknown, bearer?: string, ip = "192.0.2.1") {
  return mf.dispatchFetch("https://relay.example" + path, { method, headers: { "Content-Type": "application/json", "CF-Connecting-IP": ip, ...(bearer ? { Authorization: "Bearer " + bearer } : {}) }, body: data === undefined ? undefined : JSON.stringify(data) });
}
async function control(action: string, data = {}) { return (await req("/__test/" + action, "POST", data)).json() as Promise<any>; }
async function sql(query: string, ...args: (string|number)[]) { return control("sql", { query, args }); }
async function create(ip = "192.0.2.1", ttl = 600) {
  const response = await req("/api/requests", "POST", { name: "Synthetic", purpose: "Test", public_key: jwk, ttl_seconds: ttl }, undefined, ip);
  expect(response.status).toBe(201);
  const c = await response.json() as any; c.submit = c.input_url.split("#")[1]; return c;
}
beforeAll(async () => { mf = await fixture(); });
beforeEach(async () => { await control("reset"); });
afterAll(async () => { await mf.dispose(); });

test("normal flow, protocol lengths and storage holds only hashes", async () => {
  const c = await create(); expect(c.submit).toMatch(/^[A-Za-z0-9_-]{22}$/); expect(c.receive_token).toHaveLength(43);
  const dump = await control("inspect"); const text = JSON.stringify(dump);
  expect(text.includes(c.submit)).toBe(false); expect(text.includes(c.receive_token)).toBe(false); expect(text.includes("192.0.2.1")).toBe(false);
  const details = await (await req("/api/input", "GET", undefined, c.submit)).json() as any;
  expect(details.public_key).toEqual(jwk); expect(details.state).toBe("pending");
  expect((await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit)).status).toBe(200);
  const taken = await req(`/api/requests/${c.id}/consume`, "POST", {}, c.receive_token); expect((await taken.json() as any).envelope).toEqual(envelope);
  expect((await req(`/api/requests/${c.id}/consume`, "POST", {}, c.receive_token)).status).toBe(409);
  expect((await control("inspect")).rows[0].envelope).toBeNull();
});
test("capability roles are separate and cannot cross requests", async () => {
  const a = await create(), b = await create();
  for (const action of ["status", "consume", "cancel"]) expect((await req(`/api/requests/${a.id}/${action}`, action === "status" ? "GET" : "POST", action === "status" ? undefined : {}, a.submit)).status).toBe(404);
  for (const action of ["details", "submit", "decline"]) expect((await req(`/api/requests/${a.id}${action === "details" ? "" : "/" + action}`, action === "details" ? "GET" : "POST", action === "details" ? undefined : envelope, a.receive_token)).status).toBe(404);
  expect((await req(`/api/requests/${b.id}/status`, "GET", undefined, a.receive_token)).status).toBe(404);
  expect((await req("/api/input", "GET", undefined, a.receive_token)).status).toBe(404);
});
test("parallel submit commits once", async () => {
  const c = await create(); const results = await Promise.all(Array.from({length: 12}, () => req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit)));
  expect(results.filter(r => r.status === 200)).toHaveLength(1); expect(results.filter(r => r.status === 409)).toHaveLength(11);
});
test("parallel consume commits once even when its response is discarded", async () => {
  const c = await create(); await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit);
  const results = await Promise.all(Array.from({length: 12}, () => req(`/api/requests/${c.id}/consume`, "POST", {}, c.receive_token)));
  expect(results.filter(r => r.status === 200)).toHaveLength(1); expect(results.filter(r => r.status === 409)).toHaveLength(11);
  expect((await control("inspect")).rows[0].envelope).toBeNull();
});
test("submit/cancel and consume/cancel races never restore ciphertext", async () => {
  for (let i = 0; i < 4; i++) {
    const c = await create();
    await Promise.all([req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit), req(`/api/requests/${c.id}/cancel`, "POST", {}, c.receive_token)]);
    expect((await (await req(`/api/requests/${c.id}/status`, "GET", undefined, c.receive_token)).json() as any).state).toBe("cancelled");
  }
  await control("reset"); const c = await create(); await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit);
  const result = await Promise.all([req(`/api/requests/${c.id}/consume`, "POST", {}, c.receive_token), req(`/api/requests/${c.id}/cancel`, "POST", {}, c.receive_token)]);
  expect(result.filter(r => r.status === 200)).toHaveLength(1); expect((await control("inspect")).rows[0].envelope).toBeNull();
});
test("decline terminal state and cancel clear ciphertext", async () => {
  const c = await create(); expect((await req(`/api/requests/${c.id}/decline`, "POST", {}, c.submit)).status).toBe(200);
  expect((await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit)).status).toBe(409);
  const b = await create(); await req(`/api/requests/${b.id}/submit`, "POST", envelope, b.submit); await req(`/api/requests/${b.id}/cancel`, "POST", {}, b.receive_token);
  expect((await control("inspect")).rows.every((r: any) => r.envelope === null)).toBe(true);
});
test("request-time expiry and alarm physically clear envelope, rows, indexes, rates", async () => {
  const c = await create(); await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit);
  await sql("UPDATE requests SET deadline=? WHERE id=?", Date.now()-100, c.id);
  expect((await req(`/api/requests/${c.id}/consume`, "POST", {}, c.receive_token)).status).toBe(409);
  let dump = await control("inspect"); expect(dump.rows[0].state).toBe("expired"); expect(dump.rows[0].envelope).toBeNull();
  await control("reset"); const b = await create(); await req(`/api/requests/${b.id}/submit`, "POST", envelope, b.submit);
  await sql("UPDATE requests SET deadline=?", Date.now()-100); await control("alarm");
  dump = await control("inspect"); expect(dump.rows[0].state).toBe("expired"); expect(dump.rows[0].envelope).toBeNull();
  await sql("UPDATE requests SET terminal_at=?", Date.now()-60001); await sql("UPDATE rates SET at=?", Date.now()-60001); await control("alarm");
  dump = await control("inspect"); expect(dump.rows).toHaveLength(0); expect(dump.rates).toHaveLength(0); expect(dump.alarm).toBeNull();
  expect((await req("/api/input", "GET", undefined, b.submit)).status).toBe(404);
});
test("scheduled alarm runs without incoming API traffic", async () => {
  const c = await create("192.0.2.1", 10);
  await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit);
  const scheduled = await control("inspect");
  expect(scheduled.alarm).toBeGreaterThan(Date.now());
  await new Promise(resolve => setTimeout(resolve, 10500));
  const dump = await control("inspect");
  expect(dump.rows[0].state).toBe("expired");
  expect(dump.rows[0].envelope).toBeNull();
  expect(dump.alarm).toBeGreaterThan(Date.now());
});
test("per-IP active requests limit and spoofed XFF/internal source ignored", async () => {
  for (let i=0;i<8;i++) await create();
  const r = await mf.dispatchFetch("https://relay.example/api/requests", { method: "POST", headers: {"Content-Type":"application/json", "CF-Connecting-IP":"192.0.2.1", "X-Forwarded-For":"198.51.100.2", "X-Source":"spoofed"}, body: JSON.stringify({name:"Test",purpose:"Test",public_key:jwk}) });
  expect(r.status).toBe(429); await create("192.0.2.2");
});
test("per-IP creation sliding minute limit", async () => {
  for(let i=0;i<20;i++) { const c=await create(); await req(`/api/requests/${c.id}/cancel`,"POST",{},c.receive_token); }
  expect((await req("/api/requests","POST",{name:"Test",purpose:"Test",public_key:jwk})).status).toBe(429);
  await sql("UPDATE rates SET at=?",Date.now()-60001); await create();
});
test("global create rate and active capacity limits", async () => {
  for(let i=0;i<120;i++) await create(`192.0.2.${i}`);
  expect((await req("/api/requests","POST",{name:"Test",purpose:"Test",public_key:jwk},undefined,"198.51.100.1")).status).toBe(429);
  await sql("DELETE FROM rates"); for(let i=0;i<8;i++) await create(`198.51.100.${i}`);
  expect((await req("/api/requests","POST",{name:"Test",purpose:"Test",public_key:jwk},undefined,"198.51.100.99")).status).toBe(429);
});

test("input lookup rate applies to malformed bearer and is source isolated", async () => {
  for(let i=0;i<120;i++) expect((await req("/api/input","GET",undefined,"bad")).status).toBe(404);
  expect((await req("/api/input")).status).toBe(429); expect((await req("/api/input","GET",undefined,"bad","192.0.2.2")).status).toBe(404);
  await sql("UPDATE rates SET at=?",Date.now()-60001); expect((await req("/api/input")).status).toBe(404);
});
test("input source cardinality is bounded", async () => {
  for(let i=0;i<512;i++) await req("/api/input","GET",undefined,"bad",`198.51.${i>>8}.${i%256}`);
  expect((await req("/api/input","GET",undefined,"bad","203.0.113.1")).status).toBe(429);
});
test.each(["https://evil.example", "null", "https://relay.example/", "https://relay.example.evil"])("Origin rejected: %s", async origin => {
  const r=await mf.dispatchFetch("https://relay.example/",{headers:{Origin:origin}});expect(r.status).toBe(403);expect(r.headers.get("cache-control")).toBe("no-store");
});
test("JSON type, malformed body and streamed byte limit", async () => {
  expect((await mf.dispatchFetch("https://relay.example/api/requests",{method:"POST",body:"{}"})).status).toBe(415);
  for(const body of ["{", "null", "[]"]) expect((await mf.dispatchFetch("https://relay.example/api/requests",{method:"POST",headers:{"Content-Type":"application/json"},body})).status).toBe(422);
  expect((await mf.dispatchFetch("https://relay.example/api/requests",{method:"POST",headers:{"Content-Type":"application/json"},body:" ".repeat(100001)})).status).toBe(413);
});
test.each(["/", "/i", "/assets/app.js", "/assets/crypto.js", "/assets/home.js", "/assets/theme.js", "/assets/style.css", "/assets/home.css"])("static asset with secure headers: %s", async path => {
  const r=await req(path);expect(r.status).toBe(200);expect((await r.text()).length).toBeGreaterThan(100);expect(r.headers.get("referrer-policy")).toBe("no-referrer");expect(r.headers.get("content-security-policy")).toContain("frame-ancestors 'none'");
});
test("unknown assets, old paths and health",async()=>{
  for(const path of ["/assets/private", "/input/id", "/api/list", "/api/requests"]) expect((await req(path)).status).toBe(404);
  expect(await (await req("/health")).json()).toEqual({status:"ok",version:"0.3.0",access:"anonymous"});
});
test("SQLite durable persistence across full runtime restart preserves salt, tokens, limits and once-only state",async()=>{
  const directory=await mkdtemp(join(tmpdir(),"secret-request-do-"));
  await mf.dispose(); mf=await fixture({persist:directory});
  const c=await create(); await req(`/api/requests/${c.id}/submit`,"POST",envelope,c.submit);
  const before=await control("inspect"); await mf.dispose();mf=await fixture({persist:directory});
  expect((await (await req("/api/input","GET",undefined,c.submit)).json() as any).state).toBe("submitted");
  expect((await control("inspect")).rows[0].source).toBe(before.rows[0].source);
  expect((await control("inspect")).rates.filter((r: any) => r.kind === "create")).toHaveLength(1);
  expect((await req(`/api/requests/${c.id}/consume`,"POST",{},c.receive_token)).status).toBe(200);
  await mf.dispose();mf=await fixture({persist:directory});expect((await req(`/api/requests/${c.id}/consume`,"POST",{},c.receive_token)).status).toBe(409);
});
test("HTTP schema/envelope rejection leaves request pending", async () => {
  const c = await create();
  expect((await req(`/api/requests/${c.id}/submit`, "POST", {...envelope, v:true}, c.submit)).status).toBe(422);
  expect((await (await req(`/api/requests/${c.id}/status`, "GET", undefined, c.receive_token)).json() as any).state).toBe("pending");
  expect((await req("/api/requests", "POST", {name:"Test",purpose:"Test",public_key:{...jwk,d:"private"}})).status).toBe(422);
});
test("malformed bearer and receive capabilities never resolve submit lookup", async () => {
  const c = await create();
  for(const value of ["a".repeat(21),"a".repeat(23),"a".repeat(42),"a".repeat(44),"bad token","a".repeat(21)+"/",c.receive_token]) {
    expect((await req("/api/input","GET",undefined,value)).status).toBe(404);
    expect((await req(`/api/requests/${c.id}/status`,"GET",undefined,value)).status).toBe(value === c.receive_token ? 200 : 404);
  }
});
test.each([
  {}, [], null, {name:"",purpose:"x",public_key:jwk}, {name:"x\n",purpose:"x",public_key:jwk},
  {name:"x",purpose:" ",public_key:jwk}, {name:"x",purpose:"x",public_key:jwk,extra:1},
  ...[null,true,9,1801,10.5,"10"].map(ttl_seconds=>({name:"x",purpose:"x",public_key:jwk,ttl_seconds})),
  ...[[],[{id:"constructor",label:"x",type:"text"}],[{id:"x",label:"x",type:"file"}],[{id:"x",label:"x",type:"text",required:null}],[{id:"x",label:"x",type:"text",value:"secret"}]].map(fields=>({name:"x",purpose:"x",public_key:jwk,fields})),
])("invalid create schema %#",body=>expect(createBody(body)).toBeNull());
test.each([{}, {...jwk, d:"private"}, {...jwk,e:"Aw"}, {...jwk,n:"a"}, {...jwk,n:Buffer.alloc(384,1).toString("base64url")}, {...jwk,n:n+"!"}])("invalid JWK %#",key=>expect(validJwk(key)).toBe(false));
test.each([{}, {...envelope,v:true}, {...envelope,v:2}, {...envelope,nonce:"short"}, {...envelope,wrapped_key:"a"}, {...envelope,ciphertext:Buffer.alloc(16).toString("base64url")}, {...envelope,ciphertext:Buffer.alloc(65553).toString("base64url")}, {...envelope,extra:1}])("invalid envelope %#",value=>expect(validEnvelope(value)).toBe(false));

async function measurement() { return (await req("/__test/metrics")).json() as Promise<any>; }
async function measured(run: () => Promise<unknown>) {
  await control("metrics"); await run(); return measurement();
}

test("SQL measurement consumes the entire cursor before reading rowsRead", async () => {
  const m = await measured(() => control("measure", {query:"WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<37) SELECT x FROM n"}));
  expect(m.queries).toHaveLength(1); expect(m.rowsRead).toBeGreaterThanOrEqual(37);
});

test("complete requests stay bounded at 61440 input rates and 640 active/terminal requests", async () => {
  const c = await create();
  const [{source}] = await sql("SELECT source FROM requests WHERE id=?", c.id);
  const at = Date.now();
  await sql("DELETE FROM rates");
  await sql(`WITH RECURSIVE s(i) AS (VALUES(0) UNION ALL SELECT i+1 FROM s WHERE i<511),
    r(j) AS (VALUES(0) UNION ALL SELECT j+1 FROM r WHERE j<119)
    INSERT INTO rates SELECT 'input', CASE WHEN i=0 THEN ? ELSE 'seed-'||i END,
    CASE WHEN i=0 AND j=0 THEN ? ELSE ? END FROM s CROSS JOIN r`, source, at-61000, at);
  await sql("INSERT INTO input_sources SELECT source, MAX(at) FROM rates GROUP BY source");
  await sql(`WITH RECURSIVE n(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM n WHERE i<512)
    INSERT INTO requests SELECT 'seed-'||i, 'source-'||i, 'submit-'||i, 'receive-'||i, deadline, 'consumed', data, NULL, ? FROM n CROSS JOIN requests WHERE id=?`, at, c.id);
  await sql(`WITH RECURSIVE n(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM n WHERE i<127)
    INSERT INTO requests SELECT 'active-'||i, 'active-source-'||i, 'active-submit-'||i, 'active-receive-'||i, deadline, 'pending', data, NULL, NULL FROM n CROSS JOIN requests WHERE id=?`, c.id);
  expect((await sql("SELECT COUNT(*) n FROM rates"))[0].n).toBe(61440);
  expect((await sql("SELECT COUNT(*) n FROM requests"))[0].n).toBe(640);
  const results: Record<string, any> = {};
  results.legal = await measured(async () => expect((await req("/api/input", "GET", undefined, c.submit)).status).toBe(200));
  results.limited = await measured(async () => expect((await req("/api/input", "GET", undefined, c.submit)).status).toBe(429));
  results.newSource = await measured(async () => expect((await req("/api/input", "GET", undefined, c.submit, "203.0.113.99")).status).toBe(429));
  results.create = await measured(async () => expect((await req("/api/requests", "POST", {name:"x",purpose:"x",public_key:jwk})).status).toBe(429));
  await sql("DELETE FROM requests WHERE id='active-127'");
  results.createAllowed = await measured(() => create("203.0.113.88"));
  for (const m of Object.values(results)) {
    expect(m.rowsRead).toBeLessThan(2048); expect(m.doAccesses).toBe(1); expect(m.doFetches).toBe(1);
    expect(m.alarmWrites).toBe(0); expect(m.alarmDeletes).toBe(0);
    expect(m.queries.every((q: any) => !q.query.includes("DISTINCT") && !q.query.includes("UNION"))).toBe(true);
  }
  for (const [path, method, status] of [["/api/nope","GET",404],["/api/input","POST",405]] as const) {
    const m = await measured(async () => expect((await req(path,method)).status).toBe(status));
    expect(m.doAccesses).toBe(0); expect(m.queries).toHaveLength(0);
  }
  const plans = [
    ["SELECT deadline FROM requests WHERE state IN ('pending','submitted') ORDER BY deadline LIMIT 1", "requests_active_deadline"],
    ["SELECT terminal_at FROM requests WHERE terminal_at IS NOT NULL ORDER BY terminal_at LIMIT 1", "requests_terminal_time"],
    ["SELECT at FROM rates ORDER BY at LIMIT 1", "rates_time"],
  ];
  const alarm = await measured(() => control("alarm"));
  for (const [query, index] of plans) {
    const q = alarm.queries.find((q: any) => q.query === query);
    expect(q).toBeDefined(); expect(q.rowsRead).toBeLessThanOrEqual(1);
    const plan = JSON.stringify(await sql("EXPLAIN QUERY PLAN " + query));
    expect(plan).toContain(index); expect(plan).not.toContain("TEMP B-TREE");
  }
  console.log("capacity rowsRead", JSON.stringify(Object.fromEntries(Object.entries(results).map(([k,v]) => [k, {rowsRead:v.rowsRead,sqlCalls:v.queries.length,alarmWrites:v.alarmWrites}]))));
});

test.each([
  ["/api/unknown", "GET", 404], ["/api/requests", "GET", 404],
  ["/api/input", "POST", 405], ["/api/requests/x/consume", "GET", 405],
  ["/api/requests/x/status", "POST", 405], ["/api/requests/x/nope", "POST", 404],
  ["/api/input", "PUT", 405], ["/api/requests/x", "OPTIONS", 405],
])("rejects route/method before DO and SQL: %s %s", async (path, method, status) => {
  const outer = await measured(async () => expect((await req(path, method)).status).toBe(status));
  expect(outer.doAccesses).toBe(0); expect(outer.doFetches).toBe(0); expect(outer.queries).toHaveLength(0);
  const inner = await measured(async () => expect((await control("fetch", {path,method})).status).toBe(status));
  expect(inner.doFetches).toBe(1); expect(inner.queries).toHaveLength(0); expect(inner.alarmWrites).toBe(0);
});

test("input window expires individual events and source slots without waiting for alarm", async () => {
  await req("/api/input");
  const [{source}] = await sql("SELECT source FROM input_sources");
  const at = Date.now();
  await sql("DELETE FROM rates");
  await sql(`WITH RECURSIVE n(i) AS (VALUES(0) UNION ALL SELECT i+1 FROM n WHERE i<119)
    INSERT INTO rates SELECT 'input', ?, CASE WHEN i<60 THEN ? ELSE ? END FROM n`, source, at-61000, at-10000);
  await sql("UPDATE input_sources SET last_at=?", at-10000);
  for (let i=0; i<60; i++) expect((await req("/api/input")).status).toBe(404);
  expect((await req("/api/input")).status).toBe(429);
  expect((await sql("SELECT COUNT(*) n FROM rates WHERE source=?",source))[0].n).toBe(120);
  await sql("UPDATE rates SET at=?", at-61000);
  await sql("UPDATE input_sources SET last_at=?", at-61000);
  await sql(`WITH RECURSIVE n(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM n WHERE i<511)
    INSERT INTO input_sources SELECT 'old-'||i, ? FROM n`, at-61000);
  const m = await measured(async () => expect((await req("/api/input", "GET", undefined, "bad", "203.0.113.77")).status).toBe(404));
  expect(m.rowsRead).toBeLessThan(2048);
  expect((await sql("SELECT COUNT(*) n FROM input_sources"))[0].n).toBe(1);
  // Expired history for other sources remains for alarm cleanup only.
  expect((await sql("SELECT COUNT(*) n FROM rates"))[0].n).toBe(121);
});

test("terminal transitions keep an earlier alarm, while a shorter deadline advances it", async () => {
  const a = await create(); const first = (await control("inspect")).alarm;
  const b = await create("192.0.2.2", 10); const earlier = (await control("inspect")).alarm;
  expect(earlier).toBeLessThan(first);
  for (const action of ["submit", "consume"]) {
    const m = await measured(() => req(`/api/requests/${b.id}/${action}`, "POST", action === "submit" ? envelope : {}, action === "submit" ? b.submit : b.receive_token));
    expect(m.alarmWrites).toBe(0); expect((await control("inspect")).alarm).toBe(earlier);
  }
  await req(`/api/requests/${a.id}/cancel`, "POST", {}, a.receive_token);
  expect((await control("inspect")).alarm).toBe(earlier);
  await control("alarm"); expect((await control("inspect")).alarm).toBe(first);
});

test("alarm advances through deadline and retention, then removes all persisted scheduling state", async () => {
  const c = await create(); await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit);
  await sql("DELETE FROM rates");
  const deadline = Date.now()-100;
  await sql("UPDATE requests SET deadline=?", deadline); await control("alarm");
  let state = await control("inspect");
  expect(state.rows[0].state).toBe("expired"); expect(state.rows[0].envelope).toBeNull(); expect(state.alarm).toBe(deadline+60000);
  await sql("UPDATE requests SET terminal_at=?", Date.now()-60001); await control("alarm");
  state = await control("inspect"); expect(state.rows).toHaveLength(0); expect(state.alarm).toBeNull();
  expect(await sql("SELECT * FROM meta WHERE key='alarm_at'")).toHaveLength(0);
});

test("targeted lookups enforce retention even before a delayed alarm", async () => {
  const c = await create(); await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit);
  await sql("UPDATE requests SET deadline=?", Date.now()-60001);
  expect((await req(`/api/requests/${c.id}/consume`, "POST", {}, c.receive_token)).status).toBe(404);
  expect(await sql("SELECT * FROM requests WHERE id=?",c.id)).toHaveLength(0);
  expect((await req("/api/input", "GET", undefined, c.submit)).status).toBe(404);
});

test("persisted alarm and input-source window survive restart and expire without traffic", async () => {
  const directory = await mkdtemp(join(tmpdir(),"secret-request-alarm-"));
  await mf.dispose(); mf = await fixture({persist:directory});
  const c = await create("192.0.2.1",10);
  await req(`/api/requests/${c.id}/submit`, "POST", envelope, c.submit);
  await req("/api/input", "GET", undefined, c.submit);
  const before = await control("inspect");
  await mf.dispose(); mf = await fixture({persist:directory});
  const restored = await control("inspect");
  expect(restored.alarm).toBe(before.alarm); expect(restored.sources).toEqual(before.sources);
  const m = await measured(() => req("/api/input", "GET", undefined, c.submit));
  expect(m.alarmWrites).toBe(0);
  const delay = Math.max(0, before.alarm-Date.now())+700;
  await new Promise(resolve => setTimeout(resolve,delay));
  const after = await control("inspect");
  expect(after.rows[0].state).toBe("expired"); expect(after.rows[0].envelope).toBeNull();
  expect(after.alarm).toBeGreaterThan(before.alarm);
});

test("longest-TTL immediate cancellation for 28 simulated minutes cannot exhaust another source", async () => {
  const start = Date.now();
  for (let minute=0; minute<28; minute++) {
    await control("clock", {now:start+minute*60000});
    for (let i=0; i<20; i++) {
      const c = await create("192.0.2.1",1800);
      expect((await req(`/api/requests/${c.id}/cancel`,"POST",{},c.receive_token)).status).toBe(200);
    }
    expect((await req("/api/requests","POST",{name:"x",purpose:"x",public_key:jwk,ttl_seconds:1800})).status).toBe(429);
    const other = await create("203.0.113.7",1800);
    await req(`/api/requests/${other.id}/cancel`,"POST",{},other.receive_token);
    expect((await sql("SELECT COUNT(*) n FROM requests"))[0].n).toBeLessThanOrEqual(21);
    await control("alarm");
  }
});

test.each(["cancel","decline","consume"])("%s keeps status for exactly 60 seconds from transition, independent of TTL", async action => {
  const start = Date.now(); await control("clock",{now:start});
  const c = await create("192.0.2.1",1800);
  await control("clock",{now:start+5000});
  if (action === "consume") await req(`/api/requests/${c.id}/submit`,"POST",envelope,c.submit);
  expect((await req(`/api/requests/${c.id}/${action}`,"POST",{},action === "decline" ? c.submit : c.receive_token)).status).toBe(200);
  expect((await sql("SELECT terminal_at FROM requests WHERE id=?",c.id))[0].terminal_at).toBe(start+5000);
  await control("clock",{now:start+64999});
  expect((await req(`/api/requests/${c.id}/status`,"GET",undefined,c.receive_token)).status).toBe(200);
  expect((await req(`/api/requests/${c.id}/consume`,"POST",{},c.receive_token)).status).toBe(409);
  await control("clock",{now:start+65000});
  expect((await req(`/api/requests/${c.id}/status`,"GET",undefined,c.receive_token)).status).toBe(404);
  expect((await req(`/api/requests/${c.id}/consume`,"POST",{},c.receive_token)).status).toBe(404);
});

test("expired retention starts at deadline, alarm keeps it until the exact boundary", async () => {
  const start = Date.now(); await control("clock",{now:start});
  const c = await create("192.0.2.1",10);
  await req(`/api/requests/${c.id}/submit`,"POST",envelope,c.submit);
  await control("clock",{now:start+20000}); await control("alarm");
  expect((await sql("SELECT state, terminal_at, envelope FROM requests WHERE id=?",c.id))[0]).toEqual({state:"expired",terminal_at:start+10000,envelope:null});
  await control("clock",{now:start+60000}); await control("alarm");
  expect((await control("inspect")).alarm).toBe(start+70000);
  await control("clock",{now:start+69999});
  expect((await req(`/api/requests/${c.id}/status`,"GET",undefined,c.receive_token)).status).toBe(200);
  await control("clock",{now:start+70000}); await control("alarm");
  expect((await control("inspect")).rows).toHaveLength(0);
  expect((await control("inspect")).alarm).toBeNull();
});

test("terminal hard cap evicts the oldest terminal while preserving all 128 active requests", async () => {
  const at = Date.now(); await control("clock",{now:at});
  const c = await create();
  await sql(`WITH RECURSIVE n(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM n WHERE i<127)
    INSERT INTO requests SELECT 'active-'||i, 'other-'||i, 'as-'||i, 'ar-'||i, deadline, 'pending', data, NULL, NULL FROM n CROSS JOIN requests WHERE id=?`,c.id);
  await sql(`WITH RECURSIVE n(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM n WHERE i<512)
    INSERT INTO requests SELECT 'old-'||i, source, 'os-'||i, 'or-'||i, deadline, 'consumed', data, NULL, ?+i FROM n CROSS JOIN requests WHERE id=?`,at-1000,c.id);
  expect((await sql("SELECT COUNT(*) n FROM requests"))[0].n).toBe(640);
  const m = await measured(() => req(`/api/requests/${c.id}/cancel`,"POST",{},c.receive_token));
  expect(m.rowsRead).toBeLessThan(2048);
  expect((await sql("SELECT COUNT(*) n FROM requests WHERE terminal_at IS NOT NULL"))[0].n).toBe(512);
  expect(await sql("SELECT id FROM requests WHERE id='old-1'")).toHaveLength(0);
  expect((await sql("SELECT COUNT(*) n FROM requests WHERE state='pending'"))[0].n).toBe(127);
  await create("203.0.113.8");
  expect((await sql("SELECT COUNT(*) n FROM requests WHERE state='pending'"))[0].n).toBe(128);
  expect((await sql("SELECT COUNT(*) n FROM requests"))[0].n).toBe(640);
});

test("terminal timestamp survives cold restart with complete constructor SQL measured", async () => {
  const directory = await mkdtemp(join(tmpdir(),"secret-request-terminal-"));
  await mf.dispose(); mf = await fixture({persist:directory});
  const at = Date.now(); await control("clock",{now:at});
  const c = await create("192.0.2.1",1800);
  await req(`/api/requests/${c.id}/submit`,"POST",envelope,c.submit);
  await req(`/api/requests/${c.id}/consume`,"POST",{},c.receive_token);
  const alarm = (await control("inspect")).alarm;
  await mf.dispose(); mf = await fixture({persist:directory});
  const m = await measured(async () => expect((await req(`/api/requests/${c.id}/consume`,"POST",{},c.receive_token)).status).toBe(409));
  expect(m.queries.some((q: any) => q.query.includes("CREATE TABLE"))).toBe(true);
  expect(m.rowsRead).toBeLessThan(100); expect(m.alarmWrites).toBe(0);
  expect((await control("inspect")).alarm).toBe(alarm);
  await control("clock",{now:at+59999});
  expect((await req(`/api/requests/${c.id}/status`,"GET",undefined,c.receive_token)).status).toBe(200);
  await control("clock",{now:at+60000});
  expect((await req(`/api/requests/${c.id}/consume`,"POST",{},c.receive_token)).status).toBe(404);
  expect(await sql("SELECT * FROM requests WHERE id=?",c.id)).toHaveLength(0);
});

test.each(["+", "/", "="])("strict base64url rejects %s in every wire field", async character => {
  const c = await create();
  const badN = character === "=" ? n+character : character+n.slice(1);
  expect(validJwk({...jwk,n:badN})).toBe(false);
  expect((await req("/api/requests", "POST", {name:"x",purpose:"x",public_key:{...jwk,n:badN}})).status).toBe(422);
  for (const field of ["wrapped_key", "nonce", "ciphertext"] as const) {
    const value = character === "=" ? envelope[field]+character : character+envelope[field].slice(1);
    const bad = {...envelope,[field]:value}; expect(validEnvelope(bad)).toBe(false);
    expect((await req(`/api/requests/${c.id}/submit`, "POST", bad, c.submit)).status).toBe(422);
  }
});

test("strict base64url accepts valid remainders and URL-safe alphabet only", () => {
  for (const size of [0,1,2,3,12,17,18,19,384,65552]) {
    const bytes = Buffer.alloc(size,255), encoded = bytes.toString("base64url");
    expect(Buffer.from(decode(encoded))).toEqual(bytes);
  }
  expect(Buffer.from(decode("-_8"))).toEqual(Buffer.from([251,255]));
  for (const text of ["a", "aaaaa", "a=", "AA==", "AAA=", "AA\n", "+w", "/w"]) expect(() => decode(text)).toThrow();
  expect(validJwk({...jwk,n:Buffer.alloc(384,255).toString("base64url")})).toBe(true);
  for (const size of [17,18,19]) expect(validEnvelope({v:1,wrapped_key:Buffer.alloc(384,255).toString("base64url"),nonce:Buffer.alloc(12,255).toString("base64url"),ciphertext:Buffer.alloc(size,255).toString("base64url")})).toBe(true);
});
