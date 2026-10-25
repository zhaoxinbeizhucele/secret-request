# 客户端初始化

`npx skills add` 只分发文件，首次使用由 Agent 运行本 skill 的 `scripts/install.py`。需要 Python 3.12+。不修改全局 AGENTS.md / CLAUDE.md。

## 选择中转方式

已有配置时优先复用。新用户未指定服务时使用默认公共服务 `https://sr.eicai.cc`，告知用户该选择；用户希望自建时提供下列选择，无需要求填写尚不存在的配置文件：

- 公共：`--mode public`（新安装省略参数也是公共服务）。
- 本机：`--mode local --port 8787`，无需 Docker、域名或部署，只能本机浏览器填写。
- 自建 HTTPS：`--mode custom --url https://relay.example.com`；部署方法见仓库 README 的“部署中转服务”。

本机通知默认开启，配置企微 webhook 后同时发送两个渠道；配置一个渠道不会关闭另一个。用户显式关闭的选择在后续配置和更新时保留。复用已有的 `SECRET_REQUEST_WEBHOOK` 或用 `--webhook-env NAME` 指定其他变量名。没有可用 webhook 时，在安装命令增加 `--configure-wecom`。它使用选定的中转打开一次性加密填写页，地址只通过 stdin 交给本机配置程序并保存在受保护配置中；本机模式会临时拉起仅 loopback 的配置页，无需事先启动服务器。没有浏览器时直接用独立运行环境的 Python 执行 `scripts/setup_wecom.py --config <client.json> --no-open`，把填写链接提供给用户（本机链接仅同电脑可用）。此入口专用于首次配置，无需先有可用通知渠道。拒绝/过期不覆盖原配置；保存不发送群消息。不要让用户在聊天发送完整地址，也不要要求用户回聊天说填完了，继续跟踪同一工具会话，直到 wecom_configured 或明确失败。环境变量方式只写入变量名，客户端每次运行均需能读到该变量。

Windows：

```powershell
python -I "<skill目录>\scripts\install.py" --mode public --configure-wecom
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --check-service
```

macOS / Linux：

```sh
python3 -I '<skill目录>/scripts/install.py' --mode public --configure-wecom
~/.local/share/secret-request/secret-request --check-service
```

初始化后检查入口 `--help` 和 `--check-service`。ready 仅证明匿名服务连接，不创建申请、不发送群消息，不等于实际填写/执行已通过。失败时区别依赖缺失、网络、通知配置和服务协议问题，不重复申请凭据。

## 本机快速启动

执行安装器 `--mode local --port 8787`，在工具的后台进程会话运行安装器输出的 `secret-request-server`（Windows 为 `.cmd`）完整路径，追加 `--port 8787`。保留工具返回的会话 ID，检查同一进程；服务器启动后另开客户端执行 `--check-service`。

服务始终绑定 127.0.0.1，不依赖 Docker/证书。停止用同一会话 Ctrl+C，退出会使未交付申请失效。端口被占用时选择另一端口，并在安装和服务启动命令中保持一致。不要仅根据启动文字判断成功，必须检查 /health 或客户端 --check-service。

本机链接只能在同一电脑打开。企微桌面端可在该电脑浏览器打开；用户要手机填写时切换公共或可达的自建 HTTPS 服务，不要擅自暴露本机端口。

## 更新与兼容

`npx skills update` 后运行安装器更新环境/入口。省略模式与 URL 时保留原配置；显式指定另一服务会报错并保留旧配置。要并行使用另一模式，指定独立的 `--application-directory` 和 `--config-directory`，不要覆盖已有任务的配置。

`--no-local-notification` 可显式关闭 Windows/macOS 本机通知，`--local-notification` 可重新开启；这两个选项均不修改已配置的 webhook。填写链接只有 `/i#<22 字符凭据>`。Windows 通知程序已随包提供，能打开这种链接。macOS 没有随包二进制，需要 Apple Command Line Tools，并用 `--build-notifier` 或 `python3 scripts/build_native.py` 在本机编译。Linux 本机通知返回 unsupported，使用已配置的 webhook。已有通知设置会保留。含 `request_token` 的配置无效，安装器不会改写它。

skill 路径变化或被删除会使命令入口失效，重新运行当前 skill 的安装器。安装服务仅适用于当前使用端；不要为了修复本机配置而重启已有中转服务。
