# 公共服务

Cloudflare Workers + 一个 SQLite Durable Object 是唯一服务端，默认 URL 为 `https://sr.zhaox.app`。本次代码迁移不代表已部署，不改变 DNS、线上证书或实际客户端配置。

客户端通过 Worker 申请，浏览器使用 Worker 提供的同源页面加密，客户端一次领取解密后交给本机消费者。企微 Webhook 由客户端保存和调用；初始化也使用选定 Worker 的加密填写页，无需已有通知配置，不发送群消息。

部署资源及权限见 [DEPLOY.md](../DEPLOY.md)，本地证据见 [TEST-REPORT.md](../TEST-REPORT.md)。CI 只运行测试、类型检查和打包 dry-run，不发布镜像或自动部署。
