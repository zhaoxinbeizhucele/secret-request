# 客户端初始化

`npx skills add` 分发本 skill 的文件；它不会运行 `install.py`。首次使用时由 Agent 执行本节完成客户端初始化。用户要求安装或选择本工具完成任务，已覆盖本机客户端安装；依赖就绪时不要重复安装。

## 安装

从当前 `SKILL.md` 的实际位置取得 skill 目录，不写死 `.agents`、`.codex` 或 `.claude` 路径；复制和链接安装均支持。安装器使用隔离 Python 环境，入口会引用当前 skill 的脚本。

需要 Python 3.12+；Windows 可使用 `python` 或已有的 `py -3`，macOS / Linux 使用 `python3`。Python 不存在或版本太旧时，说明缺少的前置依赖，不要以系统错误冒充安装成功。

Windows：

```powershell
python -I "<skill目录>\scripts\install.py" --config-file "<管理员提供的设备配置文件>"
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --help
```

macOS / Linux：

```sh
python3 -I '<skill目录>/scripts/install.py' --config-file '<管理员提供的设备配置文件>'
~/.local/share/secret-request/secret-request --help
```

默认配置为 `~/.config/secret-request/client.json`。已有配置时省略 `--config-file`，保留其认证和通知设置。导入同一文件可以重复执行；不同的已有配置会报错并保留原文件。安装器不输出配置内容，导入前验证结构和 HTTPS 服务地址，并限制新配置的读取权限。

配置由服务管理员提供，每台设备使用自己的配置。没有配置时只向用户确认服务来源和配置文件位置，不让用户把 token 或 webhook 地址粘贴到聊天。不要自行生成未经服务器登记的 token。使用既有中转服务无需部署或重启服务器。

Windows 分发包已带 win-x64 通知组件。macOS 本机通知需要 Apple Command Line Tools，安装时加 `--build-notifier`；如果只使用 webhook，可省略构建。本版 Linux 使用 webhook。配置和申请机密均不随 skill 分发。

## 验证与升级

先检查安装命令成功、入口 `--help` 可运行及设备配置文件存在，再发起用户已授权任务的申请。通知不支持、权限被禁止和发送失败要如实报告；测试用虚构值。真实群 webhook 的验收由用户发起，不在初始化时自动向群发送测试消息。

`npx skills update` 更新 skill 文件。升级后运行当前 skill 的安装器，使依赖与入口同步；不会覆盖已有设备配置。移动或移除 skill 后，命令入口可能失效，重新安装当前 skill 即可。

`--application-directory` 和 `--config-directory` 可选择独立的运行与配置目录，适合测试或单独配置；生成的入口会使用对应配置目录。它们不是中转服务部署参数。
