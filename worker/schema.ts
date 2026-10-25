/** The client wire format. No cryptographic decryption at the relay. */
export type Dict = Record<string, unknown>;
export function object(value: unknown): value is Dict {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function keys(value: Dict, allowed: string[], required = allowed): boolean {
  return Object.keys(value).every(k => allowed.includes(k)) && required.every(k => Object.hasOwn(value, k));
}
const length = (s: string) => [...s].length;
function label(value: unknown, max: number): value is string {
  return typeof value === "string" && length(value) >= 1 && length(value) <= max && !!value.trim() && !/[\x00-\x1f]/.test(value);
}
export function decode(value: unknown): Uint8Array {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]*$/.test(value) || value.length % 4 === 1) throw new Error("base64");
  return Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4)), c => c.charCodeAt(0));
}
export function validJwk(value: unknown): boolean {
  try {
    if (!object(value) || !keys(value, ["kty", "e", "n"]) || value.kty !== "RSA" || value.e !== "AQAB") return false;
    const n = decode(value.n);
    return n.length === 384 && n[0] >= 128;
  } catch { return false; }
}
export function validEnvelope(value: unknown): boolean {
  try {
    if (!object(value) || !keys(value, ["v", "wrapped_key", "nonce", "ciphertext"]) || value.v !== 1) return false;
    const size = decode(value.ciphertext).length;
    return decode(value.wrapped_key).length === 384 && decode(value.nonce).length === 12 && size >= 17 && size <= 65552;
  } catch { return false; }
}
export interface Field { id: string; label: string; type: string; required: boolean }
export interface Create { name: string; purpose: string; ttl_seconds: number; public_key: Dict; agent: string; fields: Field[] | null }
export function createBody(value: unknown): Create | null {
  if (!object(value) || !keys(value, ["name", "purpose", "ttl_seconds", "public_key", "agent", "fields"], ["name", "purpose", "public_key"])) return null;
  if (!label(value.name, 100) || typeof value.purpose !== "string" || !value.purpose.trim() || length(value.purpose) > 500 || !validJwk(value.public_key)) return null;
  const ttl = value.ttl_seconds ?? 600, agent = value.agent === undefined ? "未注明 Agent" : value.agent;
  if (value.ttl_seconds === null || !Number.isInteger(ttl) || (ttl as number) < 10 || (ttl as number) > 1800 || !label(agent, 100)) return null;
  let fields: Field[] | null = null;
  if (value.fields !== undefined && value.fields !== null) {
    if (!Array.isArray(value.fields) || value.fields.length < 1 || value.fields.length > 16) return null;
    fields = []; const ids = new Set();
    for (const f of value.fields) {
      if (!object(f) || !keys(f, ["id", "label", "type", "required"], ["id", "label", "type"]) || typeof f.id !== "string" || !/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(f.id) || ids.has(f.id) || ["constructor", "prototype", "__proto__"].includes(f.id) || !label(f.label, 100) || typeof f.type !== "string" || !["text", "password", "textarea", "email", "url"].includes(f.type) || (f.required !== undefined && typeof f.required !== "boolean")) return null;
      ids.add(f.id); fields.push({ id: f.id, label: f.label.trim(), type: f.type, required: f.required === undefined ? true : f.required as boolean });
    }
  }
  return { name: value.name.trim(), purpose: value.purpose.trim(), public_key: value.public_key as Dict, ttl_seconds: ttl as number, agent: agent.trim(), fields };
}
