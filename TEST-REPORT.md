# Cloudflare 版本地验证

2026-10-25，Windows / Node 22.22.0 / Python 3.13.5。工作区分支 `feat/cloudflare-worker`，本轮四项审查修复基线 `cef4a5b3058e6935b319ed7a5aea422552872b7f`。以下结果来自提交前的实现与本地验证；未部署、创建 CF 资源或修改 DNS/生产证书/实际客户端配置。

## 最终结果

| 命令 | 结果 |
| --- | --- |
| `npm ci` | 原实现验证时成功；本轮复用已有 node_modules，未重装 |
| `npm test -- --silent=false` | **88 passed**，30.68 秒 |
| `npm run typecheck` | 退出 0 |
| `npm run dry-run` | 退出 0，63.69 KiB / gzip 19.41 KiB；仅本地打包 |
| `python -m pytest -q` | **194 passed**，146.03 秒，无跳过 |
| `python -I scripts/e2e_worker.py` | 退出 0，真实浏览器 WebCrypto 3 流程；见下文 |
| `python -I scripts/build_skill.py` | 成功；7 个客户端模块和两份依赖清单逐字节一致 |
| `python -I scripts/package_client.py` | 成功；23 个白名单文件，不含 Python 服务端、服务入口或网页副本 |
| `git diff --check` | 通过 |

本轮 Python 测试及 E2E 使用 `%TEMP%/pr6-worker-20261025-231451/isolated-venv/Scripts/python.exe`，依赖安装在该临时环境内，未修改用户 Python 环境。真实命令为该解释器加 `-m pytest -q` 和 `-I scripts/e2e_worker.py`。最初复用用户包的 venv 因 `-I` 子进程不可见用户依赖而失败，已改用独立 venv 重跑。未使用实际客户端配置或通知渠道。完整命令日志位于同一临时目录。

## 覆盖

Worker 测试在真实 workerd / Miniflare SQLite Durable Object 上运行：API 正常流程、JWK/field/envelope schema、角色与请求隔离、无效 bearer、Origin、安全头、JSON 类型与大小、并发 submit/consume/cancel、响应丢失后不可重领、每 IP/全局在途和创建限流、查询限流与来源数量限制。活动全局最多 128 条、每来源 8 条；终态独立最多 512 条，总量最多 640 条。来源测试确认 XFF 和用户提供内部头不能改变限流来源。

到期测试覆盖请求即时过期、无 API 流量时定时 alarm 自动运行并将密文列清空、终态时刻起 60 秒清理（expired 自 deadline 起算）、过期后请求与凭据索引删除。测试时钟模拟最长 TTL 下连续 28 分钟每分钟创建并取消 20 次，证明其他来源仍可创建。硬上限测试证明仅淘汰最旧终态，活动记录不受影响；超容量时允许缩短终态 60 秒窗口，已清理记录返回 404，保留期内重复 consume 返回 409。持久化测试销毁并重建整个 Miniflare 运行时，验证 salt、来源集合、terminal_at、alarm、未过期申请及一次性领取状态。

新增仅测试 SQL 统计在完整消耗 cursor 后读取 rowsRead，包含冷启动构造 SQL；37 行递归查询校验统计没有只算第一行。接近限额样本以批量 SQL 写入 61,440 条 input rates、512 个来源、128 个活动和 512 个终态请求，测量整个 HTTP 请求：

| 请求 | rowsRead | SQL 调用数 | alarm 写入 |
| --- | ---: | ---: | ---: |
| 合法 input | 126 | 7 | 0 |
| 限流 input | 122 | 2 | 0 |
| 新来源拒绝 | 515 | 4 | 0 |
| 活动满额时拒绝创建 | 643 | 4 | 0 |
| 腾出一个活动名额后允许创建 | 772 | 11 | 0 |

未知 API 路由及不支持方法在外层 Worker 被拒绝，0 次 DO 访问、0 SQL；DO 也在访问 SQL 前拒绝。alarm 的三条 earliest 查询均使用对应索引，单条 rowsRead 不超过 1，无临时排序。全局 rates 批量清理仅在 alarm，input 请求仅清理当前来源的最多 120 条历史，以及最多 512 条来源集合项；不执行 COUNT DISTINCT 全事件扫描。合法请求的已存在更早 alarm 不推迟，较短 deadline 提前 alarm。

base64url 测试逐一拒绝 JWK n 与 wrapped_key、nonce、ciphertext 中的 `+`、`/`、`=`，覆盖合法余数、非法长度和合法 `-_`。额外实测 Python encode、skill crypto 副本、浏览器 b64 的 1,025 种字节长度，只产生无填充 URL-safe 格式。

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
