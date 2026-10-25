# Secret Request

让机密走自己的通道。Agent 发起申请，企微通知本人，浏览器加密填写，本机客户端解密后直接交给任务程序。聊天里只返回状态和退出码。

官网与默认公共中转：**https://sr.eicai.cc**。服务无需账号、设备登记或长期接入 token；也可以在本机运行，或部署自己的 HTTPS 中转。

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
| 默认 / `--mode public` | 使用 `https://sr.eicai.cc`，无需部署 |
| `--mode local` | 使用 `http://127.0.0.1:8787`，由 Agent 启动本机服务器 |
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

本机通知默认开启，配置企微后同时发送本机通知和企微 webhook；配置一个渠道不会关闭另一个。`--configure-wecom` 不依赖已有通知渠道：公共/自建模式使用当前选中的中转并打开一次性填写页，本机模式临时启动 loopback 配置页。提交后地址保存到受保护的本机配置；拒绝或过期保留原配置，不发送群消息。没有桌面浏览器时可直接运行 `scripts/setup_wecom.py --config <client.json> --no-open` 获得填写链接；loopback 链接仍仅限同电脑。填写后通过原工具进程状态确认 `wecom_configured`，不要要求用户回聊天确认。已有 `SECRET_REQUEST_WEBHOOK` 时，新安装自动引用；也可用 `--webhook-env` 指定其他变量名。变量需在客户端进程环境中可用。仅将变量名写入配置，完整 webhook 不进入日志或仓库。更新时保留已保存的通知设置。

Windows/macOS 可通过 `--no-local-notification` 显式关闭本机通知，或通过 `--local-notification` 重新开启；已配置的 webhook 不受影响，后续更新和配置企微均保留已有选择。macOS 需 Apple Command Line Tools 和 `--build-notifier`。Linux 本机通知返回 unsupported，使用已配置的 webhook。通用 JSON webhook 仍然可用，当前主流程只要求企微。

### 本机快速启动

不需要 Docker、域名、证书或外部部署。让 Agent 执行：

```sh
python3 -I '<skill目录>/scripts/install.py' --mode local --port 8787
```

安装器生成两个命令入口。Windows 用 `%LOCALAPPDATA%\Programs\SecretRequest\secret-request-server.cmd`，macOS/Linux 用 `~/.local/share/secret-request/secret-request-server`。

让 Agent 在一个可后台运行的工具会话中启动服务器，保留该会话，随后另开客户端命令：

```sh
secret-request-server --port 8787
secret-request --check-service
```

入口未加入 PATH 时使用安装器输出的完整路径。服务器只绑定 `127.0.0.1`，Ctrl+C 即停止；终端关闭/进程停止后需重新启动。端口冲突时选择另一端口，并在初始化和启动时使用同一端口。浏览器在 loopback HTTP 上可使用 WebCrypto；客户端仅对 loopback 允许 HTTP。

**本机链接只能在同一台电脑打开。** 企微桌面端可在该电脑的浏览器打开；手机填写请选公共服务或可达的自建 HTTPS 服务。本机初始化不会自动对局域网或公网开放。

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

22 个字符对应 128 位（`token_urlsafe(16)`）。在当前公共服务域名上是 44 个字符，例如 `https://sr.eicai.cc/i#` 再加 22 个字符。申请 ID 不放进链接。服务只保存填写凭据的 SHA-256，并按这个哈希查找申请。填写页带着同一凭据调用 `GET /api/input`，取回申请 ID 和公钥；AES-GCM 的附加数据仍是 `secret-request:v1:` 加上该 ID。领取凭据仍是 256 位，不出现在链接里。一次性提交、最长 30 分钟、撤销和创建频率限制不变，也不新增必填服务配置。可选配置是填写页查询频率 `input_lookups_per_minute`（环境变量 `SECRET_REQUEST_INPUT_LOOKUPS_PER_MINUTE`，默认每来源每分钟 120 次，范围 1–1024）。

首页若带上同样的 22 字符片段，会转到 `/i`，避免凭据留在介绍页。客户端和本机通知程序只接受 `/i#` 这一种链接。仓库里的 Windows 通知程序二进制仍是旧构建，需要在 Windows 上重新编译后才会打开这种链接。

默认等待 600 秒。提交确认后尝试关页，不能自动关闭时显示手动关闭提示。拒绝、取消或过期不执行任务。默认建立空闲 300 秒的本机会话，合法执行结束后重新计时；状态查询不续期。

```sh
secret-request --use-session '<handle>' -- python query.py
secret-request --session-status '<handle>' --execution-id '<execution_id>'
secret-request --revoke-session '<handle>'
```

同一会话固定首次工作目录和交付方式，一次运行一个程序。任务结束后主动撤销；`--one-shot` 可不创建会话。Ctrl+C 停止本次任务并撤销本次会话，已完成任务保留真实退出码。状态未知时按原执行 ID 查询，不自动重跑可能已执行的写操作。撤销不回滚业务副作用。

## 部署中转服务

镜像：`ghcr.io/zhaoxinbeizhucele/secret-request`，由 GitHub Actions 在测试通过后构建 Linux amd64/arm64。`latest` 对应 main；生产可固定 `sha-<完整提交ID>` 或镜像 digest。拉取公开镜像无需 GitHub 登录。

### 新服务器：Compose 自动 HTTPS

准备解析到主机的域名，允许 TCP 80/443 入站，安装 Docker Compose v2，然后：

```sh
git clone https://github.com/zhaoxinbeizhucele/secret-request.git
cd secret-request/deploy
cp public.env.example .env
# 将 .env 的 SECRET_REQUEST_DOMAIN 改成自己的域名
docker compose --env-file .env -f compose.public.yaml up -d
```

Caddy 自动申请/续期 HTTPS 证书。relay 不发布宿主端口，仅 Caddy 发布 80/443；证书保存在命名卷。域名和实际入口必须一致。查看状态：

```sh
docker compose --env-file .env -f compose.public.yaml ps
curl --fail https://your-domain.example/health
```

### 已有 Nginx / HTTPS 入口

使用同一 `.env` 和 `compose.proxy.yaml`，relay 默认仅发布 `127.0.0.1:8787`：

```sh
docker compose --env-file .env -f compose.proxy.yaml up -d
```

按 `deploy/nginx.conf.example` 配置独立站点与证书。代理必须用真实连接来源覆盖 `X-Forwarded-For`，不可透传公网任意转发头；此 Compose 才会信任 host proxy。不要将该 relay 端口改为公网监听。若前面还有 CDN，先配置可信 CDN 地址范围再恢复真实 IP。

两个 Compose 文件是替代方案，不要叠加。默认专用网段分别为 172.30.80.0/29 和 172.30.81.0/29；若与现有网络冲突，在 .env 设置 RELAY_SUBNET，并同步修改对应的 RELAY_PROXY_ADDRESS（Caddy）或 RELAY_GATEWAY（主机反代）。转发头信任仅限指定代理地址。单 worker、内存状态；不横向扩容共享申请。默认最多 128 个在途申请、每来源 8 个、每来源每分钟 20 次、全局每分钟 120 次、填写页 `/api/input` 每来源每分钟 120 次。使用 `SECRET_REQUEST_MAX_REQUESTS`、`SECRET_REQUEST_MAX_REQUESTS_PER_IP`、`SECRET_REQUEST_REQUESTS_PER_MINUTE`、`SECRET_REQUEST_GLOBAL_REQUESTS_PER_MINUTE`、`SECRET_REQUEST_INPUT_LOOKUPS_PER_MINUTE` 可调整，各项 1–1024。代理有请求体和读写超时限制，应用也有 100000 字节与 15 秒请求体读取限制。

停止服务用对应的 `docker compose ... down`；未交付申请随重启失效，已领取的本机会话不受影响。保留旧镜像 digest 和 Compose 环境即可回退。不要删除 Caddy 证书卷来更新服务。

旧版 `deploy/compose.yaml` 和 JSON 配置继续支持已有私网部署。源码打包按允许清单，只包含明确文件；GNU tar 可按归档权限解压。Python 的通用 `filter='data'` 不保留目录模式，严格 umask 环境使用 `python scripts/extract_deploy.py artifacts/server.tar.gz new-directory`；目标目录必须不存在。

## 隐私与信任边界

- 浏览器用 RSA-OAEP/SHA-256 包装 AES-256-GCM 密钥，并绑定申请 ID；私钥留在发起电脑。正常服务只能接触密文。
- 仍需信任提供网页的服务。被篡改的网页可在加密前访问输入；本机完整权限程序也不受隔离。
- 无登录、申请总列表或历史数据库。匿名不代表隐藏 IP；来源 IP 仅以随机盐哈希暂存在进程内用于限流。
- 填写/拒绝与领取使用独立随机凭据。填写链接持有者可以处理申请，发到群里意味着群成员都可能填写或拒绝。
- 领取一次后移除密文；领取响应丢失不能重复领取。终态元数据在截止后 10 分钟删除。重启不恢复申请。
- 公共服务是共享的尽力服务，无可用性承诺；需要独立控制时自建。不承诺擦除所有内存、交换文件或转储副本。

## 开发

```sh
python -m pytest -q
python -I scripts/build_skill.py
python -I scripts/package_client.py
python -I scripts/package_deploy.py
```

客户端或服务器/网页变更后，重新生成 skill 中的本机运行副本。GitHub Actions 测试通过后推送 GHCR 镜像；构建成功、部署成功、真实用户验收分别核对。历史验证见 `TEST-REPORT.md`，本轮验证见 `docs/public-service.md`。
