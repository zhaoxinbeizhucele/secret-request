# Cloudflare 部署

本分支只完成代码和本地验证。部署、创建资源或修改域名/DNS 须另行授权；下列步骤留给以后执行。

采用 Worker + 单个 SQLite Durable Object：单对象同步事务保证状态机、限流与一次领取；SQLite 在重启后保留申请。无 KV/D1/R2、外部服务或 Python 服务端。网页作为文本随 Worker 打包，不另建静态站点。

`wrangler.jsonc` 不含账号 ID 或凭据。`RELAY` binding 指向 `Relay` 类；首次部署通过 `v1` migration 的 `new_sqlite_classes` 注册 SQLite DO，运行时以 `idFromName("global")` 建立唯一对象。无需手工预建数据库。`workers_dev` 和 `preview_urls` 均关闭，日志采集关闭。

匿名应用协议不需要应用 secret。自动化部署可从安全环境提供 `CLOUDFLARE_API_TOKEN` 和 `CLOUDFLARE_ACCOUNT_ID`；不可提交或回显。Token 最小权限为目标账户的 Workers Scripts Edit；使用 Wrangler 管理 custom domain 时还需目标 zone 的 Workers Routes Edit 和 Zone Read。若选择手工域名步骤，使用控制台已有权限绑定。只限定目标账户和 zone，不申请全账户通配权限。Durable Object 的 migration 随 Worker 脚本发布，不需独立数据库密钥。

以后获授权后，确认目标账户与已有 zone `zhaox.app`，确认套餐支持 SQLite Durable Objects；检查 `BASE_URL=https://sr.zhaox.app` 与 custom-domain route 一致。首次运行 `npx wrangler deploy` 发布 Worker/migration 并绑定 `sr.zhaox.app`。也可先不配置 route，发布后在 Workers 设置的 Domains & Routes 中添加 Custom Domain。若域名已有冲突记录，按另行授权处理，不能自动覆盖其他业务。Cloudflare 为 custom domain 管理 DNS 与 TLS；本次不执行该步骤。

更新后检查 `/health`、静态资源及合成值浏览器完整加密交付；健康检查不等于业务验收。已有客户端配置只在授权后改 URL。退回旧 Worker 版本前检查 migration 兼容性，不能删除 DO 命名空间作为常规回退。

## 本地验证

Node 22.20+，Python 3.12+。`npm ci`、`npm test`、`npm run typecheck`、`npm run dry-run` 均无需 CF 登录。`npm run dev` 只运行 `wrangler dev --local --config wrangler.local.jsonc`，本地覆盖 URL 为 `http://127.0.0.1:8787`，不修改生产配置或域名。客户端接受 loopback HTTP 只供这个开发入口。

`python -I scripts/e2e_worker.py` 自动在可用端口启动独立本地 Wrangler（临时配置和 SQLite 目录），使用真实 Python 客户端和 headless 浏览器 WebCrypto。需要当前独立 Python 环境安装 requirements、pytest、Playwright 与 Chromium。测试入口/存储控制只在 Miniflare 测试模块存在，不随生产入口打包。
