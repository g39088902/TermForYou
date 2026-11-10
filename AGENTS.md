# TermForYou - Developer & Agent Architecture Guide (AGENTS.md)

> 本文档面向参与 **TermForYou** 项目后续迭代的 AI Agents 与人类开发者。旨在阐明系统的核心设计原则、模块架构、关键技术点、核心数据流转以及高频避坑规范，确保任何后续功能的扩展均符合项目架构初衷与安全准则。

---

## 目录
1. [项目定位与核心哲学](#1-项目定位与核心哲学)
2. [总体系统架构与技术栈](#2-总体系统架构与技术栈)
3. [核心模块技术解析](#3-核心模块技术解析)
   - [3.1 原生 SSH 配置感知与双向同步 (`ssh_config_parser.py`)](#31-原生-ssh-配置感知与双向同步-ssh_config_parserpy)
   - [3.2 深度探针与智能认证方式推导 (`probe_service.py` & `metrics_collector.py`)](#32-深度探针与智能认证方式推导-probe_servicepy--metrics_collectorpy)
   - [3.3 终端连接与 PTY WebSocket 代理 (`main.py` & `RealXtermTerminal.vue`)](#33-终端连接与-pty-websocket-代理-mainpy--realxtermterminalvue)
   - [3.4 本地元数据存储与零凭据铁律 (`db.py`)](#34-本地元数据存储与零凭据铁律-dbpy)
   - [3.5 前端全局响应式状态中枢 (`workbenchStore.ts`)](#35-前端全局响应式状态中枢-workbenchstorets)
4. [UI/UX 与双主题适配规范 (Tailwind CSS v4)](#4-uiux-与双主题适配规范-tailwind-css-v4)
5. [高频开发任务规范与避坑指南](#5-高频开发任务规范与避坑指南)
6. [质量验证与构建工作流](#6-质量验证与构建工作流)

---

## 1. 项目定位与核心哲学

TermForYou 是一个**以终端为中心 (Terminal-First)**、面向 Linux 运维场景的高性能、轻量级现代化运维工作台。

在架构设计与功能扩展中，必须坚守以下三条核心哲学：

1. **严格零凭据持久化存储 (Zero-Storage Security)**：
   - 绝不允许在 SQLite 数据库、后端文件、环境变量或浏览器 LocalStorage / IndexedDB 中持久化存储任何主机的明文密码或私钥！
   - 对于非密钥对认证（密码认证）的主机，密码仅允许作为**内存临时凭据**在后端内存生命周期或前端当前会话中流动。页面刷新或重启服务后，密码即刻从内存中蒸发。
2. **原生 SSH 体验不设割裂屏障 (Native SSH Transparency)**：
   - 系统不使用专有的私有数据格式绑定主机，直接以本机的 `~/.ssh/config` 作为主数据源。
   - 新增、修改主机均应写回 `~/.ssh/config`，保持与系统原生 `ssh` 命令行及其他开发者工具的 100% 互通。
3. **极致轻量、非侵入式 (Agentless & Lightweight)**：
   - 目标服务器不需要安装任何常驻 Agent，所有硬件指标、系统服务、Docker 状态、安全防火墙规则均通过标准 SSH 命令集一次性异步批处理执行并正则解析。

---

## 2. 总体系统架构与技术栈

### 2.1 技术栈总览

| 模块 | 技术选型 | 说明 |
| :--- | :--- | :--- |
| **前端框架** | Vue 3 (Composition API, `<script setup lang="ts">`) | 响应式架构、强类型安全 |
| **构建工具** | Vite 6 + pnpm | 秒级 HMR 与极速打包 |
| **UI 样式** | Tailwind CSS v4 + Lucide Icons | 最新原子化 CSS，使用 CSS 原生层级与 `light-dark()` 规范 |
| **终端仿真** | `@xterm/xterm` + `FitAddon` + `WebLinksAddon` | 高性能 Canvas/WebGL 终端渲染 |
| **状态管理** | Pinia (`workbenchStore.ts`) | 单一数据源，驱动多标签、HUD、全景指标 |
| **后端框架** | Python 3.10+ FastAPI + Uvicorn | 异步高并发 HTTP API 与 WebSocket 服务 |
| **SSH 核心** | `asyncssh` | 异步 SSH2 协议实现，支持 PTY、Sftp 及直接命令执行 |
| **本地数据库**| SQLite (`aiosqlite`) | 仅存储用户偏好、标签、探针周期设置、命令 Intel 等非敏感元数据 |

### 2.2 架构通信拓扑

```
┌─────────────────────────────────────────────────────────────┐
│                      前端 Web 客户端                         │
│  (Vue 3 + Tailwind v4 + Pinia + xterm.js Canvas Renderer)   │
└──────────────┬───────────────────────────────▲──────────────┘
               │                               │
       HTTP REST API (8000)             WebSocket /ws/terminal/{alias}
       [探针/指标/配置同步/密码验证]         [双向 PTY 输入输出流 + Resize 信号]
               │                               │
┌──────────────▼───────────────────────────────┴──────────────┐
│                    FastAPI 后端服务                          │
│                                                             │
│  ┌───────────────────────┐       ┌────────────────────────┐ │
│  │   ssh_config_parser   │       │     asyncssh PTY       │ │
│  │  (双向解析 ~/.ssh/cfg) │       │   (WebSocket 会话桥接)  │ │
│  └───────────────────────┘       └────────────────────────┘ │
│  ┌───────────────────────┐       ┌────────────────────────┐ │
│  │     probe_service     │       │   metrics_collector    │ │
│  │ (周期轮询 / 状态探测) │       │ (非侵入式指令全量巡检) │ │
│  └───────────────────────┘       └────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │             SQLite: backend/termforyou.sqlite3         │ │
│  │             (仅存设置与元数据，严禁密码持久化)          │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────┘
                               │ SSH 2.0 (Port 22 或自定义端口)
                               ▼
               ┌───────────────────────────────┐
               │        远端 Linux 服务器群     │
               │  (CentOS / Ubuntu / Debian)   │
               └───────────────────────────────┘
```

---

## 3. 核心模块技术解析

### 3.1 原生 SSH 配置感知与双向同步 (`ssh_config_parser.py`)

- **解析逻辑**：
  - 扫描用户目录 `~/.ssh/config`，按标准 OpenSSH 配置语法提取：`Host`（别名）、`HostName`（IP 或域名）、`User`（登录用户名）、`Port`、`IdentityFile`（指定私钥路径）。
  - 若主机未指定 `User`，兜底采用当前本地登录用户名或 `root`；未指定 `Port`，兜底为 `22`。
- **持久化新增主机规范**：
  - 在写入新的 `Host` 块至 `~/.ssh/config` 时，**必须严格保证 `User` 在 `HostName`（IP）之前**，符合主流运维习惯，例如：
    ```sshconfig
    Host my-node
        User root
        HostName 192.168.1.100
        Port 22
        IdentityFile ~/.ssh/id_rsa
    ```
  - 写入操作应使用追加或保留注释的方式，严禁破坏用户已有的全局指令（如 `Host *`）或其它自定义参数。

### 3.2 深度探针与智能认证方式推导 (`probe_service.py` & `metrics_collector.py`)

#### 深度探测策略
探针（Probe）不只是简单的 TCP 端口探测，而是**真实的 SSH 握手探测 + 全页面指标提取**：
1. **轻量探活**：探测连通性、测算 RTT 延迟；
2. **全量数据巡检 (`fetch_full_inspection`)**：一旦探测接通，一次性拉取并解析以下模块：
   - 基础硬件指标：CPU 核数/使用率、内存配额/利用率、磁盘挂载与容量、网络流量。
   - 进程与服务：Top 进程列表、Systemd 关键系统服务（nginx, docker, sshd 等）。
   - Docker 容器：容器列表、状态、镜像、端口映射。
   - 安全与规则：UFW / Iptables 规则、Fail2ban 封禁名单、监听监听端口列表、已登录会话。
   - 调度任务：当前用户与系统的 Crontab 任务项。

#### 认证方式智能识别机制 (`auth_method`)
在未实际探测前，仅通过 `~/.ssh/config` 无法百分之百断定登录模式。系统实现了基于探测反馈的动态三态推导：
- **`custom_key` (特定密钥)**：`~/.ssh/config` 显式配置了 `IdentityFile`。
- **`default_key` (默认密钥)**：`~/.ssh/config` 未配置 `IdentityFile`，但本机通过默认密钥（如 `~/.ssh/id_rsa`, `id_ed25519`）或 `ssh-agent` 免密握手成功。
- **`password` (密码认证)**：
  - 免密握手被拒绝（抛出 `asyncssh.PermissionDenied`，标记 `auth_failed: true`）；
  - 或用户在 UI 侧主动注入了临时内存密码并通过验证连通。

#### 标签动态重写逻辑
在前端 Store (`workbenchStore.ts`) 中，通过 `updateHostAuthTags` 动态处理标签展示：
- 静态初始状态：展示 `免密/密码认证`（中性灰底）。
- 探测确认为默认密钥：动态替换为 **`默认密钥`**（浅绿底高对比绿字）。
- 探测确认需要密码：动态替换为 **`密码认证`**（若密码被拒则为琥珀黄警示字，若验证连通则为蓝紫字）。

### 3.3 终端连接与 PTY WebSocket 代理 (`main.py` & `RealXtermTerminal.vue`)

- **通信管道**：
  - 前端建立 WebSocket 连接：`/ws/terminal/{host_alias}`。
  - 后端在 `asyncssh.connect` 成功后调用 `conn.create_process(term_type="xterm-256color")` 打开具备伪终端（PTY）的交互式 Shell 进程。
- **尺寸自适应 (Terminal Resizing)**：
  - 前端基于 `@xterm/addon-fit` 计算终端行列数，监听窗口 Resize 及容器变化。
  - 通过 WebSocket 发送 JSON 控制帧：`{"type": "resize", "cols": 120, "rows": 36}`。
  - 后端接收控制帧并调用 `process.change_terminal_size(cols, rows)` 实时更新 Linux 内核 PTY 窗口大小，杜绝全屏编辑器（如 vim/nano）界面排版错乱。
- **双向数据流与编码**：
  - 纯文本数据直接作为 WebSocket text 消息透传。
  - 默认环境变量注入 `LANG=en_US.UTF-8` 或继承远端环境变量，确保 UTF-8 字符（中文、Emoji、Nerd Fonts 符号）正常呈现。

### 3.4 本地元数据存储与零凭据铁律 (`db.py`)

- **数据库路径**：`backend/termforyou.sqlite3`。
- **职责范围**：
  - `system_settings`: 全局偏好（如 `auto_probe_enabled` 自动探测开关、轮询间隔）。
  - `host_metadata`: 用户为主机附加的 UI 标签、自定义别称、分组等。
  - `command_intel`: 终端常用命令收藏、历史分析、安全警告提示规则。
- **硬性约束**：
  - 严禁向数据库添加包含 `password`、`token`、`private_key` 的表或列。
  - 所有需要持久化的主机基础通信参数（IP、Port、User、KeyPath）一律写至 `~/.ssh/config`。

### 3.5 前端全局响应式状态中枢 (`workbenchStore.ts`)

- **单一事实源 (Single Source of Truth)**：
  - `hosts: ServerHost[]`：维护全部主机状态、标签、连通性及巡检指标。
  - `sessions: TerminalSession[]`：维护所有已打开的终端标签页（包含独立 SSH 连接实例）。
  - `activeHostAlias` / `activeSessionId`：决定中央视图渲染与底部 Dock 联动。
  - `autoProbeEnabled`: 控制全局探针轮询定时器。
- **跨组件联动**：
  - `TopSessionBar.vue`：快速在多个主机的活动终端间无缝切换，支持创建新会话与关闭会话。
  - `MiniHudBar.vue`：实时展示当前主机的 CPU、内存利用率进度条与告警状态。
  - `BottomTerminalDock.vue`：全局可随时呼出/折叠的底部迷你终端，支持多标签。
  - `CommandPaletteModal.vue` (`Cmd+K`)：全局命令看板，支持模糊搜索主机、直达视图或快速执行常用运维指令。

---

## 4. UI/UX 与双主题适配规范 (Tailwind CSS v4)

本项目对浅色（Light）与深色（Dark）模式的视觉质感与可读性有极高要求，所有后续 UI 改动必须严格遵守：

1. **WCAG AAA 高对比度原则**：
   - **浅色模式**：必须采用**浅色背景搭配深色文字/边框**，杜绝浅灰、白色文字出现在浅色底上。
   - **深色模式**：必须采用**深色背景搭配高明度高对比度文字**。
2. **状态指示与徽章配色标准**：
   - **连通 / 默认密钥 (Success/Emerald)**：
     - 浅色：`bg-emerald-500/15 text-emerald-700 border-emerald-500/30`
     - 深色：`dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/40`
   - **认证失败 / 警示 (Warning/Amber)**：
     - 浅色：`bg-amber-500/15 text-amber-800 border-amber-500/40`
     - 深色：`dark:bg-amber-500/20 dark:text-amber-200 dark:border-amber-500/40`
   - **离线 / 危险 (Danger/Rose)**：
     - 浅色：`bg-rose-500/15 text-rose-700 border-rose-500/30`
     - 深色：`dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-500/40`
   - **特定密钥 / 信息 (Info/Sky or Indigo)**：
     - 浅色：`bg-sky-500/15 text-sky-700 border-sky-500/30`
     - 深色：`dark:bg-sky-500/20 dark:text-sky-300 dark:border-sky-500/40`
3. **交互控件文字可视性**：
   - 开关（Switch）、按钮（Button）在处于 Active / On 状态时，文字必须清晰可辨。切忌因父级 `text-white` 或主题变更导致浅色模式下文字泛白。

---

## 5. 高频开发任务规范与避坑指南

### 5.1 为主机增加新维度指标采集
1. 在 `backend/metrics_collector.py` 的 `fetch_full_inspection` 中合并执行指令。**尽量使用一次 SSH 会话批量执行并用分割符（Delimiter）切分**，避免建立多次 TCP 握手。
2. 指令必须具备兼容性，兼顾 Alpine (Busybox)、CentOS、Debian/Ubuntu，避免使用非标准专有命令。
3. 返回数据在 `backend/models.py` 定义 Pydantic 模型并在 `src/types/index.ts` 声明对应 TypeScript 接口。
4. 前端 Store 赋值时做好字段缺失防护（Optional Chaining `?.` 与默认空数组/空对象）。

### 5.2 终端中文与特殊符号乱码排查
- 远端服务器若未配置 UTF-8 locale，执行某些命令可能出现菱形问号或乱码。
- 在 `asyncssh.connect` 建立环境时，通过 `env={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}` 传递语言环境变量。

### 5.3 密码认证与内存生命周期传递
- 前端输入密码后，调用 `POST /api/v1/ssh/credentials/{host_alias}` 提交至后端。
- 后端缓存在 `HostMetricsService._runtime_passwords` 字典中。
- 随后触发一次探测；一旦探测成功，立即重写前端认证标签。**注意：绝不能将该密码写入 SQLite**。

### 5.4 进程守护与热更新开发规范
- 前端运行在 Vite 开发服务器（默认端口 `5173`）。
- 后端运行在 Uvicorn（带 `--reload`，默认端口 `8000`）。
- 修改后端 Python 文件时，Uvicorn 会自动重载；但修改了依赖需在 `backend/.venv` 中通过 `pip install` 同步。

---

## 6. 质量验证与构建工作流

每次功能开发或代码修改完成后，必须完成以下验证闭环：

### 6.1 前端类型与构建校验
```bash
# 必须保证 vue-tsc 与 vite build 零错误、零警告退出
pnpm run build
```

### 6.2 后端接口与探测验证
```bash
# 验证探测接口正常且 auth_method 字段符合预期
curl -s -X POST http://127.0.0.1:8000/api/v1/ssh/probe-all | jq .
```

### 6.3 视觉与双主题无损验证
利用系统 Headless Chrome 或相关无头浏览器截屏，分别验证浅色模式与深色模式下的渲染效果：
```bash
# 浅色模式截屏验证
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --screenshot=/tmp/verify_light.png --window-size=1440,900 http://localhost:5173/

# 深色模式截屏验证
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --screenshot=/tmp/verify_dark.png --blink-settings=forceDarkModeEnabled=true --window-size=1440,900 http://localhost:5173/
```

### 6.4 Git 提交规范
使用语义化 Conventional Commits 格式：
- `feat(...)`: 新功能
- `fix(...)`: 修复问题
- `refactor(...)`: 重构逻辑
- `style(...)`: 纯 UI 样式与主题对比度优化
- `docs(...)`: 文档更新
