# 失败排查与结果判断

保留当前调用已输出的 JSON 状态、工具进程会话 ID，以及已有的机密会话句柄；不要重新申请来代替排查。工具进程会话 ID 用来继续等待客户端，`session_ready.session` 才是 `--session-status` / `--use-session` 的句柄，二者不能混用。句柄具有使用权限，不贴到聊天、日志或笔记。

## 先判断执行到了哪里

| 已观察到的状态 | 下一步 |
| --- | --- |
| `waiting`，原进程仍在运行 | 继续等待同一个进程；通知渠道失败时检查该渠道状态，不重复创建申请 |
| `session_ready` | 已建立机密会话，还不能证明任务程序成功；保存句柄并继续读取后续状态 |
| `execution_requested` | 记录 `execution_id`；没有最终结果时先查询会话，不能直接重跑 |
| `completed` | 查看 JSON 中的 `exit_code`，并核对本次非敏感业务结果；退出码为 0 也不自动证明业务目标达成 |
| `execution_failed` / `execution_timeout` | 检查程序路径、依赖、工作目录、超时及业务结果；可能已经产生部分写入，不自动重复执行 |
| `failed` 或输出意外中断 | 原因未定位；结合先前事件、会话状态和业务结果排查，不能认定为密码错误或任务未执行 |
| `declined` / `cancelled` / `expired` | 停止此次申请，不自动循环通知用户 |
| `interrupted` / `execution.status=not_started` | 主动中断发生在执行前；分别核对会话是否 not_created 或 revoked |
| `execution.status=cancelled` | 后台已确认本次执行中止；副作用未回滚，不能据此直接重复写操作 |
| `result_unknown` / `execution.status=unknown` | 使用 recovery 参数或同一 execution_id 查询/撤销；不推断已停止 |

先看结构化 `status`，再看结果中的 `exit_code`。程序本身也可能返回 1、2、3 等退出码，与客户端的失败、未完成、超时退出码重合；外层退出码只作辅助，不能单独分类。没有输出 `completed` 时，不要编造程序退出码。

## 有会话句柄时

```text
secret-request --session-status <handle>
secret-request --session-status <handle> --execution-id <本次execution_id>
secret-request --revoke-session <handle> --execution-id <本次execution_id>
```

查看 `session_state` 和指定 ID 的 `execution`；没有指定 ID 时仍可查看 `status`、`running`、`last_result` 和 `remaining_seconds`：

- `active` 只表示会话可用。`running` 非空时仍有程序在执行，继续等待，不并发重跑。
- `last_result` 是最近一次结果，可能为空或属于此前执行。将它的 `execution_id` 与本次 `execution_requested.execution_id` 对上，才能用其中的状态和退出码判断本次执行；不要把旧的成功结果当成新结果。
- 指定 ID 时以 `execution` 为准：completed 保留退出码；running 尚在执行；not_started 表示查询当时该 ID 尚未被接受。断线后若会话仍 active，原请求可能随后被接受，不能据此重跑；明确拒绝或撤销确认后才能认定不会执行。unknown 不能推断结果。执行查询、重复撤销不会续期。
- 主动 Ctrl+C 会请求撤销本次使用的会话，重复 Ctrl+C 不打断必要清理。已确认 completed 的任务不会因此改报 cancelled；`session_state=revoked` 与执行成功/失败是两个事实。已确认中止不表示回滚副作用。
- 撤销返回 revoking 或 unknown 时，使用输出 recovery 的参数数组调用当前客户端入口。带 ID 撤销后最多 60 秒可查询无机密回执，期间会话不能复用；进程退出/到期无法恢复结果，需核对业务证据。不能把 unreachable/unavailable 当成已确认中止。
- `result_unknown`、连接中断或超时后，结合上述状态及本次业务结果确认是否已执行。结果不明确时，尤其是写操作，停止依赖该结果的操作并说明不确定性，不自动重试。
- 已确认程序失败且可以安全重试时，修正程序并用 `--use-session <handle> -- <程序及参数>` 复用机密；原工作目录和 stdin/env 交付方式不变。不要仅为了续期而循环执行命令，状态查询不会续期。
- `session_unavailable` 表示已不能使用该会话；`invalid_session` / `unauthorized` 时先核对是否误用了句柄，不输出句柄内容。失效或一次性使用的机密无法恢复；任务仍需继续且允许再次申请时才发起新申请。

## 没有可用句柄或原因仍不明时

- 用 `--help` 检查本机入口，用 `--check-service` 检查当前配置对应的服务连接。健康检查不创建申请、不通知，只证明服务可连通且兼容，不能证明任务或此前提交成功。
- 按失败阶段检查可执行程序是否存在、参数与字段定义是否有效、工作目录和结果目录是否可用，以及本机配置与通知环境变量是否就绪。只检查存在性、格式和非敏感字段，不输出整份配置或环境变量值。
- 若使用 `--one-shot`，不会产生可复用句柄；程序是否执行及是否部分成功仍需结合状态与业务结果核对。收到通用失败或进程退出不能推断“没有副作用”。
- 子程序 stdout/stderr 被抑制，通用 `failed` 也刻意隐藏原始异常，避免泄露机密。不要通过放开输出、打印请求/响应、异常堆栈、stdin 或环境变量来排查。需要诊断信息时，让任务程序仅保存明确筛选的非敏感错误类别和业务结果，再按原授权范围安全重试。

汇报已确认的阶段、未确认的结果和下一步，不把通知送达、填写成功、解密成功或程序退出等同于业务完成。任务完成或放弃后撤销仍有效的会话。
