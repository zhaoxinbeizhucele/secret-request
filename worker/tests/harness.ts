// Test-only storage inspection. This module is never a Wrangler entrypoint.
import worker, { Relay, type Env } from "../index";
export class TestRelay extends Relay {
  async control(action: string, data: Record<string, unknown> = {}) {
    const sql = this.ctx.storage.sql;
    if (action === "reset") {
      sql.exec("DELETE FROM requests"); sql.exec("DELETE FROM rates");
      await this.ctx.storage.deleteAlarm(); return {};
    }
    if (action === "sql") return sql.exec(data.query as string, ...(data.args as SqlStorageValue[] || [])).toArray();
    if (action === "alarm") { await this.alarm(); return {}; }
    if (action === "inspect") return { rows: sql.exec("SELECT * FROM requests").toArray(), rates: sql.exec("SELECT * FROM rates").toArray(), alarm: await this.ctx.storage.getAlarm() };
    throw new Error("unknown test control");
  }
}
export default {
  async fetch(request: Request, env: Env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/__test/")) {
      const stub = env.RELAY.get(env.RELAY.idFromName("global")) as unknown as DurableObjectStub<TestRelay>;
      return Response.json(await stub.control(url.pathname.slice(8), request.method === "POST" ? await request.json() : {}));
    }
    return worker.fetch(request, env);
  },
};
