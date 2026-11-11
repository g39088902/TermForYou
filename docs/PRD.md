# TermForYou 服务器管理面板 — 产品需求文档 (PRD) 与技术架构设计

> [!IMPORTANT]
> **产品核心理念**：「以终端为中心的可视化运维工作台 (Terminal-Centric Visual Ops Workbench)」。不仅解决传统 Web 面板（如 1Panel、宝塔）操作路径长、终端体验割裂的问题，也弥补传统 SSH 客户端在系统服务、防火墙、计划任务和容器编排上缺乏深度可视化管理的短板。

---

## 一、 产品定位与核心设计哲学

### 1.1 产品形态
- **架构模式**：采用现代轻量级前后端解耦的**免 Agent (Agentless)** 架构。
  - **前端**：Vue 3 (Composition API) + Tailwind CSS v4 + TypeScript + `@xterm/xterm`（状态管理使用全局 `reactive` 单例，未引入 Pinia）。
  - **后端**：Python 3.10+ FastAPI + `asyncssh` + SQLite（标准库 `sqlite3` 仅存主机连接次数与最后连接时间等非敏感统计）。
  - **通讯**：WebSocket (PTY 交互流) + HTTP REST (配置感知、巡检指标、临时凭据、文件与容器操作)。
- **零 Agent 侵入**：目标 Linux 服务器无需安装任何常驻后台守护进程，通过标准 SSH 协议直连，利用远端 `python3` 脚本与批量命令解析器将 `systemctl`、`crontab`、`docker`、`ufw/iptables`、`ss/proc` 与文件系统转化为可视化界面。

### 1.2 核心设计哲学
1. **严格零凭据持久化存储 (Zero-Storage Security)**：
   - 严禁在数据库、本地文件、环境变量或前端 LocalStorage 中持久化存储主机密码或私钥。
   - 密码仅作为**内存临时凭据**在后端生命周期或当前会话流转，刷新页面或重启后端即刻蒸发。
2. **原生 SSH 配置感知与双向透明同步 (Native SSH First)**：
   - 直接以宿主机 `~/.ssh/config` 为唯一数据源，新增或修改主机直接写回原文件（严格遵循 `User` 在 `HostName` 之前的语法规范），与原生命令行及三方开发者工具保持 100% 互通。
3. **静默生效与无打扰原则 (Silent Quality)**：
   - 底层修复（如视口截断、浮点行高补偿、网络重连）静默生效，严禁在 UI 向用户展示自嗨式 Bug 修复告知条。
4. **拒绝冗余输入，聚焦终端与 AI Copilot (No Redundant CLI Inputs)**：
   - 用户在黑屏终端中敲击命令是最直接的交互习惯；终端外部严禁设计重复敲原生命令的独立输入框。
   - 外部辅助框唯一定位为**自然语言 AI Copilot**，承担“自然语言意图 → 运维命令生成 → 确认一键执行”的增量价值。

---

## 二、 核心功能模块与落地进展 (Feature Specs & Status)

> 标记说明：
> - `[✅ 已实现]`：功能已在当前代码库完整实现并通过测试验证。
> - `[⏳ 进行中]`：已完成原型、核心底座或基础功能，正在深化。
> - `[📋 规划中]`：下一阶段路线图功能。

### 2.1 终端命令行交互 (Terminal CLI)
| 功能点 | 详细需求说明 | 优先级 | 落地状态 |
| :--- | :--- | :--- | :--- |
| **真实 PTY 仿真与 WebSocket 通信** | 基于 `@xterm/xterm` + `FitAddon`，与后端 `asyncssh` 建立双向 WebSocket 连接，支持完整 ANSI 256 色与 UTF-8（中文、Emoji、Nerd Fonts）。 | P0 | [✅ 已实现] |
| **自适应尺寸与末行防截断保护** | 监听容器与窗口 Resize，行数按真实 DOM 行高（≥ 18.5px）取整铺满可用高度，分数余量由状态栏/Copilot 栏吸收，并通过 `resize` 控制帧实时同步远端 Linux PTY。 | P0 | [✅ 已实现] |
| **多服务器会话管理** | 顶部 `TopSessionBar` 支持多主机 Tab 无缝切换、状态常驻与新建/关闭终端会话。 | P0 | [✅ 已实现] |
| **同窗口多终端分屏 (Split Pane)** | 支持单主机或多主机水平/垂直分屏与广播输入。 | P1 | [📋 规划中] |

### 2.2 自然语言 AI 命令生成 (AI Copilot)
| 功能点 | 详细需求说明 | 优先级 | 落地状态 |
| :--- | :--- | :--- | :--- |
| **自然语言意图输入底座** | 终端综合工作台底部专设 AI Copilot 操控条，支持自然语言提问（如“排查占用 80 端口的进程”、“清理无用 Docker 镜像”）。 | P0 | [✅ 已实现] |
| **高频 Prompt 快捷胶囊** | 提供高频运维场景一键填词（查内存最高进程、排查特定端口、查找大文件、Docker 缓存清理、最近失败服务）。 | P0 | [✅ 已实现] |
| **AI 建议指令卡片与一键执行** | 生成命令后展示包含命令释义、参数解释的建议卡片，支持直接一键【在终端执行】（通过 WebSocket 注入真实终端）。 | P0 | [✅ 已实现] |
| **真实 LLM 后端模型对接** | 后端对接 OpenAI 兼容协议（DeepSeek / Ollama / Gemini 等），替代目前的前端启发式推导。 | P1 | [⏳ 进行中] |

### 2.3 主机感知与零凭据认证体系 (SSH Host Management)
| 功能点 | 详细需求说明 | 优先级 | 落地状态 |
| :--- | :--- | :--- | :--- |
| **`~/.ssh/config` 双向解析与持久化** | 自动读取本地配置，提取 Host、User、HostName、Port、IdentityFile；新增主机规范化写回文件（严格保证 `User` 在 `HostName` 之前）。 | P0 | [✅ 已实现] |
| **认证方式智能识别推导** | 动态三态识别：`custom_key`（特定密钥）、`default_key`（默认密钥/Agent 免密）、`password`（密码认证）。未探测前展示中性标签，握手后动态更新。 | P0 | [✅ 已实现] |
| **内存临时密码认证流** | 免密被拒时弹出输入框，提交至后端内存字典暂存并重试探测，成功后连通。页面刷新或后端重启后即刻销毁。 | P0 | [✅ 已实现] |
| **批量探针与周期探活** | 支持一键单台/全部主机连通性探测（RTT 延迟、系统版本、认证状态），支持全局定时探针轮询开关与间隔设置（默认 30 秒）。 | P0 | [✅ 已实现] |

### 2.4 常用命令与历史命令提炼 (Command Intelligence)
| 功能点 | 详细需求说明 | 优先级 | 落地状态 |
| :--- | :--- | :--- | :--- |
| **工作台集成侧边栏** | 终端综合工作台右侧内置「常用命令」与「历史提炼」双标签面板，支持按关键词快速检索。 | P0 | [✅ 已实现] |
| **一键注入与执行** | 常用命令与提炼项支持一键发送到活动终端黑屏中执行，或将提炼命令一键转为常用命令模板。 | P0 | [✅ 已实现] |
| **参数化模板卡片** | 支持 `{{变量名}}` 占位符解析，执行时弹出参数填写抽屉。 | P0 | [✅ 已实现] |
| **远端历史自动采集与聚类** | 通过前端启发式与正则对常见运维命令进行去噪、聚类与占位符提取。 | P0 | [✅ 已实现] |

### 2.5 深度探针与非侵入式指标全景巡检 (Metrics & Inspection)
| 功能点 | 详细需求说明 | 优先级 | 落地状态 |
| :--- | :--- | :--- | :--- |
| **单会话批量指令巡检** | 探针接通后，后端通过一次 SSH 会话批量执行标准 Linux 命令并以分隔符切分，避免多次握手开销。 | P0 | [✅ 已实现] |
| **Mini HUD 极简微缩状态条** | 全局顶部常驻当前主机的 CPU、内存利用率进度条、延迟与状态指示。 | P0 | [✅ 已实现] |
| **性能与进程监控 (P2)** | CPU/内存利用率、Top 运行进程表（PID、User、CPU%、MEM%、命令）、监听端口列表反查。 | P0 | [✅ 已实现] |
| **系统服务巡检 (P6)** | 解析 Systemd 核心服务（Running/Failed 状态、是否开机自启），支持快速启停重载。 | P0 | [✅ 已实现] |
| **Docker 容器概况 (P5)** | 获取真实容器列表、运行状态、镜像名称、端口映射；支持真实启动/停止、确认后的删除/重启，以及页面内容器 Exec 终端。停止前确认，同容器操作互斥，完成后刷新真实状态；启停/重启/Exec 的 sudo 默认关闭。点击 Exec 后页面滚到顶部终端；CPU/内存仍为占位值。 | P0 | [✅ 已实现] |
| **安全与防火墙全景 (P8)** | 探测 UFW / Iptables 规则，提供监听端口与防火墙放行状态对照。 | P0 | [✅ 已实现] |
| **计划任务概况 (P7)** | 提取系统与当前用户 Crontab 任务项。 | P0 | [✅ 已实现] |
| **全屏文件管理器与代码编辑 (P3)** | 完整目录列表浏览、文件新建/重命名/删除/下载/解压缩、Chmod/Chown 权限配置，以及内置轻量代码编辑器抽屉（支持 sudo 提权保存）。 | P0 | [✅ 已实现] |

---

## 三、 UI/UX 架构与视觉规范

### 3.1 窗口与布局架构
- **TopSessionBar**：会话切换枢纽，展示各主机别名、IP、连通状态指示器。
- **Mini HUD**：紧随其下的窄栏微缩监控指标。
- **左侧导航栏 (Sidebar)**：覆盖 P0 主机池、P1 工作台至 P8 各子模块。
- **主舞台 (Main Stage)**：
  - **P1 终端工作台**：终端居左下置 AI Copilot，常用/提炼侧边栏居右；
  - **P2~P8 专业可视化页**：专业图表与数据网格。
- **终端入口**：SSH 交互集中在 P1 终端工作台。
- **顶部悬浮 Toast**：操作反馈弹窗置于顶部正中，彻底杜绝遮挡终端下半区与光标视界。

### 3.2 WCAG AAA 高对比度双主题设计
- **浅色模式 (Light Mode)**：以柔和浅灰底搭配深黑/高对比度深色文字与边框，杜绝浅灰白字导致的视觉疲劳。
- **深色模式 (Dark Mode)**：深邃纯净底色搭配高亮荧光对比色。
- **状态徽章规范**：
  - **成功/连通 (Emerald)**：`bg-emerald-500/15 text-emerald-700`（深色: `text-emerald-300`）
  - **警告/密码认证 (Amber)**：`bg-amber-500/15 text-amber-800`（深色: `text-amber-200`）
  - **危险/离线 (Rose)**：`bg-rose-500/15 text-rose-700`（深色: `text-rose-300`）
  - **信息/特定密钥 (Sky/Indigo)**：`bg-sky-500/15 text-sky-700`（深色: `text-sky-300`）

---

## 四、 通信协议与 API 接口规范

### 4.1 核心 RESTful API 端点清单
| 端点 | 方法 | 职责说明 | 落地状态 |
| :--- | :--- | :--- | :--- |
| `/api/v1/ssh/hosts` | `GET` | 读取 `~/.ssh/config`，返回按连接频次排序的主机列表与元数据 | [✅ 已实现] |
| `/api/v1/ssh/hosts` | `POST` | 新增主机写入 `~/.ssh/config`（User 在 HostName 前） | [✅ 已实现] |
| `/api/v1/ssh/hosts/{host_alias}` | `DELETE` | 从 `~/.ssh/config` 中移除指定主机块 | [✅ 已实现] |
| `/api/v1/ssh/probe/{host_alias}` | `POST` | 触发单台主机连通性与认证方式探测 | [✅ 已实现] |
| `/api/v1/ssh/probe-all` | `POST` | 批量并发探测全部主机并返回汇总状态 | [✅ 已实现] |
| `/api/v1/ssh/credentials/{host_alias}` | `POST` | 注入临时内存登录密码，触发快速重探 | [✅ 已实现] |
| `/api/v1/ssh/inspect/{host_alias}` | `GET` | 获取单台主机全量巡检数据（进程、Docker、服务等） | [✅ 已实现] |
| `/api/v1/ssh/metrics/{host_alias}` | `GET` | 轻量获取单台主机当前 CPU/内存等性能指标 | [✅ 已实现] |
| `/api/v1/ssh/files/{host_alias}/list` | `GET` | 远端目录文件与文件夹列表查询 | [✅ 已实现] |
| `/api/v1/ssh/files/{host_alias}/content` | `GET`/`PUT` | 远端文件内容读取与保存（支持 sudo tee 写入） | [✅ 已实现] |
| `/api/v1/ssh/files/{host_alias}/chmod` | `POST` | 批量/递归修改远端文件权限与所有者 | [✅ 已实现] |
| `/api/v1/ssh/docker/{host_alias}/containers/{container}` | `DELETE` | 删除指定 Docker 容器（带名称正则校验） | [✅ 已实现] |
| `/api/v1/ssh/docker/{host_alias}/containers/{container}/action` | `POST` | 启动/停止指定容器，JSON `{action: "start" 或 "stop", sudo: false}`；参数白名单校验，经 SSH 执行真实命令，无自动提权回退 | [✅ 已实现] |
| `/api/v1/ssh/docker/{host_alias}/containers/{container}/restart` | `POST` | 重启指定容器，JSON `{sudo: false}`；名称/ID 校验，无自动提权回退，返回真实命令结果 | [✅ 已实现] |

### 4.2 WebSocket 协议规范 (`/ws/terminal/{host_alias}`)
- **连接建立与认证首帧**：前端发起握手后 10 秒内发送认证帧：
  ```json
  {
    "action": "auth",
    "payload": { "cols": 120, "rows": 34, "term": "xterm-256color", "password": "..." }
  }
  ```
  后端提取配置后打开 `conn.create_process` PTY。
- **容器 Exec**：首帧可携带 `docker_container`（容器 ID/名称）与 `sudo`（默认 `false`）。后端校验后直接在 PTY 执行 `docker exec -it -- <container> /bin/sh`；失败或退出即结束会话。容器须运行且包含 `/bin/sh`，sudo 使用 `sudo -n`，不会询问或保存提权密码。
- **会话就绪**：PTY 成功创建后回传 `{ "action": "ready" }`，前端据此点亮连接状态。客户端先发送 `auth`，再发送尺寸同步帧；远端环境设置 `LANG=en_US.UTF-8`。
- **尺寸同步帧**：
  ```json
  { "action": "resize", "payload": { "cols": 120, "rows": 36 } }
  ```
  后端接收后调用 `process.change_terminal_size(cols, rows)` 驱动远端 Linux 内核刷新。
- **输入输出数据流**：客户端发送 `action: "stdin"`，服务端回传 `action: "stdout"` / `action: "stderr"` / `action: "auth_required"`。

---

## 五、 研发路线图与后续规划 (Milestones & Roadmap)

### 阶段一：核心基座与终端交互闭环 [✅ 已全部交付]
- [x] FastAPI + asyncssh 异步后端脚手架搭建。
- [x] 原生 `~/.ssh/config` 双向解析与规整持久化。
- [x] 基于 xterm.js 的真实 WebSocket PTY 终端通信与 ANSI 渲染。
- [x] 终端自适应尺寸解算与末行防截断数学安全边界保护。
- [x] 智能认证方式推导（特定密钥/默认密钥/密码认证）与零持久化内存密码流。
- [x] 单会话批量全量指令巡检（CPU、内存、进程、Docker、Systemd、防火墙、Crontab、文件管理）。
- [x] 自然语言 AI Copilot 命令输入底座与建议卡片展开。
- [x] WCAG AAA 浅色/深色双主题高对比度适配。

### 阶段二：AI Copilot 深度赋能与智能参数化 [进行中]
- [ ] 后端接入真实大模型接口（支持配置 OpenAI / DeepSeek / 本地 Ollama 模型）。
- [ ] 结合当前主机的 OS 类型（Ubuntu/CentOS/Alpine）为 Copilot 注入系统上下文，生成更加精准的命令。
- [ ] 历史命令后端自动归档挖掘与模板化推荐引擎。

### 阶段三：安全加固与高级交互能力 [规划中]
- [ ] `known_hosts` 主机指纹比对与中间人劫持防护机制。
- [ ] SFTP 大文件分块上传与断点续传队列管理。
- [ ] 终端多分屏（水平/垂直 Split Pane）与多终端广播输入。
