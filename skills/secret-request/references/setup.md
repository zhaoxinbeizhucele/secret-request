# 客户端初始化

`npx skills add` 只分发文件，首次使用由 Agent 运行本 skill 的 `scripts/install.py`。需要 Python 3.12+。不修改全局 AGENTS.md / CLAUDE.md。

## 选择中转方式

已有配置时优先复用。新用户未指定服务时使用默认公共服务 `https://secret-request.eicai.cc`，告知用户该选择；用户希望自建时提供下列选择，无需要求填写尚不存在的配置文件：

- 公共：`--mode public`（新安装省略参数也是公共服务）。
- 本机：`--mode local --port 8787`，无需 Docker、域名或部署，只能本机浏览器填写。
- 自建 HTTPS：`--mode custom --url https://relay.example.com`；部署方法见仓库 README 的“部署中转服务”。

默认只要求企微 webhook，本机通知关闭。复用已有的 `SECRET_REQUEST_WEBHOOK` 或用 `--webhook-env NAME` 指定其他变量名。没有可用 webhook 时，通过安全凭据申请流程交给本机配置程序，不让用户在聊天发送完整地址。配置程序可将 webhook 写入受保护的 `client.json` 的 `notifications.webhook.url`，并设置 type 为 wecom；不要输出地址。环境变量方式只写入变量名，客户端每次运行均需能读到该变量。

Windows：

```powershell
python -I "<skill目录>\scripts\install.py" --mode public --webhook-env SECRET_REQUEST_WEBHOOK
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --check-service
```

macOS / Linux：

```sh
python3 -I '<skill目录>/scripts/install.py' --mode public --webhook-env SECRET_REQUEST_WEBHOOK
~/.local/share/secret-request/secret-request --check-service
```

初始化后检查入口 `--help` 和 `--check-service`。ready 仅证明匿名服务连接，不创建申请、不发送群消息，不等于实际填写/执行已通过。失败时区别依赖缺失、网络、通知配置和服务协议问题，不重复申请凭据。

## 本机快速启动

执行安装器 `--mode local --port 8787`，在工具的后台进程会话运行安装器输出的 `secret-request-server`（Windows 为 `.cmd`）完整路径，追加 `--port 8787`。保留工具返回的会话 ID，检查同一进程；服务器启动后另开客户端执行 `--check-service`。

服务始终绑定 127.0.0.1，不依赖 Docker/证书。停止用同一会话 Ctrl+C，退出会使未交付申请失效。端口被占用时选择另一端口，并在安装和服务启动命令中保持一致。不要仅根据启动文字判断成功，必须检查 /health 或客户端 --check-service。

本机链接只能在同一电脑打开。企微桌面端可在该电脑浏览器打开；用户要手机填写时切换公共或可达的自建 HTTPS 服务，不要擅自暴露本机端口。

## 更新与兼容

`npx skills update` 后运行安装器更新环境/入口。省略模式与 URL 时保留原配置；显式指定另一服务会报错并保留旧配置。要并行使用另一模式，指定独立的 `--application-directory` 和 `--config-directory`，不要覆盖已有任务的配置。

`--local-notification` 可选择启用现有 Windows/macOS 通知；macOS 需要 --build-notifier 和 Apple Command Line Tools。当前主流程不依赖原生组件。旧通知配置会保留。0.2 的 request_token 会在升级时移除。

skill 路径变化或被删除会使命令入口失效，重新运行当前 skill 的安装器。安装服务仅适用于当前使用端；不要为了修复本机配置而重启已有中转服务。
