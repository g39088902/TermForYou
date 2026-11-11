# TermForYou

> 以终端为中心的轻量服务器可视化运维工作台。直接读取本机 `~/.ssh/config`，免 Agent，零凭据持久化。

## 核心特性

- **终端优先**：`@xterm/xterm` + 后端 `asyncssh` PTY，经 WebSocket 实时直连。
- **原生 SSH 配置**：`~/.ssh/config` 是唯一主机来源，新增/删除主机直接写回该文件。
- **零凭据持久化**：密码只存在后端内存，重启即失效；SQLite 仅记录连接次数等非敏感元数据。
- **免 Agent 可视化运维**：通过单次 SSH 会话批量采集，覆盖性能与进程、文件管理、Docker、Systemd、Cron、防火墙，并提供命令提炼与 AI Copilot 命令生成（目前为前端启发式，尚未接入真实 LLM）。
- **深浅双主题**：Tailwind CSS v4，跟随系统偏好，可手动切换。

## 架构

```
Vue 3 + Vite + Tailwind v4 + xterm.js   (:5173)
  ├─ HTTP REST  → FastAPI  http://127.0.0.1:8000/api/v1/ssh/*
  └─ WebSocket  → FastAPI  ws://127.0.0.1:8000/ws/terminal/{host_alias}
                      └─ asyncssh → 远端 Linux（PTY / 批量命令）
```

前端把后端地址写死为 `http://127.0.0.1:8000`，后端需监听该地址。

## 环境要求

- Node.js 20+ 与 pnpm
- Python 3.10+
- **远端主机**：Linux，需有 `python3`（巡检与文件管理依赖它执行采集脚本）；`sudo` 相关功能需要免密 sudo 或交互授权；Docker/ufw 等信息仅在远端已安装时可用。

## 快速启动

```bash
# 后端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 前端（另开终端，在仓库根目录）
pnpm install
pnpm run dev        # http://localhost:5173
pnpm run build      # 类型检查 + 生产构建
```

## 项目结构

```
backend/
  main.py               FastAPI 路由与终端 WebSocket
  metrics_collector.py  单会话批量采集、文件/Docker 操作
  probe_service.py      连通性与认证方式探测
  ssh_config_parser.py  ~/.ssh/config 读写
  db.py / models.py     SQLite（host_stats）与 Pydantic 模型
src/
  views/                P0 主机池 ~ P8 各功能页面
  components/           layout（导航/会话栏/HUD/编辑器抽屉）、terminal（xterm 封装）
  stores/workbenchStore.ts   全局状态（Vue reactive）与所有 API 调用
  services/commandExtractor.ts  历史命令提炼
  types/                TypeScript 类型
docs/PRD.md             产品需求与进度
AGENTS.md               开发规范与架构红线
```

## 安全须知

- 本工具面向**本机单用户**使用，后端无登录鉴权，CORS 全放开，请只监听 `127.0.0.1`，不要暴露到公网。
- 当前 SSH 连接**未校验 `known_hosts`**（`known_hosts=None`），存在中间人风险，详见 [PRD](docs/PRD.md) 的待办。
- 文件管理、Docker 删除等为真实的远端写操作，删除不可逆。

## 许可

计划采用 MIT 协议，仓库暂未附带 `LICENSE` 文件。
