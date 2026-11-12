# TermForYou 前后端功能联调与实装状态清单

> **更新时间**：2026-11-12
> **文档定位**：按当前代码调用链盘点前后端已接线功能、只读接线功能和假数据/假操作。这里的“已接线”指前端确实调用了对应后端接口，不代表已对每台目标主机完成实机验收。

---

## 一、 判定口径与现状

| 分类 | 判定口径 | 主要模块 |
| :--- | :--- | :--- |
| **已接线** | 前端发起 REST/WS 请求，后端读写本机配置或经 SSH 访问目标主机；仍需目标机验收 | 主机池、真实 xterm、轻量指标、远程文件管理、Docker 启动/停止/删除/重启/Exec |
| **只读接线，写操作模拟** | `inspect` 返回部分真实列表，但管理按钮只改前端内存或调用模拟命令函数 | Systemd、Cron、防火墙 |
| **纯前端/假数据** | 无对应后端数据源，或展示固定样例、伪造执行结果 | AI 生成、命令历史/模板 |

**仍存在的列表限制**：`src/stores/workbenchStore.ts` 预置文件、服务和防火墙演示数组。`inspectHost` 仅在后端返回**非空数组**时覆盖它们；采集为空、失败或切换主机时可能继续展示样例或上一台主机的数据。进程、计划任务和 Docker 已支持清空与过期响应隔离，其余列表尚未推广，不能只凭页面出现列表就判断数据来自当前主机。

**计划任务、Docker 与文件列表**：计划任务和 Docker 已移除初始演示数据，切换主机立即清空并发起巡检，成功时接受空列表，失败时显示读取失败；旧请求不会覆盖当前任务。文件管理器主动调用 `files/.../list` 成功后会用真实结果（包括空列表）覆盖文件样例。

---

## 二、 已经与后端真实联调实装的功能 (Real Backend Integration)

### 2.1 主机资产与认证体系 (`P0_HOSTS`)
*主机来自本机 `~/.ssh/config`，连接统计来自 SQLite；密码只进入后端进程内存。*

| 功能点 | 前端位置 | 后端端点 / 协议 | 实装说明与底层机制 |
| :--- | :--- | :--- | :--- |
| **原生 SSH 配置感知与读取** | `HostsHubView.vue`<br>`workbenchStore.ts` | `GET /api/v1/ssh/hosts` | 解析宿主机 `~/.ssh/config`，结合 SQLite `host_stats` 读取累计连接次数与最近连接时间降序排列。 |
| **新增/同别名覆盖主机配置** | `HostsHubView.vue` | `POST /api/v1/ssh/hosts` | 后端写回宿主机 `~/.ssh/config`。前端新增函数即使请求失败仍会插入本地列表并继续探测，不能把列表出现新主机视为写入成功。 |
| **持久化物理删除主机** | `HostsHubView.vue` | `DELETE /api/v1/ssh/hosts/{host_alias}` | 从 `~/.ssh/config` 移除 Host 块（自动生成 `.bak` 备份），同步清理 SQLite 连接统计与内存会话。 |
| **单台主机连通性探测** | `HostsHubView.vue` | `POST /api/v1/ssh/probe/{host_alias}` | 真实 TCP 握手测算 RTT 延时、抓取 SSH Banner、识别开机状态，并检测密码/密钥认证合法性。 |
| **全量主机批量并发探测** | `HostsHubView.vue` | `POST /api/v1/ssh/probe-all` | `asyncio.gather` 并发探测全部服务器连通性，并自动为在线主机并行拉取轻量性能指标。 |
| **定时自动探活轮询** | `workbenchStore.ts` | `POST /api/v1/ssh/probe-all` | 前端每 30 秒轮询，可用 `localStorage` 中的非敏感偏好关闭；浏览器标签隐藏时跳过该次轮询。 |
| **认证方式智能推导 (三态)** | `workbenchStore.ts` | 后端响应字段 `auth_method` | 动态识别 `custom_key`（特定密钥）、`default_key`（默认密钥/Agent免密）、`password`（密码认证）。 |
| **内存临时密码流** | `HostsHubView.vue` | `POST /api/v1/ssh/credentials/{host_alias}` | 前端弹窗提交密码，后端 `metrics_service` 内存保存并重探。前端刷新清除输入框内的密码，但**不会清除仍在运行的后端内存密码**；后端重启才清除。 |
| **手动连接计数统计** | `workbenchStore.ts` | `POST /api/v1/ssh/hosts/{host_alias}/connect` | 点击连接会请求后端累加 SQLite 统计；请求异常时前端也会临时累加显示，因此该数值可能仅是本地状态。WebSocket 建连成功时后端还会记录一次。 |

---

### 2.2 终端交互与 PTY 会话 (`P1_WORKBENCH` 终端核心区)
*真实终端使用 WebSocket 双向流与 asyncssh PTY。*

| 功能点 | 前端位置 | 后端端点 / 协议 | 实装说明与底层机制 |
| :--- | :--- | :--- | :--- |
| **真实 PTY 终端通信** | `RealXtermTerminal.vue` | `WS /ws/terminal/{host_alias}` | xterm 键盘输入经 `stdin` 帧传到后端 SSH PTY，远端输出经 `stdout` 帧回显；这条链路与前端本地命令历史相互独立。 |
| **首帧握手与动态认证** | `RealXtermTerminal.vue` | WS 首帧 `action: "auth"` | 携带 `cols`、`rows`、`term` 及内存临时密码/私钥口令，后端调用 `conn.create_process` 分配伪终端。 |
| **终端视口动态尺寸同步** | `RealXtermTerminal.vue` | WS 帧 `action: "resize"` | 监听容器与窗口 Resize，发送实际列数/行数，后端驱动 Linux 内核 `change_terminal_size` 刷新。 |
| **同主机双栏终端** | `TerminalWorkbenchView.vue` | 两个独立的 WS 会话 | 打开分屏后两个 xterm 实例均连接当前主机。未实现跨主机分屏、广播输入；页面切换后组件卸载，连接会关闭。 |

工作台的 AI 建议执行按钮会调用真实 xterm 的 `sendCommand`，因此该入口在 WebSocket 已连接时可向远端发命令；随后调用的 `executeTerminalCommand` 仅追加本地命令历史。高危命令正则仅覆盖该按钮路径，用户在 xterm 中直接键入的命令不经过这段拦截。

---

### 2.3 系统性能监控与 Mini HUD (`MiniHudBar` & `P2_METRICS_PROCESS` 仪表区)
*远端经 SSH 采集轻量指标，前端约每 3 秒轮询当前主机。*

| 功能点 | 前端位置 | 后端端点 / 协议 | 实装说明与底层机制 |
| :--- | :--- | :--- | :--- |
| **微缩状态条 (Mini HUD)** | `MiniHudBar.vue` | `GET /api/v1/ssh/metrics/{host_alias}` | 顶栏常驻展示 CPU 负载、物理内存已用/总量、网络实时上下行速率，每 3 秒非阻塞极轻量轮询更新。 |
| **多核 CPU 矩阵与负载** | `MetricsProcessView.vue` | `GET /api/v1/ssh/metrics/{host_alias}` | 读取 `/proc/stat` 解析各个独立 CPU 核心利用率，以及 `/proc/loadavg` 1/5/15 分钟负载均值。 |
| **物理内存与 Swap 总量** | `MetricsProcessView.vue` | `GET /api/v1/ssh/metrics/{host_alias}` | 内存和 Swap 数值来自后端；页面把已用内存进度条固定分成 80%“应用”和 20%“PageCache/Buffers”，**该细分比例并非实测**。 |
| **网络流量与磁盘 I/O 速率** | `MetricsProcessView.vue` | `GET /api/v1/ssh/metrics/{host_alias}` | 读取 `/proc/net/dev` 和 `/proc/diskstats` 计算实时读写 KB/s 与吞吐速率。 |
| **宿主机防火墙运行状态识别** | `MetricsProcessView.vue`<br>`FirewallSecurityView.vue` | `GET /api/v1/ssh/metrics/{host_alias}` | 自动探查远端生效的防火墙类型（`ufw` / `firewalld` / `iptables`）及其 Systemd 服务活跃状态。 |

---

### 2.4 全功能远程文件系统与在线编辑 (`P3_FILES` & `FileEditorDrawer`)
*文件读取与写入均有对应后端端点；具体权限取决于目标主机。*

| 功能点 | 前端位置 | 后端端点 / 协议 | 实装说明与底层机制 |
| :--- | :--- | :--- | :--- |
| **远程目录列表浏览** | `FileManagerView.vue`<br>`workbenchStore.ts` | `GET /api/v1/ssh/files/{host_alias}/list` | 支持绝对路径与 `~` 展开，获取文件权限位、八进制 `mode`、大小、所有者、修改时间及软链接指向。 |
| **目录体积占用分析（类 ncdu）** | `FileManagerView.vue`<br>`workbenchStore.ts` | `GET /api/v1/ssh/files/{host_alias}/du` | 远端脚本实际调用 `du`（GNU/BusyBox 回退）分析目录下各子目录体积分布，并更新容量缓存；没有调用 `ncdu`。 |
| **单个目录体积测算** | `FileManagerView.vue`<br>`workbenchStore.ts` | `POST /api/v1/ssh/files/{host_alias}/single-dir-size` | 后台执行 `du -sb` 测算特定受保护文件夹体积，支持 `sudo`。 |
| **在线读取远程文件内容** | `FileEditorDrawer.vue`<br>`workbenchStore.ts` | `GET /api/v1/ssh/files/{host_alias}/content` | 读取文本文件至抽屉，自动识别二进制文件拦截，支持只读文件 `sudo` 读取。 |
| **在线编辑保存文件内容** | `FileEditorDrawer.vue`<br>`workbenchStore.ts` | `PUT /api/v1/ssh/files/{host_alias}/content` | 保存文本内容写回远端，支持 `sudo_write`。当前前端对 `/etc`、`/lib`、`/usr` 路径自动预选 sudo；后端未勾选时遇到权限错误也会自动回退 `sudo -n`，均不符合项目“只由用户显式勾选”的约束。 |
| **新建空白文件 (touch)** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/touch` | 远端新建空白或带初始内容的文件，支持 `sudo`。 |
| **新建文件夹 (mkdir)** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/mkdir` | 远端递归创建目录，支持权限模式与 `sudo`。 |
| **重命名与文件移动 (mv)** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/rename` | 前端提交新旧路径，后端经 SSH 执行远端操作。 |
| **文件/目录复制 (cp)** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/copy` | 远端递归复制文件或文件夹。 |
| **删除文件/目录 (rm)** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/delete` | 删除选中文档或文件夹，带 `/`、`/etc` 等核心系统目录防误删保护，支持 `sudo`。 |
| **修改权限与所有者** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/chmod` | 修改八进制权限码（如 `0755`）及 `owner:group`，支持递归应用与 `sudo`。 |
| **归档打包与解压缩** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/archive` | 支持多选文件打包为 `.tar.gz`，或解压归档文件至目标路径。 |
| **本地文件上传** | `FileManagerView.vue` | `POST /api/v1/ssh/files/{host_alias}/upload` | 浏览器发送文件二进制内容到后端，再写入远端。当前前端对 `/etc`、`/lib`、`/usr` 目录自动带 `sudo=true`；后端 `cat` 写入失败时还会自动回退 `sudo -n tee`，尚不符合项目约束。 |
| **单文件 / 批量压缩下载** | `FileManagerView.vue` | `GET /api/v1/ssh/files/{host_alias}/download`；`POST /api/v1/ssh/files/{host_alias}/download-batch` | 单文件/目录下载，以及多项打包下载均已接线；后端另有批量 GET 路由，前端未使用。 |

**权限核查补充**：除编辑器和上传路径的前端自动预选外，后端的目录列表/文件读取、`mkdir`、`rename`、`copy`、`delete`、`chmod`、上传和下载实现也存在权限失败后的 `sudo -n` 自动回退；这些路径当前都没有做到“仅在用户显式勾选后提权”。

---

### 2.5 全量巡检数据只读同步 (Inspect 只读实装)
*说明：后端批量执行 `REMOTE_FULL_INSPECT_SCRIPT` 后返回列表，但部分字段是占位值；除计划任务和 Docker 外，前端只有收到非空数组才覆盖既有数据，见文首共同限制。*

| 只读数据项 | 数据获取接口 | 远端真实采集机制 | 对应页面展示 |
| :--- | :--- | :--- | :--- |
| **进程列表与端口映射** | `GET /api/v1/ssh/processes/{host_alias}`，亦包含在 `inspect` | `/proc` 采集进程及启动标识，兼容无完整 `ps` 的主机；`ss` 可选，缺失时仅降级监听信息。按自启动以来平均 CPU 排序前 100 项，每个 PID 保留一个监听端口；防火墙状态为未知，CWD 读取不到不伪造路径 | `P2_METRICS_PROCESS` 真实进程表格，5 秒刷新和手动刷新 |
| **进程停止/强杀** | `POST /api/v1/ssh/processes/{host_alias}/kill` | 仅 SIGTERM/SIGKILL；PID、启动标识校验，确认后执行；sudo 默认关闭，失败不自动提权，操作后重新读取真实状态 | `P2_METRICS_PROCESS` 信号管控 |
| **Docker 容器列表与挂载卷** | `GET /api/v1/ssh/inspect/{host_alias}` | `docker ps -a` + 单次批量 `docker inspect`（最多 25 个容器）提供容器、端口、挂载及运行参数；页面展示真实资源限制与端口映射，不伪造实时资源或防火墙放行结果 | `P5_DOCKER` 容器管理列表 |
| **Docker 容器启动/停止** | `POST /api/v1/ssh/docker/{host_alias}/containers/{container}/action`，JSON `{action: "start" 或 "stop", sudo: false}` | 校验操作与容器名称/ID；执行 `docker start -- <container>` 或 `docker stop -t 10 -- <container>`，返回真实退出码；停止前确认，成功后巡检刷新，同容器生命周期操作互斥 | `P5_DOCKER` 每行启动/停止按钮 |
| **Docker 容器重启** | `POST /api/v1/ssh/docker/{host_alias}/containers/{container}/restart` | 名称/ID 白名单校验，执行 `docker restart -t 10 -- <container>`；仅显式勾选后使用 `sudo -n`，命令失败不自动提权；完成后巡检刷新 | `P5_DOCKER` 重启按钮 |
| **Docker Exec 终端** | `WS /ws/terminal/{host_alias}`，auth 中的 `docker_container` / `sudo` | 在远端 SSH PTY 直接运行固定的 `docker exec -it -- <container> /bin/sh`，支持键盘、尺寸同步、重连和退出；未运行的容器禁用入口 | `P5_DOCKER` 页内专用终端 |
| **Docker 容器物理删除** | `DELETE /api/v1/ssh/docker/{host_alias}/containers/{container}` | 带容器名正则白名单校验，调用 `docker rm [-f] [-v]` 真实删除；当前路由没有 `sudo` 参数，普通命令失败后后端会自动尝试 `sudo -n`，与项目“只由用户显式勾选 sudo”的约束不一致 | `P5_DOCKER` 容器删除按钮 |
| **Systemd 服务名称、描述和状态** | `GET /api/v1/ssh/inspect/{host_alias}` | `systemctl list-units` 提取前 35 项；`enabled` 由加载状态推断，内存、工作目录、启动命令、重启策略和日志为占位或空值 | `P6_SYSTEMD` 服务列表 |
| **当前用户 Crontab 表达式和命令** | `GET /api/v1/ssh/inspect/{host_alias}` | `crontab -l` 提取非注释行；标题、用户、上次执行时间/结果、下次运行时间等为固定/占位值，未采集 systemd timers | `P7_CRON` 任务清单 |
| **部分防火墙规则** | `GET /api/v1/ssh/inspect/{host_alias}` | 解析 `ufw` / `firewall-cmd` / `iptables`；来源 CIDR、备注等多处填固定值，页面“监听端口是否放行”未做真实规则比对 | `P8_FIREWALL` 规则清单 |

---

### 2.6 计划任务列表刷新与服务器切换 (`P7_CRON`)

*数据仍来自全量巡检接口 `GET /api/v1/ssh/inspect/{host_alias}`，本次修改未新增后端端点。*

| 功能点 | 当前行为 |
| :--- | :--- |
| **切换立即刷新** | 监听 `activeHostId`，同步清空旧任务并发起新主机巡检，显示“正在读取当前服务器的计划任务…”。无需等待每 30 秒的自动探测；每 3 秒的轻量指标轮询本身不更新任务列表。 |
| **真实空列表** | 初始 `cronTasks` 为空，不再预置 3 条演示任务。只有成功巡检（`status: ok` 且 `cronTasks` 为数组）才接收任务；空数组同样覆盖列表，并显示当前 SSH 用户未配置任务。 |
| **失败与重试** | HTTP/网络失败、认证失败、`partial` 或缺少有效任务数组时，清空列表并显示读取错误；“重试”重新调用当前服务器的巡检接口。全量巡检失败时不会把后端兜底空数组显示成“未配置任务”。 |
| **过期响应拦截** | 写入前同时校验主机与请求序号；覆盖切换 A→B→A、同主机请求乱序、旧请求晚失败、非当前主机后台探测、关闭会话后返回等情况。单主机探测返回的任务也经过同样处理。 |
| **刷新时机** | 切换主机、再次手动连接当前主机、手动探测/重试，以及自动批量探测完成后，均可触发任务更新。切换会立即发出请求，列表仍需等待 SSH 全量采集完成；没有按主机缓存任务。 |

采集范围仍为 **SSH 登录用户的 `crontab -l`**，未采集系统级计划任务、其他用户的 crontab 或 systemd timers。上次/下次执行、退出码和输出摘要等仍为占位信息；新增、启禁用、试运行的接线状态见 3.6。

---

## 三、 目前仍为假数据 / 未联调 / 纯前端模拟的功能清单 (Mock / Pending)

> [!WARNING]
> 下列功能在 UI 上具备交互控件，但**未对接真实后端接口**，主要表现为：写死在前端 Store 的初始 Demo 数据、通过 `setTimeout` 伪造延时响应、或调用前端本地函数 `executeTerminalCommand` 仅记录命令，未真正发往远端 Linux 执行。

### 3.1 AI Copilot 自然语言命令生成 (`P1_WORKBENCH` 底部)
- **当前状态**：🔴 **纯前端模拟**
- **代码位置**：`src/views/TerminalWorkbenchView.vue` (`handleGenerateCommand`)
- **假数据机制**：
  - 代码中写死了多个 `if-else` 分支匹配「内存」「端口」「大文件」「docker 清理」「系统日志」等关键词；
  - 使用 `await new Promise(r => setTimeout(r, 350))` 伪造生成耗时；
  - 未匹配的意图仅简单输出 `echo "# [AI 生成] ..."`；
  - **完全未接入后端任何 LLM（OpenAI / DeepSeek / Ollama / Gemini）接口**。
- **与后端的联调缺口**：真实模型生成接口尚不存在；接入时凭据应仅保存在会话内存中。

---

### 3.2 历史命令提炼与常用命令资产库 (`P1_WORKBENCH` 侧边栏 & `P4_COMMANDS`)
- **当前状态**：🔴 **初始样本与前端算法；无远端历史采集/模板持久化**
- **代码位置**：`src/stores/workbenchStore.ts`、`src/services/commandExtractor.ts`、`src/views/CommandIntelView.vue`
- **假数据机制**：
  - `INITIAL_HISTORY_LINES`：在 Store 写死了 22 条固定的历史命令（如 `docker logs ...`、`journalctl ...`）；
  - `savedSnippets`：在 Store 写死了 4 条 demo 模板（排查端口、查大文件、容器追踪、UFW 放行）；
  - **未从远端主机读取 `~/.bash_history` 或 `~/.zsh_history`**；
  - xterm 中直接输入的命令不会写入 `rawHistoryLines`；部分按钮调用 `executeTerminalCommand` 时才追加本地样本，该函数不向远端发送命令；
  - 用户新保存的常用命令仅存在前端响应式变量中，**刷新浏览器即刻丢失，后端无数据库持久化支持**；
  - `runLlmSemanticPolish`（AI 语义润色）：前端针对 `kubectl`、`docker`、`find` 写的硬编码标题替换。
- **与后端的联调缺口**：
  - 尚无读取远端 shell 历史文件的后端采集端点；
  - 尚无后端 SQLite 常用命令模板持久化存储与标签分类 CRUD 接口。

---

### 3.3 进程管理操作 (`P2_METRICS_PROCESS`)
- **当前状态**：✅ **列表与 SIGTERM / SIGKILL 已接通前后端**
- **代码位置**：`src/views/MetricsProcessView.vue`、`src/stores/workbenchStore.ts`、`backend/main.py`、`backend/process_manager.py`、`backend/metrics_collector.py`。
- **执行链路**：确认对话框 → `POST /api/v1/ssh/processes/{host_alias}/kill`（`pid`、`signal`、`identity`、`sudo`）→ SSH 运行标准库 Python 脚本真实发送信号；结果返回后重新读取进程列表，不凭成功回包删除行，不将“发送信号成功”误报为“进程已退出”。
- **权限与保护**：只允许正整数 PID ≥ 2 和 SIGTERM/SIGKILL；核对 boot ID 与 `/proc/PID/stat` 启动时刻，标识变化拒绝操作；支持时使用 pidfd 绑定进程，旧 Python/内核降级为身份校验后 `os.kill`（仍存在检查与发送间极短的 PID 复用竞态）。拒绝僵尸进程、PID 1 和本次 SSH 操作的祖先进程；默认不提权，显式勾选才使用 `sudo -n -- python3`，不保存提权密码。
- **数据与刷新**：移除演示进程，空列表直接生效；切换服务器立即清空并隔离旧回包，进程专用查询与全量巡检共享采集代码、遵循请求时序；同 PID 操作互斥。错误、认证失败或网络异常均显示真实失败/未确认结果，操作后刷新；页面可见时每 5 秒自动刷新，可手动重试。
- **采集边界**：最多展示平均 CPU 占用前 100 项，CPU 为进程自启动以来平均值；一个 PID 仅保留一个监听端口，尚未实现服务/容器归属解析和真实防火墙匹配。SIGTERM 可能被忽略，托管进程可能自动重启。

---

### 3.4 Docker 容器管理 (`P5_DOCKER`)

- **当前状态**：✅ **模块已完成；列表、运行参数、启动、停止、删除、重启和 Exec 已接线，docker run 命令窗口已移除**
- **代码位置**：`src/views/DockerStudioView.vue`、`src/stores/workbenchStore.ts`、`src/components/terminal/RealXtermTerminal.vue`、`backend/main.py`、`backend/metrics_collector.py`
- **已实装**：
  - **启动/停止容器**：`exited` / `created` 显示启动，`running` / `restarting` 显示停止；`paused` / `removing` / `dead` / `unknown` 禁用启停。停止需确认，执行真实 API，成功后重新巡检，不在前端伪造运行状态；启停/重启期间锁定同一容器的相关按钮，失败或超时按真实结果提示。
  - **重启容器**：确认后请求真实重启 API，按主机与容器 ID 标记进行中并防止重复点击；根据后端命令退出码反馈结果，成功后巡检刷新列表。连接失败/超时不会伪报成功，需刷新确认最终状态。
  - **Exec 终端**：在 Docker 页顶部打开独立 xterm，点击入口后自动滚到顶部使终端可见；通过 auth 帧传递固定主机与容器 ID，在远端 PTY 直接进入容器 `/bin/sh`。支持输入、输出、resize、重连；关闭面板、离开页面或切换主机均断开会话；容器内 `exit` 结束会话，不会退回宿主机 shell。
  - **权限与认证**：启停/重启/Exec 的 sudo 默认关闭，仅用户勾选才使用 `sudo -n`，不会自动回退提权；删除接口是例外：没有用户 sudo 选项，后端会在 `docker rm` 失败后自动尝试 `sudo -n`。SSH 临时密码沿用后端内存凭据。镜像需包含 `/bin/sh`，无 shell 的镜像会显示 Docker 错误并结束会话。
  - **参数查看**：网络模式（含 host/bridge/none/自定义网络）、重启策略和健康状态显示在摘要；“查看参数”按容器展开运行时间、退出码/OOM、重启重试/计数、CPU/内存限制/绑核、运行用户/特权/只读根文件系统、网络 IPv4/IPv6 与 Compose 项目/服务。挂载显示只读/读写，兼容 tmpfs。详情采集失败保留基础容器列表，显示未读取，不把未知当作默认值。
  - **采集边界**：仍使用现有 inspect API，一次 `docker ps` 后批量 inspect 最多 25 个容器，只投影必要参数，不采集 Env、启动命令或任意标签；未增加提权。已发布端口保留绑定 IP 与 TCP/UDP/SCTP，停止容器可回退读取配置绑定；仅暴露的端口标注“未发布”，host 模式明确提示共享宿主机网络。
  - **列表来源与隔离**：移除 Docker 初始演示数组；切换主机清空列表并巡检，接受成功空列表，支持加载/错误/重试；与计划任务共用主机和请求序号校验，阻止旧响应覆盖。启停/重启/Exec 使用列表中的容器 ID；保留 Docker 实际返回的 running/exited/created/paused/restarting/removing/dead 状态，无法识别时为 unknown。
- **边界说明**：列表巡检依赖 SSH 用户本身的 Docker 权限，不主动提权；缺少 Docker、权限不足或采集命令失败时显示读取失败或空列表，不据此断言主机没有容器。删除接口沿用当前路由行为，操作前需确认。

---

### 3.5 Systemd 系统服务管理与操作 (`P6_SYSTEMD`)
- **当前状态**：🟡 **列表数据已实装，增改启停为假操作**
- **代码位置**：`src/views/SystemdManagerView.vue`
- **假数据机制**：
  - Store 预置 3 条演示服务；巡检返回非空列表时才替换，且远端列表的内存/工作目录/启动命令/近期日志等字段仍为占位值；
  - **启停/重载服务**：点击“启动 / 停止 / 重启”，调用 `executeTerminalCommand` 记录本地命令，并直接在前端强行修改 `svc.state = 'running'`，**远端服务没有任何变化**；
  - **新建服务向导**：表单生成的 unit 内容仅在前端内存数组 `store.systemdServices.unshift`，未在远端 `/etc/systemd/system/` 真实写入文件，也未执行 `daemon-reload`。
- **与后端的联调缺口**：
  - 尚无服务管控端点 `/api/v1/ssh/systemd/{host_alias}/services/{service}/action`（start/stop/restart/reload/enable/disable）；
  - 新建服务需要复用已实装的 `PUT /api/v1/ssh/files/{host_alias}/content` 写入 unit 文件，并另行触发 `daemon-reload`。

---

### 3.6 Crontab 计划任务管理与操作 (`P7_CRON`)

- **当前状态**：🟡 **列表读取与切换刷新已实装；新增、启禁用、试运行未接线**
- **代码位置**：`src/views/CronManagerView.vue`、`src/stores/workbenchStore.ts`
- **已完成的列表行为**：见 2.6。初始演示任务已删除，支持切换即时刷新、空列表、错误重试与过期响应拦截。
- **假数据机制**：
  - **执行信息与预测**：任务的上次/下次执行、退出码、输出摘要等仍为占位值；构建器中的自然语言描述与未来触发时间来自前端预设/固定文本，未接入真实调度计算；
  - **试运行任务**：点击“试运行”仅调用 `executeTerminalCommand` 记录本地命令，并把本地上次运行时间改为“刚刚”，未真正执行；
  - **启用/禁用任务**：仅在前端将 `task.enabled` 置反并弹 Toast，**未修改远端 crontab 配置**；
  - **新增计划任务**：仅向前端数组 `store.cronTasks` 添加一条记录，生成的 `(crontab -l; echo ...) | crontab -` 未实际执行。
- **与后端的联调缺口**：
  - 尚无 Crontab 操作端点；后续需要提供写入、注释、删除特定 crontab 行，以及单次异步运行任务命令的接口。

---

### 3.7 防火墙规则管理与操作 (`P8_FIREWALL`)
- **当前状态**：🟡 **列表与状态已实装，新增放行规则为假操作**
- **代码位置**：`src/views/FirewallSecurityView.vue`
- **假数据机制**：
  - Store 预置 4 条演示规则；巡检返回非空列表时才替换。远端采集规则的来源 CIDR 和备注等字段也存在占位值；
  - **应用新增规则**：点击“立即应用该规则”，前端在内存中 `store.firewallRules.unshift`，并将对应端口的 `firewallAllowed` 置为 true，但生成的 `sudo ufw allow ...` 或 `firewall-cmd ...` **并未发给远端执行，实际放行状态未知**。
  - “监听端口与规则对照”使用进程的 `firewallAllowed` 字段；进程采集现返回 `null`（未知），尚未完成真实防火墙规则匹配。
- **与后端的联调缺口**：
  - 尚无根据探测到的防火墙类型（ufw / firewalld / iptables）统一添加/删除规则的后端端点 `/api/v1/ssh/firewall/{host_alias}/rules`。

---

## 四、 按页面速查

| 页面/组件 | 已接线的数据与动作 | 假数据、占位字段或未接线动作 |
| :--- | :--- | :--- |
| `P0_HOSTS` 主机池 | SSH 配置读/写/删、探测、临时密码、连接统计 | 新增请求失败仍可能显示本地新主机；连接统计请求失败会本地累加 |
| `P1_WORKBENCH` 工作台 | xterm 的键盘输入、输出和窗口尺寸经 WS 连接 SSH PTY；同主机双栏可建立两条连接 | AI 生成为关键词规则；离开页面会关闭终端连接，多主机 Tab 只是前端标签 |
| `P2_METRICS_PROCESS` 性能/进程 | CPU、内存、Swap、磁盘和网络指标；真实进程列表与 SIGTERM/SIGKILL、确认与显式 sudo、刷新与过期响应隔离 | 内存应用/PageCache 比例固定为 80/20；端口放行状态未知；归属尚未解析 |
| `P3_FILES` 文件管理 | 目录、体积、文件内容及大部分增删改传操作都有 API | 初始文件样例和读取失败时的编辑器缓存/生成文本；编辑器保存后“重启服务”按钮只模拟重启；前端路径预选及后端多个操作的 sudo 自动回退均违反显式授权约束 |
| `P4_COMMANDS` 命令库 | 本地正则聚类与参数化模板 UI 可运行，无后端数据源 | 初始 22 条历史样本、4 条模板；LLM 语义润色是假；模板不持久化，执行入口只记录本地命令历史 |
| `P5_DOCKER` 容器 | 容器列表、网络模式/端口与挂载、重启策略/健康/资源限制等展开参数；真实启停/重启/删除和 Exec PTY；列表切换隔离与错误重试；已移除 docker run 部署窗口 | 无 shell 镜像不支持 Exec；列表读取依赖 SSH 用户的 Docker 权限 |
| `P6_SYSTEMD` 服务 | 非空巡检时服务名称、描述、状态 | 服务详情多个字段为占位；启停/重启/新建是假操作 |
| `P7_CRON` 计划任务 | 切换主机立即巡检当前用户 crontab，支持空列表、错误重试及过期回包拦截 | 上次/下次执行信息为占位；新增、启禁用、试运行是假操作；systemd timer 未采集 |
| `P8_FIREWALL` 防火墙 | 防火墙类型/状态及部分规则采集 | 来源/备注有占位；监听端口放行未真实比对；添加规则是假操作 |
| 公共 Mini HUD | 当前主机轻量指标轮询 | 无独立假数据源，依赖主机指标请求 |

**本地功能不算假数据**：主题偏好、自动探测开关、文件书签和跨页导航是前端本地状态/偏好；它们可正常使用，但不是远端主机数据。

**未由当前前端调用的后端路由**：`GET /api/v1/ssh/config-path`、`GET /api/v1/ssh/files/{host_alias}/dir-sizes`、`GET /api/v1/ssh/files/{host_alias}/download-batch`。这些路由存在不等于对应 UI 已接线。

---

## 五、 最近调整的验证记录（2026-11-11 至 2026-11-12）

| 检查项 | 结果与范围 |
| :--- | :--- |
| 前端类型检查与构建 | `pnpm run build` 通过；存在 Vite 大包体积警告，无构建错误。 |
| 计划任务回归检查 | `node scripts/verify-cron-host-switch.mjs` 通过。使用真实 Store 与模拟延迟响应验证即时刷新、空结果、A→B→A、请求乱序、旧请求晚失败、部分采集/认证/HTTP 失败、重试、后台探测隔离及关闭会话。该脚本不访问远端主机。 |
| 页面实测 | 本次修复后，`test-env` 显示 1 条任务，`cloud-prod` 显示空列表；切回服务器时先显示当前主机加载状态。已检查计划任务页面的深浅主题。 |
| 后端冒烟 | `GET /api/v1/ssh/hosts` 返回 4 台；`POST /api/v1/ssh/probe-all` 返回 `status: ok`，含 4 项探测结果及 4 项指标响应。 |
| Docker 后端检查 | `backend/.venv/bin/python scripts/verify-docker-backend.py` 通过 13 项检查，覆盖批量巡检参数解析、host/none/共享网络、健康检查缺失、CPU 配额、详情失败降级、未发布/IPv6/停止容器端口和 tmpfs，及启停请求模型、命令拼接、非法操作/容器参数拒绝、退出码/失败/超时、认证失败及仅显式 sudo。 |
| Docker 参数实机验证 | `test-env` 现有容器正确返回 host/bridge 与不同重启策略；隔离临时容器经真实 inspect API 验证 none 网络、on-failure:3、0.25 核/32 MiB 限制、只读根文件系统、运行用户、健康检查、tmpfs、Compose 归属与未发布端口。临时容器及匿名卷已清理。 |
| Docker 参数界面验证 | 在 1440×900 深浅主题下检查摘要与展开详情，验证 Enter 展开/收起和 bridge 网络实际 IPv4；800px 窄窗口按内容宽度改为单列参数，长镜像名与挂载路径不挤压操作按钮。浏览器未记录错误。 |
| Docker 前端回归 | `node scripts/verify-docker-store.mjs` 通过，验证启停/重启请求与显式 sudo、同容器操作冲突拦截、失败不伪造状态、异常后解锁、切换服务器后的回包隔离和空列表。原有计划任务回归脚本也通过。 |
| Docker 实机验证 | 在 `test-env` 创建 90 秒后自行退出并自动移除的隔离测试容器；重启 API 改变其 `StartedAt`。Exec 验证容器身份、PTY 输入输出、resize 与退出；非法容器参数在建立 SSH 前被拒绝。 |
| Docker 启停实机验证 | 在 `test-env` 的隔离临时容器上验证启动 API 将 created 变为 running，停止 API 执行成功且由 Docker 自动清理容器；不存在容器返回真实失败，非法操作返回 422，未知主机返回 404。页面点击启动后显示 running 并切换为停止按钮；停止确认对话框与深浅主题已检查，临时容器已清理。 |
| Docker Exec 滚动检查 | 从容器列表底部点击 Exec，页面滚动位置由 612 变为 0，顶部终端可见；深浅主题均已检查。 |
| Docker 页面检查 | 实际通过 Exec 按钮进入容器，验证命令回显、PTY 和 shell 退出；已检查深浅主题及停止容器的 Exec 禁用状态。修正了 resize 可能抢在 auth 首帧前发出的握手顺序，并以服务端 `ready` 标记 PTY 就绪。 |
| 进程管理验证（2026-11-12） | `backend/.venv/bin/python scripts/verify-process-backend.py`（8 项）与 `node scripts/verify-process-store.mjs` 通过；测试主机上两个临时进程分别经 HTTP API 接收 SIGTERM/SIGKILL 后退出，过期启动标识及重复终止已退出进程均被拒绝，临时进程已清理；1440×900 浅色主题已检查真实列表、刷新、显式 sudo、确认与两种信号按钮。 |
| 已删除功能核对 | 源码已无公共随行终端组件、独立日志窗、关联开关和 `terminalHistory` 模拟输出状态。 |

以上验证覆盖进程管理与列表切换、Docker 运行参数与启停/重启/Exec、Exec 顶部滚动与界面移除调整；任务写入、启禁用和试运行仍未对接远端，其他页面列表的演示数据与过期数据问题仍见第一节。
