# 公共服务与本机自建交付记录

本轮目标：公共 HTTPS 中转；skill 默认公共/可选本机或 HTTPS 自建；无 Docker 本机快速启动；Compose 部署；企微 webhook；官网介绍页；Actions 发布 GHCR 镜像。

## 实现

- 默认公共地址 https://secret-request.eicai.cc；更新保留已有配置，另一服务采用独立应用/配置目录。
- 本机服务器仅监听 127.0.0.1，安装器提供独立客户端和服务器入口。停止前台/工具会话进程即可关闭，不创建系统常驻服务。
- 公网 Compose 自动 HTTPS（Caddy）与已有 HTTPS 反代两种替代方案；代理覆盖来源头，relay 限制连接并发、请求体大小与读取时间。
- 根路径官网和申请页分离。官网支持复制命令、深色模式、桌面及窄屏。
- 新安装默认关闭本机通知，优先引用企微 webhook 环境变量；旧通知设置保持。
- 打包改为明确允许清单；Python 解包工具保留数据过滤安全校验，同时设置已知源码目录权限。
- GitHub Actions 测试通过后构建 amd64/arm64 镜像并推送 GHCR，提供 latest 与完整提交标签。

## 本地证据

- Windows 全套 169 passed（96.09 秒），含打包允许清单、本机独立服务器/客户端连接、配置模式和既有功能回归。
- 新增官网后相关检查 18 passed（11.34 秒）：首页桌面/390px/320px无横向溢出，锚点、剪贴板成功/失败、深色模式，以及安装/打包/本机服务器。
- 实际执行 python -I 的服务端与客户端打包入口均成功；仅导入函数的测试不代替入口验证。
- 官网截图在 artifacts/public-service，未提交真实机密。

## 外部交付

2026-10-15，已完成下列实时验证：

- Actions [38678459172](https://github.com/zhaoxinbeizhucele/secret-request/actions/runs/38678459172) 成功，Linux 162 passed、2 skipped（浏览器相关模块缺少 Playwright，Windows 另行覆盖）。生成 amd64/arm64 镜像，GHCR 包为 public；无登录主机实际从 GHCR 拉取成功。
- 部署代码提交 139b8f0cefced66dad696a42eeb3a607918aa6c1。镜像索引 digest 为 sha256:9717a0955c3dd6db08d5d0474d5127701b0bb6733d283afa022fda2761f8a4d9，实际 amd64 image ID 为 sha256:93bdb3f46366579ed532611c498c239faa1aa55fa4f745f26ce90888a8ad2c68。
- 目标机直连 GHCR 较慢；在已有 dmit-pro 主机按上述 digest 拉取，经 SSH 流式传输到目标机。目标 image ID 相同，未本地重建或换源。
- DNSPod 新增 secret-request.eicai.cc A → 159.75.138.202（TTL 600，记录 ID 2430811130）；随后系统解析读回一致。只新增本子域名记录。
- ssh eicai.cc → VM-12-9-debian，/home/zhaox/dockerApp/secret-request，Compose 项目 secret-request-public；容器 UID 10001、只读根文件系统、仅 127.0.0.1:8787 发布，健康状态 healthy。
- 新增 /etc/nginx/conf.d/secret-request.eicai.cc.conf，复用现有 *.eicai.cc 证书；nginx -t 通过后平滑 reload。旧容器 ID 与核对前一致。站点禁用访问日志，有请求/连接限流和超时。
- 公网 HTTPS /health、首页、首页 JS/CSS、输入页及所有输入页资源读回通过。
- 从 GitHub 实际 npx skills add 到隔离项目，使用下载的安装器和独立 Python 环境。默认无 URL 初始化后 --check-service 为 ready，pip check 通过；本机模式从生成的入口实际启动，完成同机加密/解密/执行/300 秒会话/撤销；停止后监听端口消失。
- 下载的客户端连接公网服务，通过实际浏览器填写虚构多字段值，成功解密交付给任务并撤销会话。首次探针对原始 JSON 字节按 Python 格式化结果作比较，因浏览器紧凑 JSON 而失败；改为比较 JSON 字段内容后通过，产品保持原字节未改变。提交后的 Edge 扩展浮层阻挡状态观察，因此本轮不声称公网真人关页验收已通过。
- 公网额外验证：错误 Origin 返回 403，100001 字节请求被拒绝；持有八条同来源申请时第九条返回 429，即使每次伪造不同 X-Forwarded-For 也无法绕过；另一台主机仍能创建申请，证明没有共享代理配额。测试后取消全部虚构申请。
- 自动 HTTPS Compose 也实际启动验证：独立临时项目、仅 loopback 的 18080/18443、localhost 内部 CA；使用该 CA 证书校验后，Caddy → 独立 relay 的 HTTPS /health 与官网均通过，随后清理本测试容器/网络/卷。这证明 Compose 连通与配置，不把 localhost 内部 CA 测试说成已为新公网域名执行 ACME 签发。
- Caddy 2.10.2 实际 config validate 通过。公网 Compose 固定 Caddy 服务地址，主机反代 Compose 固定网关地址；不再默认信任任意转发来源。
- 最终本地全套 170 passed（102.97 秒）。独立首页截图/代码审查结论 pass；独立部署代码审查发现的代理信任范围已修复，当前运行容器也已读回限定地址。

企微当前状态：协议/重试/错误响应已有自动化覆盖，真实机器人联调正在通过已安装 secret-request 的本机通知申请地址；未拿到可用地址前，不声明真实企微发送已通过。完整地址不会进入聊天、Git、镜像或服务端配置。

## 运维与回退

- 本站未购买资源，复用现有主机、域名和通配证书（核对有效期至 2026-11-13）。证书续期沿用该机现有管理流程。
- 当前使用固定提交标签，更新先 pull 目标 SHA/digest，再 docker compose --env-file .env -f compose.yaml up -d --wait。保留上个标签即可回退，重启前的未交付申请会失效。
- 站点回退：只撤下本项目独立 Nginx 配置并通过 nginx -t 后 reload，停止本项目 Compose。不要停止或修改其他站点/容器。
- 公共服务是共享的尽力服务，无可用性承诺；不要将健康检查或虚构值测试等同于真实用户业务验收。

## 人工验收

- 官网 /：桌面和手机查看、点击开始使用并复制命令；说明和三种模式清晰，暗色无横向溢出。
- 新 Agent 会话：npx skills add 后初始化；默认公共服务，也可选择本机/自建。已有配置更新保留原服务。
- 本机模式：启动生成的 server 入口后 --check-service；本机浏览器可填写，端口占用明确报错，Ctrl+C 后连接不可用。手机不能访问本机链接。
- 企微：运行已授权申请、桌面或手机打开通知（本机模式仅同电脑）、填写虚构值；任务接收且不在聊天输出输入。拒绝不执行，失败不重复创建。
- Compose：新主机设域名后启动，健康、首页和填写链路通过；更新重启使旧未交付申请失效。
