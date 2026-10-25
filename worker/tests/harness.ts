// Test-only storage inspection. This module is never a Wrangler entrypoint.
import worker, { Relay, type Env } from "../index";
type Measurement = { query: string; rowsRead: number; rowsWritten: number };
let metrics = { queries: [] as Measurement[], doAccesses: 0, doFetches: 0, alarmWrites: 0, alarmDeletes: 0 };
function instrument(sql: SqlStorage): SqlStorage {
  return new Proxy(sql, { get(target, key) {
    if (key !== "exec") { const v = Reflect.get(target, key); return typeof v === "function" ? v.bind(target) : v; }
    return (query: string, ...args: SqlStorageValue[]) => {
      const cursor = target.exec(query, ...args);
      // rowsRead is final only after the entire cursor has been consumed.
      const rows = cursor.toArray();
      metrics.queries.push({ query, rowsRead: cursor.rowsRead, rowsWritten: cursor.rowsWritten });
      return new Proxy(cursor, { get(c, name) {
        if (name === "toArray") return () => rows;
        if (name === "one") return () => { if (rows.length !== 1) throw new Error("expected one row"); return rows[0]; };
        if (name === Symbol.iterator) return () => rows[Symbol.iterator]();
        if (name === "raw") return function* () { for (const row of rows) yield c.columnNames.map(k => row[k]); };
        const v = Reflect.get(c, name); return typeof v === "function" ? v.bind(c) : v;
      } });
    };
  } });
}
export class TestRelay extends Relay {
  private testNow: number | undefined;
  protected now() { return this.testNow ?? Date.now(); }
  protected storageSql(sql: SqlStorage) { return instrument(sql); }
  protected setAlarm(at: number | null) { if (at === null) metrics.alarmDeletes++; else metrics.alarmWrites++; super.setAlarm(at); }
  async fetch(request: Request) { metrics.doFetches++; return super.fetch(request); }
  async control(action: string, data: Record<string, unknown> = {}) {
    const sql = this.ctx.storage.sql;
    if (action === "reset") {
      this.testNow = undefined;
      sql.exec("DELETE FROM requests"); sql.exec("DELETE FROM rates");
      sql.exec("DELETE FROM input_sources"); sql.exec("DELETE FROM meta WHERE key='alarm_at'");
      await this.ctx.storage.deleteAlarm(); return {};
    }
    if (action === "sql") return sql.exec(data.query as string, ...(data.args as SqlStorageValue[] || [])).toArray();
    if (action === "measure") return this.sql.exec(data.query as string).toArray();
    if (action === "clock") { this.testNow = data.now as number; return {}; }
    if (action === "alarm") { await this.alarm(); return {}; }
    if (action === "fetch") { const response = await this.fetch(new Request("https://relay.internal" + data.path, { method: data.method as string })); return { status: response.status }; }
    if (action === "inspect") return { rows: sql.exec("SELECT * FROM requests").toArray(), rates: sql.exec("SELECT * FROM rates").toArray(), sources: sql.exec("SELECT * FROM input_sources").toArray(), alarm: await this.ctx.storage.getAlarm() };
    throw new Error("unknown test control");
  }
}
export default {
  async fetch(request: Request, env: Env) {
    const url = new URL(request.url);
    if (url.pathname === "/__test/metrics") {
      const result = { ...metrics, rowsRead: metrics.queries.reduce((sum, q) => sum + q.rowsRead, 0) };
      if (request.method === "POST") metrics = { queries: [], doAccesses: 0, doFetches: 0, alarmWrites: 0, alarmDeletes: 0 };
      return Response.json(result);
    }
    if (url.pathname.startsWith("/__test/")) {
      const stub = env.RELAY.get(env.RELAY.idFromName("global")) as unknown as DurableObjectStub<TestRelay>;
      return Response.json(await stub.control(url.pathname.slice(8), request.method === "POST" ? await request.json() : {}));
    }
    const relay = new Proxy(env.RELAY, { get(target, key) {
      if (key === "get") return (...args: Parameters<typeof target.get>) => { metrics.doAccesses++; return target.get(...args); };
      const v = Reflect.get(target, key); return typeof v === "function" ? v.bind(target) : v;
    } });
    return worker.fetch(request, { ...env, RELAY: relay });
  },
};
