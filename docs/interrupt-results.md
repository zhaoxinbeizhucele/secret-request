# 主动中断与执行结果约定

基线核对：2026-10-10，当前 HEAD 仍为 `d1f1ef4b5fdb6d648390c3ee53f5cd9aa24e6aad`，与 release-readiness 报告一致。原仓库未跟踪的调查材料保留；本轮使用 `fix/interrupt-results` 独立 worktree。

## 状态约定

- 执行与会话分开表达：终态事件的 `execution` 记录本次 `execution_id` 和真实执行状态；`session_state` 表示 active、revoked、revoking、unavailable、unknown 或 not_created。
- 主动 Ctrl+C 记录停止意图，在可获得会话句柄的交接完成后请求撤销本会话。等待申请时取消申请且不执行；启动中不会因信号在句柄交接间抛出异常而遗留无人知晓的会话。重复 Ctrl+C 不打断必要清理。
- 撤销回执须包含本次执行结果。已 completed/timeout/failed 的真实结果保持不变；只有后台确认终止才输出执行 cancelled。终止不表示既有业务副作用回滚。
- 状态未知输出 `result_unknown` / `execution.status=unknown`，附带使用同一句柄和 execution_id 的查询、撤销参数。不得重发 run。active 会话中 not_started 只表示查询当时尚未登记，原断线请求可能随后接受；没有明确拒绝或撤销确认时不能当作未执行终态。
- 非主动断线不自动撤销或重复执行。`--session-status HANDLE --execution-id ID` 只查指定任务；结果缺失不使用 `last_result` 替代。本次结果在会话存续期间有界保存（最多原有 256 次执行）。
- 带 execution_id 的主动撤销后，后台保留从首次撤销起最多 60 秒的结果回执用于丢响应恢复；清除机密并结束执行后才进入无机密回执状态，并释放机密会话名额。普通无 ID 撤销保持原有退出行为；已有回执不会因再次无 ID 撤销立即消失。进程退出/回执到期后，执行结果不可恢复，必须核对业务证据。
- POSIX 仅清理受控进程组，Windows 使用 Job Object；不承诺任意脱离进程组后代的安全隔离，不扩大本轮进程控制实现。

## 范围

只涉及客户端、会话状态协议、相关测试及必要 skill/生成副本。通用错误分类、安装、打包加固、网页、服务部署、进程隔离重构均留待后续。

## 实现及兼容边界

- `secret_request/client.py:139`：SIGINT 只记录意图，不在会话句柄交接中抛异常；默认申请与复用都经过本次执行上下文。启动前已收到取消时不启动程序；启动后的完成结果优先于随后到达的取消。
- `client.py:189`、`:309`：执行 RPC 只发送一次。撤销响应、原执行响应和指定 ID 的查询均可确认结果；撤销等待期间或结果输出期间新确认的终态也保留。命令退出码在最后清理后决定，与最终事件一致。已确认结果与 unknown 会话状态可以同时存在。
- `session.py:69`、`:94`、`:109`：按执行 ID 保存最多 256 个结果，查询不替换成 last_result；撤销立即禁止机密复用，停止确认后给出执行回执。`session.py:258` 管理短期回执与机密会话锁的生命周期。
- README、skill 主说明与 troubleshooting 已同步。执行 `python -I scripts/build_skill.py` 生成客户端副本；副本一致性与复制到仓库外运行由现有 bundle 测试验证。

原有无 ID status/revoke 接口仍可用。新协议只涉及本机客户端/后台，不需要中转服务变更。**既存旧后台没有按 ID 查询和短期回执能力**；新客户端遇到此类缺失会保守报告 unknown，不能用旧 last_result 猜测。现有安装未更新，因此本次实现尚未在用户日常入口生效。

取消是请求而非立即完成承诺：正在等待的 HTTP/RPC 或启动交接按既有超时返回后处理停止意图；重复 Ctrl+C 不提前打断必要清理。强制杀死客户端、机器断电、恶意脱离进程组等不在 SIGINT 保证内。`--one-shot` 不创建会话，保留既有完成/超时事件形式，本轮只同步其停止意图和启动前检查。

## 实际验证

所有验证使用虚构输入、loopback 中转、临时配置/用户目录和隔离 Python 环境；消费者故意向 stdout/stderr 打印虚构输入，断言客户端输出不含输入、无异常堆栈。没有使用现有客户端配置、真实 webhook 或 Debian 服务。

最终结果：Windows 全量 **165 passed**；WSL/Linux **153 passed、1 deselected**（打包失败明确记录，浏览器/Node 两组未运行），见 [验证记录](validation/stage-a/README.md)。新增 `tests/test_interrupts.py` 共 22 项，其中 17 项分别在 Windows 与 Linux 送达真实 OS 信号：Windows 在隐藏独立控制台发送 CTRL_C_EVENT，Linux 对独立客户端进程组发送 SIGINT。屏障只控制真实启动、HTTP/RPC 或结果输出的时序；没有用抛 KeyboardInterrupt 代替中断验收。

| 验收点 | 已执行的证据 |
| --- | --- |
| 默认新申请 | waiting、submitted/consume 响应、bootstrap 写入前、后台已 ready 但尚未交接句柄、执行中、完成响应/状态查询刚返回时的真实中断；等待时中转确认为 cancelled，已领取时为 consumed，均不启动消费者；已创建的会话明确 revoked |
| 会话复用 | 执行中、完成响应/查询/输出时 Ctrl+C；原请求或撤销响应丢失时恢复真实退出码 7；未知时实际执行输出的 query_args 和 revoke_args，两条命令均成功确认同一 ID 的回执 |
| 其他会话 | 独立会话在目标中断时仍正在执行并正常退出 9，也能继续复用；没有被撤销 |
| 非主动断响应 | 真实 socket 发送一次后丢响应；暂停接受时输出 unknown，放行后同一 ID 查得 completed/0，副作用计数为 1；执行另一个 ID 后原 ID 仍查得原结果，不采信 last_result |
| 回归与生命周期 | 正常 0/非零退出、超时、撤销、stdin/env、复用、空闲到期、256 次上限与现有 OS 锁检查；新增验证无机密回执释放机密名额、反复撤销不续期且回执到期退出 |

实际平台为 Windows 11（10.0.26300，Python 3.13.5）和 WSL2 Ubuntu/Linux（6.6.87.2，Python 3.12.3）。**未验证 macOS、独立 Linux 主机/Debian 实际部署、用户手按键盘、现有安装的 cmd/Unix 包装入口中断行为**。Windows 浏览器回归使用隔离 headless Edge；Linux 未跑浏览器和 Node WebCrypto 两组。测试通过不表示已发布或生产可用。

测试基础设施的最小修复：

- `tests/test_browser_flow.py:73` 自动建立截图目录的父目录，修复干净 worktree 中不存在 artifacts 导致的既有失败。
- 新 Windows 中断夹具在目标独立控制台中恢复 Win32 Ctrl+C 接收属性；独立假脚本确认基础 Python 和 venv 都受执行宿主继承属性影响，无需生产代码做解释器特判。[Microsoft 说明](https://learn.microsoft.com/en-us/windows/console/setconsolectrlhandler)
- 新测试屏障初版将已知结果用例错误匹配到 unknown，已修正并复测；无生产行为变化。

## 后续清单与限制

- **已确认但本轮不修复**：WSL/Python 3.12 下 `tests/test_deploy_package.py:33` 失败：`tarfile.extractall(filter="data")` 在 umask 077 下提取目录后得到 0700，而断言要求其他用户可遍历。归档成员的 0755/0644 断言先通过；不能由此推断 Debian 实际安装是否失败。留待打包阶段核对解包方式与测试预期。本轮没有修改打包代码或该测试。
- **待验证**：macOS SIGINT；实际平台终端/包装入口；清理长时间阻塞时 revoking 的真实平台表现；旧客户端与新后台的组合。这些没有用模拟成功替代证据。
- 60 秒回执只解决短期丢响应，进程退出后没有持久结果账本；元数据后台不再占机密槽，也不是另一个服务或安全隔离层。长期记录、通用错误分类、资源加固及进程隔离仍属于后续范围。
- 没有提交、推送、重装、发布或部署。停止在阶段 A 的本子任务，不自动进入其他阶段。

## 人工验收清单（尚未由用户执行）

使用本 worktree 的隔离 Python：`<python> -m secret_request.client`，配合本地测试中转和只含虚构输入的临时配置；不要用真实机密，也不要把句柄写入仓库。时序窄窗口可用 `pytest tests/test_interrupts.py -q` 复跑对应真实 OS 场景。

| 入口/操作 | 预期结果及边界 |
| --- | --- |
| 新申请 CLI，等待输入时 Ctrl+C | execution=not_started、session_state=not_created，申请 cancelled，无消费者启动 |
| 新申请提交虚构输入；启动交接/执行中 Ctrl+C，可重复按两次 | 已创建的会话 revoked；执行前中断可为 not_started，已接受的执行确认停止则 cancelled；没有无人知晓的可用会话，无输入输出；中止提示不声称副作用回滚 |
| `--use-session HANDLE -- <长任务>`，另一个独立会话也在执行，再 Ctrl+C | 仅所用会话撤销；另一个会话任务正常完成且仍 active |
| 快任务返回 0/7，在结果输出尚未退出时 Ctrl+C（完成屏障用例） | completed 保留实际退出码，session_state 可为 revoked；撤销响应不明时保留已知结果并报告会话 unknown，命令退出码与最终结果一致 |
| 丢执行/撤销响应，执行输出的 recovery 参数；之后再执行不同 ID | 同一 ID 查得对应结果或明确 unknown；不重复 run、不拿后来 last_result 代替；撤销回执 60 秒后不可恢复，不能把 unavailable 当已确认业务结果 |
| 正常执行、超时后再复用、普通撤销及空闲到期 | 正常/超时结果真实；未撤销会话可按原规则复用；已撤销/到期拒绝执行，查询和重复 ID 不续期 |
