# 阶段 A 验证记录

日期：2026-10-10（Asia/Shanghai）；分支 `fix/interrupt-results`，基线 `d1f1ef4b5fdb6d648390c3ee53f5cd9aa24e6aad`。实现说明与人工验收见 [状态约定](../../interrupt-results.md)。

环境使用临时 venv、临时用户目录、环境变量白名单、禁用第三方 pytest 自动插件；不读取用户配置。所有输入均为虚构值；中转仅监听 loopback、通知关闭。浏览器使用隔离 headless Edge。Python 依赖由现有 requirements 提供，pytest 8.4.2。没有安装/更新日常客户端，没有访问 Debian 服务。

| 平台与入口 | 最终命令与结果 |
| --- | --- |
| Windows 11 10.0.26300 / Python 3.13.5 | `python -m pytest -q --basetemp <临时目录> --junitxml <临时结果>`；**165 passed in 108.27s**，退出 0；[windows-tests.txt](windows-tests.txt) / [XML](windows-tests.xml) |
| WSL2 Ubuntu / Linux 6.6.87.2 / Python 3.12.3 | 同上，另外 `--ignore=tests/test_browser_flow.py --ignore=tests/test_webcrypto.py --deselect=tests/test_deploy_package.py::test_archive_has_readable_files_and_explicit_traversable_parents`；**153 passed, 1 deselected in 46.00s**，退出 0；[linux-tests.txt](linux-tests.txt) / [XML](linux-tests.xml) |

Linux 排除的两组需要未准备的浏览器/Node 环境，已在 Windows 验证。先前未 deselect 的 Linux 运行得到 **151 passed, 1 failed in 45.22s**，唯一失败为既有打包测试，见 [完整失败记录](linux-package-check.txt)；此后新增两项结果保真竞态测试。打包失败没有修复或掩盖，后续清单记录了具体断言和验证边界。

`tests/test_interrupts.py` 新增 22 项：17 项实际 Windows CTRL_C_EVENT / Linux SIGINT；其他检查使用真实子进程、socket 断响应、回执到期和一个确定性轮询边界。不用模拟 KeyboardInterrupt 代替 OS 信号。Windows 每个目标有隐藏独立控制台，独立发送 helper 附着该控制台；不会向用户现有终端广播。目标恢复宿主继承的 Win32 Ctrl+C 接收属性；Linux 每个目标使用独立 session/process group。

隔离启动的最小方式（需要先在临时 venv 准备依赖）：

```text
# Windows：从独立验证进程传入白名单环境，HOME/USERPROFILE/AppData/TEMP 指向临时目录
<venv-python> -m pytest -q --basetemp <临时目录>

# Linux：使用临时 HOME/TMPDIR，固定 PATH；测试环境无用户认证变量
env -i PATH=/usr/bin:/bin HOME=<临时HOME> TMPDIR=<临时目录> PYTHONUTF8=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 <venv-python> -m pytest -q --ignore=tests/test_browser_flow.py --ignore=tests/test_webcrypto.py --deselect=tests/test_deploy_package.py::test_archive_has_readable_files_and_explicit_traversable_parents --basetemp <临时目录>
```

不要仅复制上述 Python 命令到含真实凭据的环境；本轮执行通过父进程传入白名单环境。临时环境不代表安装分发或生产环境验收。macOS、独立 Debian、用户亲手键盘操作和已安装包装入口没有验证。
