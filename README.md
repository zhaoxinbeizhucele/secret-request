# Secret Request

让机密走自己的通道。Agent 发起申请，企微通知本人，浏览器加密填写，本机客户端解密后直接交给任务程序。聊天里只返回状态和退出码。

官网与默认公共中转：**https://sr.zhaox.app**。服务无需账号、设备登记或长期接入 token；也可以部署自己的 Cloudflare Worker。此地址是代码默认目标，本分支尚未部署。

## 添加到 Agent

```sh
npx skills add zhaoxinbeizhucele/secret-request -g
```

安装后开启新会话，告诉 Agent：

> 初始化 secret-request，使用默认公共服务，通过企微 webhook 通知我。

`npx skills add` 只分发文件，不会执行安装器。Agent 会建立独立 Python 环境、生成配置并检查连接。需要 Node.js 22.20+ 和 Python 3.12+。完整企微 webhook 属于机密。没有现成环境变量时，安装命令加 `--configure-wecom`，会打开加密填写网页并交给本机配置程序；也可复用已存在的 `SECRET_REQUEST_WEBHOOK` 环境变量，不要粘贴进聊天。

首次初始化可选择：

| 模式 | 行为 |
| --- | --- |
| 默认 / `--mode public` | 使用 `https://sr.zhaox.app`，无需部署 |
| `--mode custom --url https://relay.example.com` | 使用自己部署的 HTTPS 服务 |

已有配置的更新保留原地址和通知设置，省略模式不会切到公共服务。显式指定另一地址会报错并保留原配置；并行使用其他服务时，指定独立 `--application-directory` 和 `--config-directory`。

### 公共服务初始化

Windows（`<skill目录>` 为当前安装位置）：

```powershell
python -I "<skill目录>\scripts\install.py" --mode public --configure-wecom
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --check-service
```

macOS / Linux：

```sh
python3 -I '<skill目录>/scripts/install.py' --mode public --configure-wecom
~/.local/share/secret-request/secret-request --check-service
```

本机通知默认开启，配置企微后同时发送本机通知和企微 webhook；配置一个渠道不会关闭另一个。`--configure-wecom` 不依赖已有通知渠道：使用当前选中的 Worker 并打开一次性加密填写页。提交后地址保存到受保护的本机配置；拒绝或过期保留原配置，不发送群消息。没有桌面浏览器时可直接运行 `scripts/setup_wecom.py --config <client.json> --no-open` 获得填写链接。填写后通过原工具进程状态确认 `wecom_configured`，不要要求用户回聊天确认。已有 `SECRET_REQUEST_WEBHOOK` 时，新安装自动引用；也可用 `--webhook-env` 指定其他变量名。变量需在客户端进程环境中可用。仅将变量名写入配置，完整 webhook 不进入日志或仓库。更新时保留已保存的通知设置。

Windows/macOS 可通过 `--no-local-notification` 显式关闭本机通知，或通过 `--local-notification` 重新开启；已配置的 webhook 不受影响，后续更新和配置企微均保留已有选择。macOS 需 Apple Command Line Tools 和 `--build-notifier`。Linux 本机通知返回 unsupported，使用已配置的 webhook。通用 JSON webhook 仍然可用，当前主流程只要求企微。

## 使用

先准备只将机密用于当前授权任务的程序，再发起申请：

```sh
secret-request --agent-name Codex --name "测试库登录" --purpose "查询已授权的测试库结构" --fields-file fields.json -- python query.py
```

`fields.json` 仅定义字段，不放输入值：

```json
[
  {"id":"username","label":"用户名","type":"text"},
  {"id":"password","label":"密码","type":"password"}
]
```

支持 1–16 个 text/password/textarea/email/url 字段。默认必填。多字段交付完整 JSON，单字段不指定文件时交付原始字符串。通过 UTF-8 stdin 交付，无额外换行；`--env NAME` 可放入子进程环境。输入上限 64 KiB。程序 stdout/stderr 不返回给 Agent，需要结果时只保存非敏感业务结果。

企微消息只包含名称、用途和本次填写链接；webhook 由客户端调用，服务不保存或调用 webhook。失败最多重试一次，使用同一申请。发送成功不等于用户已处理。没有通知配置时，仅在明确需要备用链接时用 `--show-link`。

### 填写链接

中转只发出这一种填写链接：

`https://<服务>/i#<22 字符填写凭据>`

22 个字符对应 128 位（`token_urlsafe(16)`）。在默认公共服务域名上是 45 个字符，例如 `https://sr.zhaox.app/i#` 再加 22 个字符。申请 ID 不放进链接。服务只保存填写凭据的 SHA-256，并按这个哈希查找申请。填写页带着同一凭据调用 `GET /api/input`，取回申请 ID 和公钥；AES-GCM 的附加数据仍是 `secret-request:v1:` 加上该 ID。领取凭据仍是 256 位，不出现在链接里。一次性提交、最长 30 分钟、撤销和创建频率限制不变，也不新增必填服务配置。Worker 固定填写页查询频率为每来源每分钟 120 次。

客户端和本机通知程序只接受 `/i#` 这一种链接。Windows 通知程序已随仓库提供，能打开这种链接。macOS 没有随包二进制，需要在本机用 `--build-notifier` 或 `python3 scripts/build_native.py` 编译。

默认等待 600 秒。提交确认后尝试关页，不能自动关闭时显示手动关闭提示。拒绝、取消或过期不执行任务。默认建立空闲 300 秒的本机会话，合法执行结束后重新计时；状态查询不续期。

```sh
secret-request --use-session '<handle>' -- python query.py
secret-request --session-status '<handle>' --execution-id '<execution_id>'
secret-request --revoke-session '<handle>'
```

同一会话固定首次工作目录和交付方式，一次运行一个程序。任务结束后主动撤销；`--one-shot` 可不创建会话。Ctrl+C 停止本次任务并撤销本次会话，已完成任务保留真实退出码。状态未知时按原执行 ID 查询，不自动重跑可能已执行的写操作。撤销不回滚业务副作用。

## 部署中转服务

公共部署只使用 Cloudflare Workers + 一个 SQLite Durable Object。静态网页随 Worker 打包。部署资源、最小权限及域名步骤见 [DEPLOY.md](DEPLOY.md)。Python 仅负责客户端、通知和本机任务会话。

默认域名为 `https://sr.zhaox.app`，是代码配置目标，不代表本分支已上线。部署、域名和 DNS 变更须另行授权。已有客户端仅需在用户授权后更改 base URL；本次代码修改不更新实际客户端配置。

## 隐私与信任边界

- 浏览器用 RSA-OAEP/SHA-256 包装 AES-256-GCM 密钥，并绑定申请 ID；私钥留在发起电脑。正常服务只能接触密文。
- 仍需信任提供网页的服务。被篡改的网页可在加密前访问输入；本机完整权限程序也不受隔离。
- 无登录或申请总列表。Worker 以随机盐哈希来源 IP，并将请求、凭据 SHA-256 索引、密文及短期限流数据存入单个 SQLite Durable Object；盐也持久化。来源仅信任平台提供的 CF-Connecting-IP，不信任 X-Forwarded-For。
- 填写/拒绝与领取使用独立随机凭据。填写链接持有者可以处理申请，发到群里意味着群成员都可能填写或拒绝。
- 领取一次后移除密文；领取响应丢失不能重复领取。终态元数据在截止后 10 分钟删除。Worker 重启后保留未过期申请。alarm 到期清除密文，截止后 10 分钟删除请求和索引，限流记录保留最多 60 秒；alarm 延迟时，下次请求也会执行清理。
- 公共服务是共享的尽力服务，无可用性承诺；需要独立控制时自建。应用清理不保证 Cloudflare 平台备份或恢复副本立即擦除，也不承诺擦除所有内存、交换文件或转储副本。

## 开发

```sh
npm ci
python -m pip install -r requirements.txt pytest pytest-asyncio playwright
python -m playwright install chromium
python -I scripts/build_skill.py
npm test
npm run typecheck
npm run dry-run
python -m pytest -q
python -I scripts/e2e_worker.py
python -I scripts/package_client.py
```

客户端变更后重新生成 skill 中的客户端副本；网页由 Worker 直接打包。GitHub Actions 只测试，不发布或部署。构建通过、部署生效和真实用户验收分别核对。本地浏览器 E2E：`python -I scripts/e2e_worker.py`（安装 Playwright 与 Chromium 后运行），只连接独立的本地 Wrangler，使用合成值且不发送通知。结果见 `TEST-REPORT.md`。
