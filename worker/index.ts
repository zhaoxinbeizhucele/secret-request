import { DurableObject } from "cloudflare:workers";
import home from "../secret_request/web/home.html";
import input from "../secret_request/web/index.html";
import app from "../secret_request/web/app.js";
import cryptoJs from "../secret_request/web/crypto.js";
import homeJs from "../secret_request/web/home.js";
import theme from "../secret_request/web/theme.js";
import style from "../secret_request/web/style.css";
import homeCss from "../secret_request/web/home.css";
import { createBody, validEnvelope } from "./schema";

export interface Env { BASE_URL: string; RELAY: DurableObjectNamespace<Relay> }
export const SECURITY = {
  "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
  "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
};
function json(value: unknown, status = 200) { return Response.json(value, { status, headers: SECURITY }); }
function error(status: number, detail: string) { return json({ detail }, status); }
function apiRoute(path: string, method: string): Response | undefined {
  // Keep GET /api/requests undiscoverable, as in the existing protocol.
  if (path === "/api/requests") return method === "POST" ? undefined : error(404, "not_found");
  if (path === "/api/input") return method === "GET" ? undefined : error(405, "method_not_allowed");
  const match = /^\/api\/requests\/[A-Za-z0-9_-]+(?:\/(status|submit|decline|cancel|consume))?$/.exec(path);
  if (!match) return error(404, "not_found");
  return method === (!match[1] || match[1] === "status" ? "GET" : "POST") ? undefined : error(405, "method_not_allowed");
}
const files: Record<string, [string, string]> = {
  "/": [home, "text/html"], "/i": [input, "text/html"],
  "/assets/app.js": [app, "application/javascript"], "/assets/crypto.js": [cryptoJs, "application/javascript"],
  "/assets/home.js": [homeJs, "application/javascript"], "/assets/theme.js": [theme, "application/javascript"],
  "/assets/style.css": [style, "text/css"], "/assets/home.css": [homeCss, "text/css"],
};
export async function readJson(request: Request): Promise<unknown | Response> {
  if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "json_required");
  const reader = request.body?.getReader();
  const chunks: Uint8Array[] = []; let size = 0, timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), 15000); });
  try {
    if (reader) while (true) {
      const chunk = await Promise.race([reader.read(), timeout]);
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > 100000) { void reader.cancel().catch(() => {}); return error(413, "request_too_large"); }
      chunks.push(chunk.value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const c of chunks) { bytes.set(c, offset); offset += c.length; }
    // State actions need no payload; create and submit require JSON.
    if (!size && !["/api/requests"].includes(new URL(request.url).pathname) && !request.url.endsWith("/submit")) return {};
    return JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes));
  } catch (e) {
    void reader?.cancel().catch(() => {});
    return error(e instanceof Error && e.message === "timeout" ? 408 : 422, e instanceof Error && e.message === "timeout" ? "request_timeout" : "invalid_request");
  } finally { clearTimeout(timer); }
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const origin = request.headers.get("origin");
    if (origin && origin !== env.BASE_URL) return error(403, "origin_not_allowed");
    const path = new URL(request.url).pathname;
    if (path.startsWith("/api/")) { const rejected = apiRoute(path, request.method); if (rejected) return rejected; }
    let body: unknown;
    if (["POST", "PUT", "PATCH"].includes(request.method)) {
      body = await readJson(request); if (body instanceof Response) return body;
    }
    if (request.method === "GET" && path === "/health") return json({ status: "ok", version: "0.3.0", access: "anonymous" });
    if ((request.method === "GET" || request.method === "HEAD") && Object.hasOwn(files, path)) {
      const [content, type] = files[path];
      return new Response(request.method === "HEAD" ? null : content, { headers: { ...SECURITY, "Content-Type": type + "; charset=utf-8" } });
    }
    if (!path.startsWith("/api/")) return error(404, "not_found");
    // Only this freshly constructed internal request reaches the DO. Incoming
    // XFF/Forwarded/internal headers never participate in source identity.
    const headers = new Headers({ "X-Source": request.headers.get("CF-Connecting-IP") || "unknown" });
    headers.set("Authorization", request.headers.get("Authorization") || "");
    if (body !== undefined) headers.set("Content-Type", "application/json");
    return env.RELAY.get(env.RELAY.idFromName("global")).fetch(new Request("https://relay.internal" + path, {
      method: request.method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    }));
  },
};

interface Row extends Record<string, SqlStorageValue> {
  id: string; source: string; submit_hash: string; receive_hash: string; deadline: number;
  state: string; data: string; envelope: string | null; terminal_at: number | null;
}
export function token(bytes: number): string {
  return btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(bytes)))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function hash(value: string) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))), b => b.toString(16).padStart(2, "0")).join("");
}
/** One durable object, synchronous SQL transactions: no await across a state change. */
export class Relay extends DurableObject<Env> {
  protected sql: SqlStorage;
  private salt: string;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env); this.sql = this.storageSql(ctx.storage.sql);
    ctx.storage.transactionSync(() => {
      this.sql.exec("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
      this.sql.exec("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, source TEXT NOT NULL, submit_hash TEXT UNIQUE NOT NULL, receive_hash TEXT NOT NULL, deadline INTEGER NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL, envelope TEXT, terminal_at INTEGER)");
      this.sql.exec("CREATE INDEX IF NOT EXISTS requests_active_deadline ON requests(deadline) WHERE state IN ('pending','submitted')");
      this.sql.exec("CREATE INDEX IF NOT EXISTS requests_terminal_time ON requests(terminal_at) WHERE terminal_at IS NOT NULL");
      this.sql.exec("CREATE TABLE IF NOT EXISTS rates (kind TEXT NOT NULL, source TEXT NOT NULL, at INTEGER NOT NULL)");
      this.sql.exec("CREATE INDEX IF NOT EXISTS rates_time ON rates(at)");
      this.sql.exec("CREATE INDEX IF NOT EXISTS rates_source ON rates(kind,source,at)");
      this.sql.exec("CREATE INDEX IF NOT EXISTS rates_kind_time ON rates(kind,at)");
      this.sql.exec("CREATE TABLE IF NOT EXISTS input_sources (source TEXT PRIMARY KEY, last_at INTEGER NOT NULL)");
      this.sql.exec("CREATE INDEX IF NOT EXISTS input_sources_time ON input_sources(last_at)");
      this.sql.exec("INSERT OR IGNORE INTO meta VALUES ('salt', ?)", token(32));
    });
    this.salt = this.sql.exec<{value: string}>("SELECT value FROM meta WHERE key='salt'").one().value;
  }
  protected storageSql(sql: SqlStorage) { return sql; }
  private count(query: string, ...args: (string | number)[]) { return this.sql.exec<{n: number}>(query, ...args).one().n; }
  protected now() { return Date.now(); }
  private trimTerminal(now: number) {
    this.sql.exec("DELETE FROM requests WHERE terminal_at<=?", now - 60000);
    const excess = this.count("SELECT COUNT(*) n FROM requests WHERE terminal_at IS NOT NULL") - 512;
    // Normal creation rates keep this below 512. The hard cap may shorten the
    // 60-second status window under excess load; active rows are never evicted.
    if (excess > 0) this.sql.exec("DELETE FROM requests WHERE id IN (SELECT id FROM requests WHERE terminal_at IS NOT NULL ORDER BY terminal_at LIMIT ?)", excess);
  }
  private purgeRequests(now: number) {
    this.sql.exec("UPDATE requests SET state='expired', envelope=NULL, terminal_at=deadline WHERE deadline<=? AND state IN ('pending','submitted')", now);
    this.trimTerminal(now);
  }
  private purge(now: number) {
    this.purgeRequests(now);
    this.sql.exec("DELETE FROM rates WHERE at<=?", now - 60000);
    this.sql.exec("DELETE FROM input_sources WHERE last_at<=?", now - 60000);
  }
  private schedule(now: number) {
    // Each earliest lookup visits at most one covering-index entry.
    const active = this.sql.exec<{deadline: number}>("SELECT deadline FROM requests WHERE state IN ('pending','submitted') ORDER BY deadline LIMIT 1").toArray()[0];
    const retained = this.sql.exec<{terminal_at: number}>("SELECT terminal_at FROM requests WHERE terminal_at IS NOT NULL ORDER BY terminal_at LIMIT 1").toArray()[0];
    const rate = this.sql.exec<{at: number}>("SELECT at FROM rates ORDER BY at LIMIT 1").toArray()[0];
    const at = Math.min(active?.deadline ?? Infinity, retained ? retained.terminal_at + 60000 : Infinity, rate ? rate.at + 60000 : Infinity);
    this.setAlarm(Number.isFinite(at) ? Math.max(now + 1, at) : null);
  }
  protected setAlarm(at: number | null) {
    // Alarm writes share the storage transaction and its output gate. They are
    // deliberately issued before returning a capability or consumed envelope.
    if (at === null) {
      this.sql.exec("DELETE FROM meta WHERE key='alarm_at'");
      void this.ctx.storage.deleteAlarm();
    } else {
      this.sql.exec("INSERT OR REPLACE INTO meta VALUES ('alarm_at', ?)", String(at));
      void this.ctx.storage.setAlarm(at);
    }
  }
  private scheduleEarlier(at: number) {
    const previous = this.sql.exec<{value: string}>("SELECT value FROM meta WHERE key='alarm_at'").toArray()[0];
    if (!previous || at < Number(previous.value)) this.setAlarm(at);
  }
  private current(row: Row | undefined, now: number): Row | undefined {
    if (!row) return row;
    if ((row.terminal_at ?? row.deadline) <= now - 60000) {
      this.sql.exec("DELETE FROM requests WHERE id=?", row.id); return undefined;
    }
    if (row.terminal_at === null && row.deadline <= now) {
      this.sql.exec("UPDATE requests SET state='expired', envelope=NULL, terminal_at=deadline WHERE id=?", row.id);
      row.state = "expired"; row.envelope = null; row.terminal_at = row.deadline;
      this.trimTerminal(now);
      if (!this.count("SELECT COUNT(*) n FROM requests WHERE id=?", row.id)) return undefined;
    }
    return row;
  }
  async alarm() {
    const now = this.now();
    this.ctx.storage.transactionSync(() => { this.purge(now); this.schedule(now); });
  }
  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname, method = request.method;
    const rejected = apiRoute(path, method); if (rejected) return rejected;
    const body: unknown = method === "POST" ? await request.json() : undefined;
    const bearer = request.headers.get("Authorization") || "";
    const presented = /^Bearer ([A-Za-z0-9_-]{22}|[A-Za-z0-9_-]{43})$/.exec(bearer)?.[1];
    // Hashing and random generation may await; all reads/checks/writes after
    // those awaits happen in one synchronous transaction, including cleanup.
    const source = await hash(this.salt + ":" + (request.headers.get("X-Source") || "unknown"));
    const hashed = presented ? await hash(presented) : "";
    const creating = method === "POST" && path === "/api/requests";
    const payload = creating ? createBody(body) : null;
    const rid = creating ? token(18) : "", submit = creating ? token(16) : "", receive = creating ? token(32) : "";
    const submitHash = creating ? await hash(submit) : "", receiveHash = creating ? await hash(receive) : "";
    const now = this.now();
    return this.ctx.storage.transactionSync(() => this.dispatch(path, method, body, payload, source, hashed, now, rid, submit, receive, submitHash, receiveHash));
  }
  private dispatch(path: string, method: string, body: unknown, payload: ReturnType<typeof createBody>, source: string, hashed: string, now: number, rid: string, submit: string, receive: string, submitHash: string, receiveHash: string): Response {
    if (method === "POST" && path === "/api/requests") {
      if (!payload) return error(422, "invalid_request");
      // At most 128 active + 512 terminal rows; creation reclaims activity.
      this.purgeRequests(now);
      if (this.count("SELECT COUNT(*) n FROM requests WHERE state IN ('pending','submitted')") >= 128 ||
          this.count("SELECT COUNT(*) n FROM requests WHERE source=? AND state IN ('pending','submitted')", source) >= 8 ||
          this.count("SELECT COUNT(*) n FROM rates WHERE kind='create' AND source=? AND at>?", source, now - 60000) >= 20 ||
          this.count("SELECT COUNT(*) n FROM rates WHERE kind='create' AND at>?", now - 60000) >= 120) return error(429, "request_limit");
      if (this.count("SELECT COUNT(*) n FROM requests WHERE id=? OR submit_hash=?", rid, submitHash)) return error(503, "unavailable");
      const deadline = now + payload.ttl_seconds * 1000;
      const data = { name: payload.name, purpose: payload.purpose, agent: payload.agent, fields: payload.fields, public_key: payload.public_key, created_at: new Date(now).toISOString(), expires_at: new Date(deadline).toISOString() };
      this.sql.exec("INSERT INTO requests VALUES (?,?,?,?,?,'pending',?,NULL,NULL)", rid, source, submitHash, receiveHash, deadline, JSON.stringify(data));
      this.sql.exec("INSERT INTO rates VALUES ('create',?,?)", source, now);
      this.scheduleEarlier(Math.min(deadline, now + 60000));
      return json({ id: rid, receive_token: receive, state: "pending", input_url: this.env.BASE_URL + "/i#" + submit, remaining_seconds: payload.ttl_seconds }, 201);
    }
    let row: Row | undefined;
    if (method === "GET" && path === "/api/input") {
      // Per-source history is at most 120 entries. Global rate cleanup belongs
      // to the alarm, so delayed alarms cannot turn a lookup into a full scan.
      this.sql.exec("DELETE FROM rates WHERE kind='input' AND source=? AND at<=?", source, now - 60000);
      const count = this.count("SELECT COUNT(*) n FROM rates WHERE kind='input' AND source=? AND at>?", source, now - 60000);
      if (count >= 120) return error(429, "request_limit");
      this.sql.exec("DELETE FROM input_sources WHERE last_at<=?", now - 60000);
      if (!count && this.count("SELECT COUNT(*) n FROM input_sources") >= 512) return error(429, "request_limit");
      this.sql.exec("INSERT INTO rates VALUES ('input',?,?)", source, now);
      this.sql.exec("INSERT OR REPLACE INTO input_sources VALUES (?,?)", source, now);
      this.scheduleEarlier(now + 60000);
      row = this.current(this.sql.exec<Row>("SELECT * FROM requests WHERE submit_hash=?", hashed).toArray()[0], now);
      return row ? this.public(row, now) : error(404, "request_not_found");
    }
    const match = /^\/api\/requests\/([A-Za-z0-9_-]+)(?:\/(status|submit|decline|cancel|consume))?$/.exec(path);
    if (!match) return error(404, "not_found");
    const action = match[2] || "details";
    if (method !== (["details", "status"].includes(action) ? "GET" : "POST")) return error(405, "method_not_allowed");
    if (action === "submit" && !validEnvelope(body)) return error(422, "invalid_envelope");
    row = this.current(this.sql.exec<Row>("SELECT * FROM requests WHERE id=?", match[1]).toArray()[0], now);
    const submitRole = ["details", "submit", "decline"].includes(action);
    if (!hashed || !row || hashed !== (submitRole ? row.submit_hash : row.receive_hash)) return error(404, "request_not_found");
    if (action === "details") return this.public(row, now);
    if (action === "status") return json({ state: row.state });
    if ((action === "consume" && row.state !== "submitted") || (action === "cancel" && !["pending", "submitted"].includes(row.state)) || (["submit", "decline"].includes(action) && row.state !== "pending")) return error(409, "request_unavailable");
    const next = { submit: "submitted", decline: "declined", cancel: "cancelled", consume: "consumed" }[action]!;
    this.sql.exec("UPDATE requests SET state=?, envelope=?, terminal_at=? WHERE id=?", next, action === "submit" ? JSON.stringify(body) : null, action === "submit" ? null : now, row.id);
    if (action !== "submit") { this.trimTerminal(now); this.scheduleEarlier(now + 60000); }
    // Consumed is committed before the response leaves the object. A lost
    // response deliberately cannot be retried to retrieve the ciphertext again.
    return action === "consume" ? json({ envelope: JSON.parse(row.envelope!) }) : json({ state: next });
  }
  private public(row: Row, now: number) {
    return json({ ...JSON.parse(row.data), id: row.id, state: row.state, remaining_seconds: Math.max(0, (row.deadline - now) / 1000) });
  }
}
