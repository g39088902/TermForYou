# TermForYou - Developer & Agent Guide (AGENTS.md)

> 面向参与本项目迭代的 AI Agents 与开发者。第 1、4 节为必须遵守的红线。产品范围与进度见 `docs/PRD.md`。

---

## 1. 架构红线

1. **零凭据持久化**
   - 严禁把明文密码、私钥口令写入 SQLite、本地文件、环境变量、LocalStorage / IndexedDB。
   - 密码仅存后端内存字典（`metrics_service.set_credential`）或前端会话内存，重启/刷新即失效。
   - LocalStorage 只允许存非敏感偏好（现有：`color-scheme`、`termforyou_auto_probe`、`termforyou_file_bookmarks`）。
2. **原生 SSH 配置优先**
   - 唯一主机来源是本机 `~/.ssh/config`，新增/修改/删除必须写回该文件。
   - 写入主机块时 **`User` 必须在 `HostName` 之前**。
3. **免 Agent**
   - 不在目标机安装常驻进程；信息通过单次 SSH 会话批量执行标准命令获取。
   - 远端采集和文件操作脚本依赖目标机的 `python3`（见 `metrics_collector.py`），新增采集逻辑要兼容 Ubuntu/Debian/CentOS/Alpine，并对缺失命令降级。
4. **远端写操作必须安全**
   - 拼接到远端 shell 的路径、容器名等一律校验或 `shlex.quote`（参考 `remove_docker_container` 的名称白名单）。
   - `sudo` 提权默认关闭，只能由用户显式勾选，禁止按路径自动开启。
   - 删除类操作必须有确认对话框。

---

## 2. 技术栈与结构

| 层 | 技术 |
| :--- | :--- |
| 前端 | Vue 3 + Vite 6 + Tailwind CSS v4 + TypeScript；状态是 `src/stores/workbenchStore.ts` 中的 `reactive` 单例（**未使用 Pinia**） |
| 终端 | `@xterm/xterm` + `@xterm/addon-fit`（组件 `components/terminal/RealXtermTerminal.vue`） |
| 后端 | Python 3.10+ FastAPI + `asyncssh`，标准库 `sqlite3` |
| 存储 | `backend/termforyou.sqlite3`，目前仅 `host_stats`（连接次数、最后连接时间） |

```
前端 :5173 ──HTTP /api/v1/ssh/*──▶ FastAPI :8000 ──asyncssh──▶ 远端 Linux
          ──WS /ws/terminal/{alias}─▶
```

- 后端地址在前端写死为 `http://127.0.0.1:8000`。
- 终端 WebSocket 为 JSON 帧：客户端 `auth`（首帧，含 cols/rows/term/可选密码）、`stdin`、`resize`（`payload: {cols, rows}`）、`ping`；服务端 `stdout`、`stderr`、`auth_required`、`pong`。
- 页面 ID：`P0_HOSTS`、`P1_WORKBENCH`、`P2_METRICS_PROCESS`、`P3_FILES`、`P4_COMMANDS`、`P5_DOCKER`、`P6_SYSTEMD`、`P7_CRON`、`P8_FIREWALL`。
- 新增后端能力时，同步更新 `backend/models.py`、`src/types/index.ts` 与 `docs/PRD.md`。

---

## 3. 开发规范

### 3.1 认证方式三态（`auth_method`）
- `custom_key`：`~/.ssh/config` 显式配置了 `IdentityFile`。
- `default_key`：未配置 `IdentityFile`，但默认密钥或 `ssh-agent` 握手成功。
- `password`：免密被拒（`auth_failed`）或通过临时密码握手成功。
- 前端标签：初始「免密/密码认证」→ 探测后「默认密钥」或「密码认证」。

### 3.2 终端视口
- 行数按真实 DOM 行高（≥ 18.5px）取整铺满可用高度，分数余量由状态栏/Copilot 栏吸收，不得截断最后一行。
- 容器使用 `flex-1 min-h-0 w-full`，避免 `h-full` 造成溢出。
- 保持 `.xterm .xterm-scrollable-element { height: 100% !important; }`，消除 xterm 6 在 macOS 下的底部缝隙。
- 仅当用户已在底部时才自动跟随滚动；用户向上翻看历史时不得强制拉回底部。
- 通过 `resize` 帧同步远端 PTY 尺寸；终端环境强制 `LANG=en_US.UTF-8`。

### 3.3 UI 与主题
- 颜色走 WCAG AAA：浅色模式浅底深字，深色模式深底亮字。
- 状态徽章：成功 Emerald、警示 Amber、错误 Rose、信息 Sky，均用 `bg-{c}-500/15`，文字浅色用 `-700`（Amber 用 `-800`）、深色用 `-300`（Amber 用 `-200`）。
- 列表类视图：不要给默认项预设「选中/悬停」外观；只有用户操作后才出现选中态；可交互行需支持键盘（Tab/方向键/Enter/空格）。

---

## 4. 交互铁律

1. **静默生效**：底层修复（视口、防抖、重连等）不得在界面加「已修复」「保护已生效」之类提示。
2. **终端外输入框只做 AI Copilot**：用于把自然语言转成命令；不得再做重复原生命令输入的框。
3. **临时密码**：前端 POST 到 `/api/v1/ssh/credentials/{host_alias}`，只进后端内存，禁止写库。

---

## 5. 验证与提交

每次修改后：

```bash
# 1. 前端类型检查 + 构建，必须零错误
pnpm run build

# 2. 后端启动后做接口冒烟（需先运行 uvicorn）
curl -s http://127.0.0.1:8000/api/v1/ssh/hosts | jq 'length'
curl -s -X POST http://127.0.0.1:8000/api/v1/ssh/probe-all | jq .

# 3. 改动 UI 时做深浅主题截图（需先运行 pnpm run dev）
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --screenshot=/tmp/verify_light.png --window-size=1440,900 http://localhost:5173/
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --screenshot=/tmp/verify_dark.png --blink-settings=forceDarkModeEnabled=true --window-size=1440,900 http://localhost:5173/
```

- 仓库暂无自动化测试，改动后端逻辑时请手动对真实/测试主机验证。
- 提交遵循 Conventional Commits（`feat` / `fix` / `refactor` / `style` / `docs`）。
- `*.sqlite*`、`dist/` 已被 `.gitignore` 忽略，不要提交。
