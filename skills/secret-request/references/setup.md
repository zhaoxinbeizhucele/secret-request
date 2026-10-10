# 客户端初始化

匿名中转只需要服务 URL，不需要登录、设备登记、配对码、长期 token 或管理员提供的配置文件。`npx skills add` 只分发 skill 文件；首次使用时由 Agent 运行本节安装器，自动生成本机配置。

本项目安装器不修改全局 `AGENTS.md`、`CLAUDE.md` 或其他 Agent 指令文件，也不要求用户手工添加规则。主动使用由宿主 Agent 发现并选择本技能；触发条件写在 `SKILL.md` 的 description 与正文中。新安装或更新后，按宿主要求刷新技能或开启新会话；不能把客户端初始化成功等同于宿主已加载新版技能。

## 首次使用

1. 从当前 `SKILL.md` 的实际位置找到 `scripts/install.py`，兼容复制和链接安装。
2. 检查 Python 3.12+。如果没有可用的现有配置和用户已提供的地址，只询问“使用哪个中转服务 URL？”。不要要求用户寻找尚不存在的 client.json，也不要从旧项目、备份或其他设备复制认证。
3. 确认通知方式：Windows/macOS 可使用本机通知；webhook 使用已有环境变量名，完整 webhook 地址不要粘贴到聊天。Linux 使用 webhook，本版没有 Linux 本机通知组件。
4. 运行安装器，再检查入口和服务连接。示例 URL 不是可用服务，必须换成用户选择的 HTTPS 地址。

Windows：

```powershell
python -I "<skill目录>\scripts\install.py" --url "https://your-relay.example"
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --help
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --check-service
```

macOS / Linux：

```sh
python3 -I '<skill目录>/scripts/install.py' --url 'https://your-relay.example'
~/.local/share/secret-request/secret-request --help
~/.local/share/secret-request/secret-request --check-service
```

默认使用本机通知。只使用企微 webhook 时，在安装命令增加 `--no-local-notification --webhook-type wecom --webhook-env SECRET_REQUEST_WEBHOOK`，其中变量需在运行客户端的环境里存在。通用 JSON 接收端使用 `--webhook-type generic`。可同时启用本机通知和 webhook；缺少 webhook 配置时只说明设置方法，不自动发送真实群消息。

Windows 包含 win-x64 通知组件，无需 .NET。macOS 本机通知需要 Apple Command Line Tools，初始化增加 `--build-notifier`；只有 webhook 时可省略。

安装器自动保存 `~/.config/secret-request/client.json`，内容为服务 URL 和通知设置，并保护文件权限。同一服务可重复初始化；已有配置时可省略 `--url`。已有其他服务地址时报错并保留原配置，需要分开使用时指定独立配置目录。

## 验证和升级

`--check-service` 只发健康检查，不创建申请、不通知。`ready` 表示匿名服务可连通；旧版服务返回 `incompatible_service`，应让部署者升级服务。网络失败、私网不可达与本机依赖缺失要分别报告，不能把入口存在当成整条流程已通过。实际通知、网页填写和任务执行留到用户授权的申请中验证。

`npx skills update` 后运行当前 skill 的安装器更新环境和入口。0.2 配置会在初始化时保留 URL、通知设置并移除废弃的 request_token；新用户不需要这份旧配置。服务端需先升级到支持匿名接入的 0.3。不要替用户重建或重启已有服务器来修复本机安装问题。

`--application-directory` 和 `--config-directory` 可选择独立的运行与配置目录，适合隔离测试。移动或删除 skill 会使命令入口引用失效，重新运行当前 skill 的安装器修复入口。
