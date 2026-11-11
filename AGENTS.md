# TermForYou - Developer & Agent Architecture Guide (AGENTS.md)

> 本文档面向参与 **TermForYou** 项目迭代的 AI Agents 与开发者。核心规范与架构红线必须无条件严格遵守。

---

## 1. 核心哲学与架构红线

1. **严格零凭据持久化 (Zero-Storage Security)**
   - 严禁在 SQLite、本地文件、环境变量或前端持久化存储（LocalStorage / IndexedDB）中写入明文密码或私钥。
   - 密码认证主机仅允许**内存临时凭据**在后端生命周期或前端会话中流转，刷新或重启后即刻蒸发。
2. **原生 SSH 配置感知与透明同步 (Native SSH First)**
   - 唯一配置源为本机 `~/.ssh/config`，新增/修改必须写回此文件。
   - 写入新主机块时，**必须严格保证 `User` 在 `HostName`（IP）之前**。
3. **轻量非侵入式 (Agentless)**
   - 目标机无需安装常驻 Agent，所有硬件指标、系统服务、Docker 与安全规则均通过单次 SSH 会话批量执行标准命令解析获取。

---

## 2. 系统架构与通信拓扑

| 模块 | 技术选型 | 职责说明 |
| :--- | :--- | :--- |
| **前端** | Vue 3 + Vite 6 + Pinia + Tailwind v4 | 响应式工作台、多会话状态中枢 (`workbenchStore.ts`) |
| **终端仿真** | `@xterm/xterm` + `FitAddon` + `WebLinksAddon` | 高性能 Canvas 渲染，WebSocket 伪终端 (PTY) |
| **后端** | Python 3.10+ FastAPI + `asyncssh` | 异步 SSH2 协议、PTY 会话代理、指令巡检探针 |
| **元数据存储** | SQLite (`backend/termforyou.sqlite3`) | **仅存储**用户设置、标签、命令 Intel 等非敏感元数据 |

```
前端 (Vue 3 + Tailwind v4 + xterm.js)
  │ WebSocket: /ws/terminal/{alias} (双向 PTY 输入输出流 + resize 信号)
  │ HTTP REST: /api/v1/ssh/*, /api/v1/hosts/* (探针/指标/配置同步/密码临时验证)
  ▼
FastAPI + asyncssh
  ├─ ssh_config_parser (双向读写 ~/.ssh/config)
  ├─ probe_service & metrics_collector (单会话多指标批量采集)
  └─ SQLite (termforyou.sqlite3 - 仅非敏感偏好)
  ▼ SSH 2.0 (Port 22/自定义)
远端 Linux 群 (CentOS / Ubuntu / Debian / Alpine)
```

---

## 3. 核心机制与开发规范

### 3.1 探针巡检与认证三态推导
- **认证方式识别 (`auth_method`)**：
  - `custom_key`: `~/.ssh/config` 显式配置 `IdentityFile`。
  - `default_key`: 未配置 `IdentityFile`，但通过本机默认密钥（`id_rsa`, `id_ed25519` 或 `ssh-agent`）握手成功。
  - `password`: 免密被拒（`auth_failed: true`）或通过运行时临时密码握手成功。
- **动态标签更新**：`workbenchStore.ts` 动态映射：`免密/密码认证`（初始）→ `默认密钥`（绿）或 `密码认证`（黄/紫）。
- **指标批量采集**：在 `metrics_collector.py` 中用分隔符拼装单条执行流，兼容标准 Linux 与 Alpine，输出映射至 Pydantic 与 TypeScript 接口。

### 3.2 终端仿真与视口对齐规范
- **尺寸解算规范**：行数解算以真实 DOM 渲染行高（$\ge 18.5\text{px}$）为基准铺满可用高度，消除外部僵死空白，确保向下滚动全屏显示 log。容器采用 `flex-1 min-h-0 w-full`，杜绝 `h-full` 造成的物理溢出。
- **Mac/多端滚动视口贴合**：针对 xterm 6.0 内部机制，强制 `.xterm .xterm-scrollable-element` 具备 `height: 100% !important;`，消除 macOS/各平台下由于 `xterm-scrollable-element` 内联像素赋值与 `.xterm-viewport` 测量尺寸不一致导致的下挂缝隙，使两者底边恒为 $0\text{px}$ 误差完全贴合。
- **系统终端级滚动体验**：仅当用户处于最底端时新数据自动跟随滚动到底部；若用户主动向上滚动使输入区居中或查看历史日志，绝不强行拽到底部打断用户。
- **PTY 同步**：通过 `{"type": "resize", "cols": n, "rows": m}` 实时调整远端内核 PTY；环境变量强制注入 `LANG=en_US.UTF-8`。

### 3.3 UI/UX 与双主题标准 (Tailwind CSS v4)
- **WCAG AAA 高对比度原则**：
  - 浅色模式：浅底深字，杜绝白字浅灰；深色模式：深底高亮字。
  - 连通/成功 (Emerald): `bg-emerald-500/15 text-emerald-700` (深色: `text-emerald-300`)
  - 警示/未连通 (Amber): `bg-amber-500/15 text-amber-800` (深色: `text-amber-200`)
  - 离线/错误 (Rose): `bg-rose-500/15 text-rose-700` (深色: `text-rose-300`)
  - 信息/特定密钥 (Sky): `bg-sky-500/15 text-sky-700` (深色: `text-sky-300`)

---

## 4. 交互铁律与防坑指南

1. **静默生效，严禁自嗨式修复提示**：
   - 底层修复（如视口截断、防抖、边距修正、容错重连）必须在底层**静默生效**。
   - **绝对禁止**在界面添加“某某 Bug 已修复”、“视界保护已生效”等技术细节告示或徽章。
2. **杜绝冗余交互，定位 AI Copilot**：
   - 终端的首要交互是黑屏键盘直接输入；严禁在外部设计重复敲原生命令的独立输入框。
   - 终端外部输入框**仅作为自然语言 AI 生成命令 Copilot**，辅助转化运维意图为可执行命令。
3. **密码临时生命周期**：
   - 前端提交临时密码至 `/api/v1/ssh/credentials/{host_alias}`，仅存内存字典，禁止写库。

---

## 5. 质量验证与构建工作流

每次修改必须执行并全绿通过：

```bash
# 1. 前端构建校验 (零错误、零警告)
pnpm run build

# 2. 探测与后端接口校验
curl -s -X POST http://127.0.0.1:8000/api/v1/ssh/probe-all | jq .

# 3. 双主题无损视觉校验 (无头截屏)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --screenshot=/tmp/verify_light.png --window-size=1440,900 http://localhost:5173/
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --screenshot=/tmp/verify_dark.png --blink-settings=forceDarkModeEnabled=true --window-size=1440,900 http://localhost:5173/

# 4. Git 规范: Conventional Commits (feat, fix, refactor, style, docs)
```
