# TermForYou

> 以终端为中心的高性能、轻量化服务器可视化运维工作台。  
> 拒绝臃肿监控全家桶，开箱即用，原生解析本机 `~/.ssh/config`，严格零凭据持久化存储。

---

## 🌟 核心特性

- 🖥️ **以终端为中心 (Terminal-First)**: 集成 `@xterm/xterm` 与 Python `asyncssh` PTY WebSocket 实时直连。
- ⚡ **原生 SSH 配置感知**: 自动解析本地 `~/.ssh/config`，无感同步已知主机、别名与密钥认证。
- 🔒 **严格零凭据持久化 (Zero-Storage)**: 前后端绝不持久化任何密码与私钥，非密钥主机仅于内存会话中临时传递。
- 🎨 **自适应设计系统**: 基于 Vue 3 + Tailwind CSS v4 与 CSS `light-dark()` 规范，完美支持深浅主题无缝切换与系统偏好同步。
- 🗂️ **顶天立地功能导航**: 左侧核心全局导航，支持多标签会话切换与全屏工作流。

---

## 🏗️ 架构概览

```
Frontend (Vue 3 + Vite + Tailwind v4 + xterm.js)
  │
  ├── HTTP REST  ──> FastAPI (:8000/api/hosts) 读取本地 ~/.ssh/config 主机池
  │
  └── WebSocket  ──> FastAPI (:8000/ws/terminal/{host_alias})
                        │
                        └── asyncssh PTY (直接建立 SSH 管道直连远端目标服务器)
```

---

## 🚀 快速启动

### 1. 运行后端 (Python FastAPI + asyncssh)

```bash
cd backend

# 创建并激活虚拟环境 (可选/推荐)
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务 (默认监听 127.0.0.1:8000)
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. 运行前端 (Vue 3 + Vite)

```bash
# 安装前端依赖 (使用 pnpm)
pnpm install

# 启动开发服务器
pnpm run dev
```

浏览器访问 `http://localhost:5173` 即可开始使用。

---

## 📦 项目结构

```
TermForYou/
├── backend/
│   ├── main.py               # FastAPI 服务入口与 WebSocket PTY 代理
│   ├── models.py             # 数据模型 (HostInfo 等)
│   ├── ssh_config_parser.py  # ~/.ssh/config 原生解析器
│   └── requirements.txt      # Python 依赖清单
├── src/
│   ├── components/
│   │   ├── layout/           # 侧边栏导航、顶栏会话切换、HUD 面板
│   │   └── terminal/         # xterm.js 终端、分屏与虚拟终端组件
│   ├── views/                # 主机池、命令提炼、Docker、文件管理等视图
│   ├── stores/               # 状态管理
│   ├── services/             # API 请求与 WebSocket 客户端
│   ├── types/                # TypeScript 类型定义
│   ├── App.vue
│   └── main.ts
├── docs/
│   └── PRD.md                # 完整产品需求规格说明书
├── package.json
└── vite.config.ts
```

---

## 📄 开源许可

本项目遵循 MIT 开源协议。
