---
name: secret-request
description: 当执行用户已授权的任务，确实缺少密码、API Key、Token、私钥或需要用户补充登录凭据时，主动使用此技能，无需用户点名；不要让用户把机密粘贴到聊天。发送本机或已配置的 webhook 通知，让用户在网页填写，再交给本地任务程序使用。也用于客户端初始化、更新和通知配置。已有可用认证或同一任务的有效机密会话时优先复用；普通登录说明、示例代码、网络或权限错误不应直接触发机密申请。
---

发起申请前，准备并检查使用机密的任务程序、工作目录和非敏感结果路径。已有可用认证时直接使用；不要为查看凭据而重新索取。申请名称、用途、Agent 名称和字段定义会出现在网页或通知里，不要包含机密。

## 主动使用的时机

- 在已授权的实际任务中确认缺少机密时，主动进入本流程，不要等用户说“使用 secret-request”，也不要先让用户在聊天提供密码、Token 或带机密的命令。服务和通知已配置时，简短说明将通过网页申请，然后直接发起；不要另问一次“要不要发通知”。用户明确限制通知或拒绝申请时遵从其选择。
- 例如：用户要求调用某个 API，但所需 API Key 未配置；要求连接指定数据库，但没有可用登录凭据；要求使用一个已过期且无法正常刷新的 Token。用户名与密码等同时缺少的字段合并为一条申请，只申请当前任务需要的信息。
- 先利用任务上下文中已知的认证方式或有效会话。检查配置是否可用时不输出机密值；认证失败先判断是否为网络、服务地址、权限或配置问题，不把所有 401/403 或连接失败都解释为需要新密码。
- 尚未初始化时转到下方安装指引；只询问缺少的服务 URL、通知偏好等非敏感信息。拿到机密后继续原任务，验证业务结果；不要把“已通知”或“用户已填写”当作任务完成。

## 入口与申请

本 skill 可通过 `npx skills add` 安装，所需脚本随包分发。首次使用、用户要求安装或升级客户端时，按 [客户端初始化](references/setup.md) 完成依赖与本机配置；入口就绪时直接使用。安装只涉及本机使用端，不需要修改全局 `AGENTS.md`、`CLAUDE.md` 或其他 Agent 的全局指令。

Windows 入口为 `%LOCALAPPDATA%\Programs\SecretRequest\secret-request.cmd`；macOS / Linux 默认入口为 `~/.local/share/secret-request/secret-request`。也可使用已经配置的 `secret-request` 命令。[安装器](scripts/install.py) 支持 Python 3.12+，首次用服务 URL 自动生成配置。中转服务匿名接入，不需要账号、设备登记、配对码、长期 token 或管理员配置文件。

```powershell
& "$env:LOCALAPPDATA\Programs\SecretRequest\secret-request.cmd" --agent-name 'Codex' --name '测试库登录' --purpose '查询已授权测试库的结构' --fields-file .\fields.json -- python .\query.py
```

不指定 `--fields-file` 时，收到的是原始 UTF-8 字符串；指定后收到整份 JSON 对象。字段文件仅定义 `id`、`label`、`type`、`required`，禁止实际输入值或默认值：

```json
[
  {"id":"username","label":"用户名","type":"text"},
  {"id":"password","label":"密码","type":"password"}
]
```

支持 text、password、textarea、email、url，1–16 个字段，required 默认 true。默认交给程序 stdin，读取到 EOF，不追加换行；Python 用 `sys.stdin.buffer.read().decode('utf-8')`，多字段再用 `json.loads`。`--env NAME` 则把整份内容放进该子进程的一个环境变量。

客户端创建申请后，自行发送配置的本机通知和 webhook；只等待这条申请。通知失败会报告渠道状态，不重新创建申请；仅在用户要求备用入口时使用 `--show-link`。链接持有者可以填写或拒绝，勿随意转发。

## 等待与执行

默认等待输入 600 秒，可用 `--wait 10..1800` 调整。用支持后台命令的工具启动，保存工具返回的进程会话 ID，后续查询同一进程。等待时继续独立工作；没有独立工作时有限时等待，不把 waiting 当作任务完成，也不要求用户回聊天确认填写。

拒绝、取消或过期后停止此次请求，不自动循环催促。首次提交前不要修改待执行程序。机密仅通过网页填写，不能改为聊天、剪贴板或读取密码库。

解密后默认建立本机内存会话，输出 session_ready 及句柄，然后执行程序。程序输出被抑制；需要业务结果时，让程序单独保存必要的非敏感结果。提交和领取成功不等于业务成功。

`completed` 仅表示程序执行结束，必须同时检查 `exit_code` 和本次非敏感业务结果；非零退出码不能报告成功。程序失败后，核对是否已有部分业务操作，再修正程序并复用仍有效的会话，不必重新申请机密。外层命令退出码可能与程序退出码重合，不能仅凭数字判断失败原因。

遇到 `failed`、`execution_failed`、`execution_timeout`、`result_unknown` 或输出中断时，按 [失败排查与结果判断](references/troubleshooting.md) 检查最后状态、已有会话和业务结果，再决定是否重试。通用 `failed` 本身不能定位原因，也不代表程序一定没有执行。

## 复用与清理

```text
secret-request --use-session <handle> -- python query.py
secret-request --session-status <handle>
secret-request --revoke-session <handle>
```

同一任务优先复用已有句柄，不重复申请。会话固定首次工作目录和 stdin/env 方式；复用时不再传申请信息或 --env。同一会话一次运行一个程序。

默认空闲超时 300 秒，`--session-ttl 10..1800` 可调整。合法执行期间暂停空闲到期，执行结束后重新计时；状态查询、无效调用、重复执行不续期。单次执行默认上限 300 秒，可用 --execution-timeout 调整。明确只需一次时用 --one-shot。

任务完成或放弃后主动撤销。revoking 表示仍在清理，不能报告已经结束；revoked 表示已停止。空闲过期、撤销或后台退出后句柄失效，机密不能恢复。最多 16 个本机复用后台，每个会话最多 256 次执行，达到上限时停止并检查申请或重试逻辑。

断线出现 result_unknown 时，结合 execution_requested 中的 ID、会话状态和业务结果判断；不自动重跑可能已执行的写操作。句柄具有使用权限，不保存到仓库、长期笔记或分享给其他任务。

本工具避免正常流程让机密进入模型上下文，不隔离有本机完整权限的恶意程序。程序只能将机密用于原任务授权的目标，不打印、保存或通过日志、结果、命令参数回传机密。撤销是解除内存引用，不能承诺擦除所有系统内存副本。
