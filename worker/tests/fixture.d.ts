declare module "*.mjs" { export function fixture(options?: { port?: number; persist?: boolean | string; base?: string }): Promise<import("miniflare").Miniflare>; }
