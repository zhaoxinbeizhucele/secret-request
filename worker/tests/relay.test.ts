import { beforeEach, afterAll, beforeAll, test, expect } from "vitest";
import { fixture } from "../../scripts/worker_fixture.mjs";
import { createBody, validEnvelope, validJwk } from "../schema";
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
  await sql("UPDATE requests SET deadline=?", Date.now()-600001); await sql("UPDATE rates SET at=?", Date.now()-60001); await control("alarm");
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
test("total record bound includes terminal entries", async () => {
  for(let batch=0;batch<5;batch++) {
    const amount=batch===4?32:120;
    for(let i=0;i<amount;i++) { const c=await create(`192.0.2.${i}`); await req(`/api/requests/${c.id}/cancel`,"POST",{},c.receive_token); }
    await sql("DELETE FROM rates");
  }
  expect((await control("inspect")).rows).toHaveLength(512);
  expect((await req("/api/requests","POST",{name:"Test",purpose:"Test",public_key:jwk})).status).toBe(429);
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
