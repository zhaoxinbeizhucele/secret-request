---
name: secret-request
description: 已授权任务缺少密码、API Key 等机密时，发送本机或 webhook 通知，让用户在网页填写，并交给本地任务程序使用，避免进入聊天。支持多字段、短期复用和本机客户端初次配置。
---

发起申请前，准备并检查使用机密的任务程序、工作目录和非敏感结果路径。已有可用认证时直接使用；不要为查看凭据而重新索取。申请名称、用途、Agent 名称和字段定义会出现在网页或通知里，不要包含机密。

## 入口与申请

本 skill 可通过 `npx skills add` 安装，所需脚本随包分发。首次使用、用户要求安装或升级客户端时，按 [客户端初始化](references/setup.md) 完成依赖与设备配置；入口就绪时直接使用。安装只涉及本机使用端。

Windows 入口为 `%LOCALAPPDATA%\Programs\SecretRequest\secret-request.cmd`；macOS / Linux 默认入口为 `~/.local/share/secret-request/secret-request`。也可使用已经配置的 `secret-request` 命令。[安装器](scripts/install.py) 支持 Python 3.12+；配置文件导入不会覆盖已有设备认证。

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
