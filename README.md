# Secret Request 0.2

Agent 发起申请，用户点击通知在网页填写，客户端取回密文并在本地交给任务程序。支持 Windows、macOS 本机通知和客户端 webhook。应用按需运行；同一份程序可以连接自部署服务或受信任的共享服务。

```mermaid
sequenceDiagram
    participant A as Agent
    participant C as 本地客户端
    participant R as 中转服务
    participant U as 用户浏览器
    A->>C: 名称、用途、字段、任务程序
    C->>R: 创建申请和公钥
    R-->>C: 单条填写链接、领取凭据
    C->>U: 本机通知或 webhook 链接
    U->>R: 浏览器加密后提交
    C->>R: 等待自己的申请、一次取回
    R-->>C: 密文
    C->>C: 解密、执行、短期复用
    C-->>A: 会话状态、退出码
```

## 安装客户端

使用端支持标准的 [`npx skills`](https://github.com/vercel-labs/skills) 分发。完整 skill 位于 `skills/secret-request`，包含客户端、安装器及通知组件；服务端仍独立部署。

从 GitHub 安装到 Codex：

```powershell
npx skills add zhaoxinbeizhucele/secret-request --skill secret-request -g -a codex -y
```

Claude Code：

```sh
npx skills add zhaoxinbeizhucele/secret-request --skill secret-request -g -a claude-code -y
```

也可以用 `-a codex claude-code` 同时安装到两者。需要项目内安装时省略 `-g`，需要独立副本时加 `--copy`。本地开发可将来源替换为 `./`；Windows 的本地来源使用 `/`，例如 `./skills`，不要把 `.\skills` 误当成 Git 来源。

`npx skills` 安装 skill 文件，不执行应用安装脚本。安装后在新会话要求 Agent 初始化客户端；Agent 根据 skill 内的 [安装指引](skills/secret-request/references/setup.md) 建立独立运行环境，导入设备配置，然后使用工具。需要 Node.js 22.20+ 运行当前 Skills CLI、Python 3.12+ 运行客户端。客户端不需要配置中转服务的 Docker。

也可以手动初始化。以下 `<skill目录>` 指当前安装的 skill 位置，适用于 Codex、Claude Code 的复制或链接安装。设备配置由服务管理员提供：

Windows：

```powershell
python -I "<skill目录>\scripts\install.py" --config-file "<设备配置文件路径>"
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --help
```

macOS / Linux：

```sh
python3 -I '<skill目录>/scripts/install.py' --config-file '<设备配置文件路径>'
~/.local/share/secret-request/secret-request --help
```

安装器建立独立 Python 环境和命令入口。新设备可通过 `--config-file` 导入配置，导入时验证格式、保护文件权限，不覆盖已有配置，也不打印凭据；已有配置时省略该参数。需要短命令时自行把入口目录加入 PATH。Windows 分发包携带已构建的通知组件，目标机无需 .NET；macOS 安装本机通知组件需 Apple Command Line Tools，再执行安装器的 `--build-notifier`。只有 webhook 时不必构建本机组件。Linux 使用 webhook，本机通知暂未实现。

更新 skill 用 `npx skills update`，然后运行其安装器更新依赖和入口，设备认证继续沿用。用户自行解压安装时也可使用 `artifacts/secret-request-client.zip`，其中不含设备配置；当前 Windows 组件使解压体积超过 Skills CLI 的直接下载默认上限，`npx skills` 分发采用 Git 或本地目录来源。

设备配置是私有文件，不进入 skill、分发包或 Git 仓库。每位用户应从所使用的服务管理员取得自己设备的配置；更新或重新安装时沿用原配置。

开发者可运行 `python scripts/build_native.py` 构建当前系统组件；Windows 构建需要 .NET 10 SDK。通知组件没有菜单、托盘或开机启动项，Windows 发送后退出；macOS 等待本条通知点击或到期，申请结束时客户端会回收它。

## 客户端配置

将服务管理员提供的、属于该设备的 `client.json` 放到 `~/.config/secret-request/client.json`，仅本人可读。下面均为示例，不是有效的服务凭据：

```json
{
  "url":"https://your-relay.example",
  "request_token":"REPLACE_WITH_YOUR_DEVICE_TOKEN",
  "notifications":{
    "local":true,
    "webhook":{
      "type":"wecom",
      "url_env":"SECRET_REQUEST_WEBHOOK"
    }
  }
}
```

企微的环境变量值是群机器人的完整 webhook 地址，属于敏感配置，不进入聊天或仓库。也可以在受保护配置中使用 `url`；`url` 和 `url_env` 二选一。本机通知与 webhook 可同时开启，默认启用本机通知。

通用 webhook 使用 `type: generic`，可附带 `headers`，接收 JSON：`event`、`request_id`、`title`、`message`、`input_url`、`expires_in_seconds`。它是约定格式，不承诺兼容任意消息平台。客户端只发送填写链接，不发送领取凭据、公钥或用户输入；中转服务不保存或调用 webhook。发送失败最多重试一次，始终使用同一条申请和链接。

Windows / macOS 需要登录桌面并允许通知。macOS 首次运行可能询问权限。没有桌面、通知被禁止或组件未安装时，渠道报告 failed/unsupported；配置 webhook 或明确使用 `--show-link` 取得备用填写链接。接收到消息不代表用户已经看到或处理。

## 使用

先准备并检查任务程序，再申请。多字段定义只含非敏感的 ID、标签、类型和必填标记：

```json
[
  {"id":"username","label":"用户名","type":"text"},
  {"id":"password","label":"密码","type":"password"}
]
```

```sh
secret-request --agent-name Codex --name "测试库登录" --purpose "查询已授权测试库结构" --fields-file fields.json -- python query.py
```

1–16 个字段，类型支持 text、password、textarea、email、url，required 默认 true。整个 JSON 对象经 stdin 或一个指定的环境变量交给程序。单字段不指定 fields-file 时收到原始字符串。stdin 为 UTF-8，无额外换行；内容上限 64 KiB。指定 `--env NAME` 会放入子进程环境，父进程环境不变。

客户端只等待本次申请，默认 600 秒，`--wait` 可设 10–1800 秒。等待期间报告通知渠道状态。用户可以提交或拒绝，终态不能再次填写。浏览器先加密、清空输入，服务确认提交后尝试关闭页面；禁止自动关闭时显示手动关闭提示。断网重试复用加密数据，不提前关闭。

解密后默认创建可复用会话，输出句柄，再执行任务。程序 stdout/stderr 不回传给 Agent；退出码和必要的非敏感业务结果用于判断成功。`--execution-timeout` 默认 300 秒，允许 1–3600 秒；程序结束、超时、撤销时清理其进程组/Windows Job，不用于启动常驻服务。

```sh
secret-request --use-session '<handle>' -- python query.py
secret-request --session-status '<handle>'
secret-request --revoke-session '<handle>'
```

会话默认空闲 5 分钟过期，`--session-ttl` 可设 10–1800 秒。合法执行运行中不因空闲过期，执行结束后重新计时；状态查询、无效、重复、busy 调用不续期。运行中 status 的 expires_at 和 remaining_seconds 为 null。首次工作目录、输入方式固定，最多一次并发执行；复用不再发送通知或申请。任务完成后应主动撤销。`--one-shot` 不创建复用后台。

每个用户最多 16 个机密会话后台，用操作系统锁限制，无凭据或句柄文件。每个会话最多 256 次执行。随机句柄有使用权限，不能分享；固定目录不是沙箱。断线后先核对执行 ID 和业务结果，不自动重复未知结果的写操作。重启电脑或会话后台退出后机密无法恢复。

## 部署中转服务

安装 `requirements.txt` 中依赖。生成新配置时必须使用不存在的输出目录，脚本拒绝覆盖和隐式轮换：

```sh
python scripts/provision.py --url https://your-relay.example --device laptop --device workstation --output runtime
docker compose -f deploy/compose.yaml up -d --build relay
```

每台设备只分发其自己的 client.json，服务保留 relay.json。Docker 仅绑定 127.0.0.1:8787；用可信 HTTPS 反向代理或 Tailscale Serve 暴露，并使配置 base_url 与实际浏览器入口一致。公开源码不会自动部署中转服务，也不会改变现有服务的访问范围。

服务只支持单 worker。密文及申请存在内存，不建历史数据库；重启使未交付申请失效，但已取回的本机会话不依赖服务。默认最多 128 条在途申请，每个设备最多 8 条、每分钟创建 20 条，可在 relay.json 调整。已结束的元数据短期保留用于状态查询，到申请截止时间后 10 分钟删除，总量也有限制。

本版无登录和全局列表。创建需设备凭据；填写/拒绝与状态/取消/领取使用互相独立的单条随机凭据。服务只保留其哈希，不提供申请枚举入口。填写链接持有者有处理权限：发到群里意味着群成员也可以填写或拒绝，不能据此领取输入。领取为一次性，响应丢失不能再次领取，应核对后重新申请。

浏览器采用 RSA-OAEP/SHA-256 包装 AES-256-GCM 密钥并绑定请求 ID；私钥留在发起电脑。正常服务只拿到密文。用户仍需信任提供网页的服务：被篡改的网页可以在加密前访问输入；本机完整权限的程序也不受隔离。工具不长期保存输入，但不能承诺擦除所有内存、交换文件或转储副本。

## 开发与打包

```sh
python -m pytest -q
python scripts/build_skill.py
python scripts/package_client.py
python scripts/package_deploy.py
```

客户端变更后重新生成 skill 再分发。服务器包排除配置、测试端点和本机通知二进制。验证范围和人工验收见 [TEST-REPORT.md](TEST-REPORT.md)。

0.1 升级到 0.2 是不兼容重构：relay.json 只保留 base_url、clients 及新限额配置；客户端 token 可以沿用。旧 reviewer、ntfy、全局列表、托盘和开机启动项退役；旧服务不能与新客户端混用。已有历史数据库不再被读取，处理其旧备份属于部署迁移步骤。
