# Cloudflare 版本地验证

2026-10-25，Windows / Node 22.22.0 / Python 3.13.5。工作区分支 `feat/cloudflare-worker`，基线 `416574978c18b59f6181c1141b93267e2f34ace5`。以下结果来自提交前的实现与本地验证；未部署、创建 CF 资源或修改 DNS/生产证书/实际客户端配置。

## 最终结果

| 命令 | 结果 |
| --- | --- |
| `npm ci` | 成功；77 packages audited，0 vulnerabilities |
| `npm test` | **63 passed**，17.52 秒 |
| `npm run typecheck` | 退出 0 |
| `npm run dry-run` | 退出 0，60.30 KiB / gzip 18.78 KiB；仅本地打包 |
| `python -m pytest -q --tb=short` | **194 passed**，147.69 秒，无跳过 |
| `python -I scripts/e2e_worker.py` | 退出 0，真实浏览器 WebCrypto 3 流程；见下文 |
| `python -I scripts/build_skill.py` | 成功；7 个客户端模块和两份依赖清单逐字节一致 |
| `python -I scripts/package_client.py` | 成功；23 个白名单文件，不含 Python 服务端、服务入口或网页副本 |
| `git diff --check` | 通过 |

Python 测试及 E2E 使用只读复用的独立环境 `C:/Users/zhaox/.codex_tmp/secret-request-domain-sr-zhaox-app/venv/Scripts/python.exe`，未安装或修改该环境。真实命令为该解释器加 `-m pytest -q --tb=short` 和 `-I scripts/e2e_worker.py`。未使用实际客户端配置或通知渠道。

## 覆盖

Worker 测试在真实 workerd / Miniflare SQLite Durable Object 上运行：API 正常流程、JWK/field/envelope schema、角色与请求隔离、无效 bearer、Origin、安全头、JSON 类型与大小、并发 submit/consume/cancel、响应丢失后不可重领、每 IP/全局在途和创建限流、查询限流与来源数量限制、512 条总记录限制。来源测试确认 XFF 和用户提供内部头不能改变限流来源。

到期测试覆盖请求即时过期、无 API 流量时定时 alarm 自动运行并将密文列清空、调用 alarm 清理截止后 600 秒记录及凭据索引和旧限流数据。持久化测试销毁并重新创建整个 Miniflare 运行时，使用同一 SQLite 目录验证未过期申请、来源哈希与限流记录保留，领取后再次重启仍不可重领。

Python 原有客户端/crypto/session/通知/安装/中断与浏览器覆盖保留，集成后端改为本地 Worker。额外使用真实 HTTP 慢流验证 15 秒返回 408，以及分块传输超过 100000 字节返回 413。浏览器回归包含多字段、明暗主题、窄屏、同标签页切换申请、提交与拒绝关页、断网重试及首页片段边界。企微配置使用选中 Worker 加密协议保存合成地址，拒绝/无效输入保留原文件，无群消息。

## Wrangler E2E

脚本自动选择独立 loopback 端口，以 `wrangler dev --local` 启动生产 Worker 入口，使用临时 SQLite 目录与临时客户端配置；不使用测试控制入口。headless 浏览器打开真实同源网页，实际 WebCrypto 加密并提交合成值。Python `client.run` 真正创建请求、生成私钥、领取解密并经 stdin 交给合成消费者，消费者校验完整字段值并写入非敏感成功标记。

最终输出：

```json
{"status":"passed","browser_webcrypto_flows":3,"client_decrypt_consumer":1,"duplicate_consume_rejected":1,"cancel_rejected_consume":1,"expiry_rejected_consume":1}
```

三个流程分别为客户端解密交付、浏览器提交后撤销、浏览器提交后自然过期。E2E 在完整退出与临时目录清理成功后才输出 passed。Windows 使用 Job 管理本测试的 Wrangler 进程树，防止遗留 workerd 句柄。脚本不输出 token、fragment 链接、密钥、Webhook 或原始异常。

## 发布边界

生产打包产物已检查，不含 `/__test/`、`TestRelay` 或测试 SQL 控制入口。GitHub Actions 只测试和本地打包，不部署或发布镜像。旧 Python 中转、本机产品模式、Docker 部署与过时验证记录已移除；客户端任务会话保留。

本地所有要求已完成。没有执行云端部署、Cloudflare runtime 验证、DNS/TLS 验证、真实企微通知或手机填写验收，也未在 Linux/macOS 运行本次全量测试。应用 SQL 清理不代表平台备份或恢复副本立即擦除。默认 `https://sr.zhaox.app` 仅为代码目标。
