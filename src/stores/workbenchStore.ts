import { reactive, computed, watch } from 'vue'
import type {
  PageId,
  ServerHost,
  SavedSnippet,
  ExtractedCommandCluster,
  FileEntry,
  DiskUsageItem,
  ProcessItem,
  ProcessSignal,
  ProcessActionResponse,
  CronTaskItem,
  ServerTimezone,
  SystemdServiceItem,
  DockerContainerItem,
  DockerActionResponse,
  DockerContainerAction,
  FirewallRuleItem,
  CrossModuleLinkPayload
} from '@/types'
import { extractParameterizedClusters, computeCommandPrefixStats } from '@/services/commandExtractor'

const INITIAL_HISTORY_LINES: string[] = [
  'docker logs -f --tail 100 nginx-gateway',
  'docker logs -f --tail 200 api-core-prod',
  'docker logs -f --tail 50 redis-cache-01',
  'docker logs -f --tail 500 worker-celery',
  'journalctl -u nginx.service -n 100 --no-pager',
  'journalctl -u termforyou-agent.service -n 200 --no-pager',
  'journalctl -u mysql.service -n 50 --no-pager',
  'sudo ufw allow from 10.16.0.0/16 to any port 5432 proto tcp',
  'sudo ufw allow from 192.168.10.25 to any port 6379 proto tcp',
  'sudo ufw allow from 172.18.0.0/24 to any port 3306 proto tcp',
  'find /var/log/nginx -name "*.log" -mtime +7',
  'find /opt/app/logs -name "*.gz" -mtime +30',
  'find /tmp/uploads -name "*.tmp" -mtime +3',
  'systemctl restart nginx.service',
  'systemctl restart api-core.service',
  'systemctl status redis-server.service',
  'ss -tulnp | grep 8080',
  'ss -tulnp | grep 6379',
  'ss -tulnp | grep 3306',
  'ls -la',
  'cd /etc/nginx',
  'pwd'
]

export const store = reactive({
  // 当前主页面路由 (默认进入主机连接池页面)
  activePage: 'P0_HOSTS' as PageId,

  // 色彩模式状态 ('light dark' 跟随系统 | 'light' 白天模式 | 'dark' 暗黑模式)
  colorSchemePref: (typeof window !== 'undefined'
    ? (localStorage.getItem('color-scheme') as 'light' | 'dark' | null) ?? 'light dark'
    : 'light dark') as 'light dark' | 'light' | 'dark',
  systemIsDark:
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : true,

  // 已打开的服务器会话 Tabs (初始未连接任何服务器)
  openHostIds: [] as string[],
  activeHostId: '',

  // 终端自动同步文件管理器路径 (Follow CWD)
  followCwd: true,

  // 跨模块跳转上下文胶囊横幅
  lastJumpContext: null as CrossModuleLinkPayload | null,

  // 全局 Toast 通知
  toastMessage: '' as string,

  // 右侧文件代码编辑器抽屉状态
  editorDrawer: {
    open: false,
    loading: false,
    saving: false,
    filePath: '',
    content: '',
    sudoWrite: false,
    reloadServiceHint: ''
  },

  // 远程文件管理加载状态与目录体积分析 (ncdu)
  filesLoading: false,
  filesError: '' as string,
  showHiddenFiles: true,
  dirDiskUsage: {
    loading: false,
    cwd: '',
    totalBytes: 0,
    items: [] as DiskUsageItem[]
  },
  dirSizes: {} as Record<string, number>, // 缓存各目录绝对路径对应的真实磁盘占用 (bytes)
  calculatingDirs: [] as string[], // 当前正在单独计算体积的目录路径
  autoCalculateDirSizes: true, // 访问目录时是否自动在后台非阻塞异步测算子目录真实占用

  // 全局命令面板 (Cmd+K) 与参数化命令执行弹窗控制
  commandPaletteOpen: false,
  paramModal: {
    open: false,
    snippet: null as SavedSnippet | null,
    values: {} as Record<string, string>
  },

  // 服务器主机池 (初始为空，从后端 ~/.ssh/config 异步加载真实配置)
  hosts: [] as ServerHost[],

  // 主机连接池开机状态与探测控制
  autoProbeEnabled: typeof window !== 'undefined'
    ? localStorage.getItem('termforyou_auto_probe') !== 'false'
    : true,
  isProbingAll: false,

  // 原始历史命令池（用于 AST 骨架提炼）
  rawHistoryLines: [...INITIAL_HISTORY_LINES],

  // 常用命令库 (Snippets)
  savedSnippets: [
    {
      id: 'snip-1',
      title: '实时追踪容器尾部日志',
      category: 'Docker 运维',
      commandTemplate: 'docker logs -f --tail {{lines:100}} {{container_name:nginx-gateway}}',
      description: '按指定行数实时流式查看指定容器的 stdout/stderr 日志',
      variables: [
        { name: 'lines', defaultValue: '100', description: '尾部显示行数', options: ['50', '100', '200', '500'] },
        {
          name: 'container_name',
          defaultValue: 'nginx-gateway',
          description: '目标 Docker 容器名称',
          options: ['nginx-gateway', 'api-core-prod', 'redis-cache-01', 'postgres-exporter']
        }
      ],
      scope: 'global',
      usageCount: 42,
      source: 'auto-extracted'
    },
    {
      id: 'snip-2',
      title: '反查指定端口占用的进程与 PID',
      category: '网络与端口排查',
      commandTemplate: 'ss -tulnp | grep :{{port:8080}}',
      description: '快速定位监听特定 TCP/UDP 端口的进程名与 PID',
      variables: [
        { name: 'port', defaultValue: '8080', description: '要排查的端口号', options: ['80', '443', '3306', '6379', '8080'] }
      ],
      scope: 'global',
      usageCount: 31,
      source: 'manual'
    },
    {
      id: 'snip-3',
      title: '查找大文件并按大小降序排列',
      category: '日志与文件分析',
      commandTemplate: 'find {{target_dir:/var/log}} -type f -size +{{min_size:50M}} -exec ls -lh {} + | sort -k 5 -rh',
      description: '磁盘告警时快速定位指定目录下超过阈值的大文件',
      variables: [
        { name: 'target_dir', defaultValue: '/var/log', description: '扫描起始目录', options: ['/var/log', '/opt', '/var/lib/docker'] },
        { name: 'min_size', defaultValue: '50M', description: '最小文件体积', options: ['10M', '50M', '100M', '500M'] }
      ],
      scope: 'global',
      usageCount: 19,
      source: 'manual'
    },
    {
      id: 'snip-4',
      title: 'UFW 放行指定内网网段访问端口',
      category: '网络与端口排查',
      commandTemplate: 'sudo ufw allow from {{ip_cidr:10.16.0.0/16}} to any port {{port:5432}} proto tcp comment "{{comment:Internal DB}}"',
      description: '由防火墙可视化向导保存的白名单放行指令',
      variables: [
        { name: 'ip_cidr', defaultValue: '10.16.0.0/16', description: '允许的来源 IP 或 CIDR 网段' },
        { name: 'port', defaultValue: '5432', description: '放行端口' },
        { name: 'comment', defaultValue: 'Internal DB', description: '规则备注' }
      ],
      scope: 'prod-web-01',
      usageCount: 12,
      source: 'gui-saved'
    }
  ] as SavedSnippet[],

  // 文件系统模拟数据
  files: [
    {
      name: 'nginx.conf',
      path: '/etc/nginx/nginx.conf',
      isDir: false,
      sizeBytes: 2641,
      permissions: '-rw-r--r--',
      octal: '0644',
      owner: 'root',
      group: 'root',
      modifiedAt: '2026-11-09 18:12',
      content: `user www-data;
worker_processes auto;
pid /run/nginx.pid;

events {
    worker_connections 4096;
    multi_accept on;
}

http {
    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    include /etc/nginx/mime.types;

    upstream api_backend {
        server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
    }

    server {
        listen 80;
        server_name termforyou.internal;
        location / {
            proxy_pass http://api_backend;
        }
    }
}`
    },
    {
      name: 'conf.d',
      path: '/etc/nginx/conf.d',
      isDir: true,
      sizeBytes: 4096,
      permissions: 'drwxr-xr-x',
      octal: '0755',
      owner: 'root',
      group: 'root',
      modifiedAt: '2026-11-10 09:20'
    },
    {
      name: 'docker-compose.yml',
      path: '/opt/stacks/gateway/docker-compose.yml',
      isDir: false,
      sizeBytes: 1820,
      permissions: '-rw-r--r--',
      octal: '0644',
      owner: 'root',
      group: 'docker',
      modifiedAt: '2026-11-08 14:30',
      content: `services:
  nginx-gateway:
    image: nginx:1.27-alpine
    container_name: nginx-gateway
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /etc/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /var/log/nginx:/var/log/nginx

  redis-cache-01:
    image: redis:7.4-alpine
    container_name: redis-cache-01
    restart: always
    ports:
      - "6379:6379"
    volumes:
      - /var/lib/docker/volumes/redis_data/_data:/data`
    },
    {
      name: 'backup_db.sh',
      path: '/opt/scripts/backup_db.sh',
      isDir: false,
      sizeBytes: 940,
      permissions: '-rwxr-xr-x',
      octal: '0755',
      owner: 'root',
      group: 'root',
      modifiedAt: '2026-11-07 02:00',
      content: `#!/usr/bin/env bash
set -euo pipefail
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="/var/backups/postgres"
mkdir -p "$BACKUP_DIR"
pg_dump -U postgres -h 127.0.0.1 app_prod | gzip > "$BACKUP_DIR/app_prod_$TIMESTAMP.sql.gz"
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +7 -delete
echo "[OK] Backup finished at $TIMESTAMP"`
    },
    {
      name: 'api-core.service',
      path: '/etc/systemd/system/api-core.service',
      isDir: false,
      sizeBytes: 612,
      permissions: '-rw-r--r--',
      octal: '0644',
      owner: 'root',
      group: 'root',
      modifiedAt: '2026-11-05 16:40',
      content: `[Unit]
Description=TermForYou Core API Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/api-core
ExecStart=/opt/api-core/bin/server --port 8080 --env prod
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target`
    }
  ] as FileEntry[],

  // Only actual process snapshots may be used as signal targets.
  processes: [] as ProcessItem[],
  processesLoading: false,
  processesError: '',
  processActions: {} as Record<string, ProcessSignal>,

  // 当前服务器的计划任务；切换时清空，等待真实巡检结果。
  cronTasks: [] as CronTaskItem[],
  cronTasksLoading: false,
  cronTasksError: '',
  // 服务器时区；crontab 按服务器本地时间触发，视图据此换算北京时间。
  serverTimezone: null as ServerTimezone | null,

  // Systemd 系统服务列表
  systemdServices: [
    {
      name: 'nginx.service',
      description: 'A high performance web server and a reverse proxy server',
      state: 'running',
      enabled: true,
      pid: 1042,
      memoryMb: 342,
      uptime: '48d 14h',
      unitFilePath: '/lib/systemd/system/nginx.service',
      workingDir: '/etc/nginx',
      execStart: '/usr/sbin/nginx -g "daemon on; master_process on;"',
      restartPolicy: 'on-failure',
      recentLogs: [
        'Nov 10 09:20:01 prod-web-01 systemd[1]: Reloaded A high performance web server.',
        'Nov 10 11:02:44 prod-web-01 nginx[1042]: 2026/11/10 11:02:44 [notice] signal 1 (SIGHUP) received'
      ]
    },
    {
      name: 'api-core.service',
      description: 'TermForYou Core API Service (Go Backend)',
      state: 'running',
      enabled: true,
      pid: 2891,
      memoryMb: 2380,
      uptime: '12d 06h',
      unitFilePath: '/etc/systemd/system/api-core.service',
      workingDir: '/opt/api-core',
      execStart: '/opt/api-core/bin/server --port 8080 --env prod',
      restartPolicy: 'always',
      recentLogs: [
        'Nov 10 11:00:00 prod-web-01 api-core[2891]: [INFO] Worker pool heartbeat OK (active=12/64)',
        'Nov 10 11:06:15 prod-web-01 api-core[2891]: [INFO] Metrics snapshot flushed in 4.2ms'
      ]
    },
    {
      name: 'celery-beat.service',
      description: 'Distributed Task Queue Periodic Scheduler',
      state: 'failed',
      enabled: true,
      memoryMb: 0,
      uptime: '已停止 (ExitCode=1)',
      unitFilePath: '/etc/systemd/system/celery-beat.service',
      workingDir: '/opt/worker',
      execStart: '/opt/worker/venv/bin/celery -A tasks beat --loglevel=INFO',
      restartPolicy: 'on-failure',
      recentLogs: [
        'Nov 10 10:42:11 prod-web-01 celery[8821]: ERROR: Pidfile (/var/run/celery/beat.pid) already exists.',
        'Nov 10 10:42:11 prod-web-01 systemd[1]: celery-beat.service: Main process exited, code=exited, status=1/FAILURE',
        'Nov 10 10:42:11 prod-web-01 systemd[1]: celery-beat.service: Failed with result "exit-code".'
      ]
    }
  ] as SystemdServiceItem[],

  // Docker 容器列表
  dockerContainers: [] as DockerContainerItem[],
  dockerContainersLoading: false,
  dockerContainersError: '',
  dockerContainerActions: {} as Record<string, DockerContainerAction>,

  // 防火墙规则列表
  firewallRules: [
    {
      id: 'fw-1',
      port: '22',
      protocol: 'tcp',
      sourceCidr: '0.0.0.0/0',
      action: 'ALLOW',
      comment: 'SSH 远程管理端口 (防锁死保护)',
      enabled: true,
      listeningProcess: { pid: 812, name: 'sshd', type: 'process' }
    },
    {
      id: 'fw-2',
      port: '80,443',
      protocol: 'tcp',
      sourceCidr: '0.0.0.0/0',
      action: 'ALLOW',
      comment: 'Nginx HTTP/HTTPS 公网入口',
      enabled: true,
      listeningProcess: { pid: 1042, name: 'nginx-gateway', type: 'docker', targetId: 'c-nginx-01' }
    },
    {
      id: 'fw-3',
      port: '6379',
      protocol: 'tcp',
      sourceCidr: '192.168.10.0/24',
      action: 'ALLOW',
      comment: 'Redis 缓存内网白名单访问',
      enabled: true,
      listeningProcess: { pid: 4120, name: 'redis-cache-01', type: 'docker', targetId: 'c-redis-01' }
    },
    {
      id: 'fw-4',
      port: '3306',
      protocol: 'tcp',
      sourceCidr: '172.18.0.0/24',
      action: 'ALLOW',
      comment: '旧版 MySQL 遗留规则 (当前无进程监听)',
      enabled: true
    }
  ] as FirewallRuleItem[]
})

const FALLBACK_EMPTY_HOST: ServerHost = {
  id: '',
  name: '未连接服务器',
  ip: '--',
  port: 22,
  user: '--',
  group: '未连接',
  status: 'unconnected',
  tags: [],
  metricsStatus: 'idle',
  connectionCount: 0
}

// 计算当前用户是否已连接任何服务器
export const hasConnectedHost = computed<boolean>(() => {
  return store.openHostIds.length > 0 && !!store.activeHostId
})

// 计算当前激活的服务器对象 (若未连接，安全回退至空对象避免空指针)
export const currentHost = computed<ServerHost>(() => {
  if (!store.activeHostId) {
    return store.hosts[0] ?? FALLBACK_EMPTY_HOST
  }
  return store.hosts.find((h) => h.id === store.activeHostId) ?? store.hosts[0] ?? FALLBACK_EMPTY_HOST
})

// 实时运行 AST 骨架聚类提炼引擎
export const extractedClusters = computed<ExtractedCommandCluster[]>(() => {
  return extractParameterizedClusters(store.rawHistoryLines)
})

// 命令前缀分布统计
export const prefixStats = computed(() => {
  return computeCommandPrefixStats(store.rawHistoryLines)
})

// 触发全局轻提示
export function showToast(msg: string) {
  store.toastMessage = msg
  setTimeout(() => {
    if (store.toastMessage === msg) {
      store.toastMessage = ''
    }
  }, 3600)
}

// 核心：跨模块上下文跳转动作
export function navigateWithContext(payload: CrossModuleLinkPayload) {
  if (!hasConnectedHost.value && payload.targetPage !== 'P0_HOSTS') {
    showToast('请先在主机连接池中连接一台服务器')
    store.activePage = 'P0_HOSTS'
    return
  }

  store.lastJumpContext = payload
  store.activePage = payload.targetPage

  if (payload.openPath) {
    currentHost.value.currentCwd = payload.openPath
    fetchRemoteDirectory(payload.openPath)
  }

  if (payload.editFilePath) {
    openFileInEditor(payload.editFilePath)
  }

  showToast(`已跨模块跳转：${payload.reason}`)
}

export interface BackendSshHost {
  id: string
  host_alias: string
  hostname: string
  user: string
  port: number
  identity_files: string[]
  proxy_jump?: string | null
  auth_hint: string
  connection_count?: number
  last_connected_at?: number | null
}

// 用户手动连接某台服务器：持久化至 SQLite 数据库并按连接次数降序重排
export async function connectHost(hostId: string) {
  const host = store.hosts.find((h) => h.id === hostId)
  if (!host) return

  // 1. 发起后端记录连接次数请求
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/hosts/${encodeURIComponent(hostId)}/connect`, {
      method: 'POST'
    })
    if (res.ok) {
      const data = await res.json()
      if (data.stat) {
        host.connectionCount = data.stat.connection_count
        host.lastConnectedAt = data.stat.last_connected_at
      }
    }
  } catch {
    host.connectionCount = (host.connectionCount || 0) + 1
    host.lastConnectedAt = Math.floor(Date.now() / 1000)
  }

  // 2. 重新按用户手动连接的次数降序排序 (若次数相同按最后连接时间降序)
  store.hosts.sort((a, b) => {
    const countDiff = (b.connectionCount ?? 0) - (a.connectionCount ?? 0)
    if (countDiff !== 0) return countDiff
    return (b.lastConnectedAt ?? 0) - (a.lastConnectedAt ?? 0)
  })

  // 3. 打开会话标签并切换至终端工作台
  if (!store.openHostIds.includes(hostId)) {
    store.openHostIds.push(hostId)
  }
  const hostChanged = store.activeHostId !== hostId
  store.activeHostId = hostId
  store.activePage = 'P1_WORKBENCH'

  // 4. 立即启动该主机的性能采集、全景数据探测与定时轮询
  startMetricsPolling()
  if (!hostChanged) void inspectHost(hostId)
  showToast(`已成功连接至「${host.name}」(${host.ip}) · 累计连接 ${host.connectionCount || 1} 次`)
}

// 从本地 Python 后端加载真实 ~/.ssh/config 主机列表 (按连接次数降序)
/**
 * 根据探测/认证真实结果，动态将模糊的“免密/密码认证”更名为“密码认证”或“默认密钥”
 */
export function updateHostAuthTags(host: ServerHost, authMethod?: string, hasPassword = false) {
  if (authMethod) {
    host.authMethod = authMethod as any
  }
  if (hasPassword) {
    host.hasCustomPassword = true
  }

  // 1. 若在 ~/.ssh/config 明确指定了密钥路径，保持专属密钥标签
  if (host.identityFiles && host.identityFiles.length > 0) {
    host.tags = ['密钥认证', ...host.identityFiles.map(k => k.split('/').pop() || 'key')]
    return
  }

  // 2. 未指定密钥时，根据真实探测结果动态更名
  const isPassword =
    host.authFailed ||
    authMethod === 'password' ||
    host.hasCustomPassword ||
    host.authMethod === 'password'

  if (isPassword) {
    host.tags = ['密码认证']
  } else if (
    authMethod === 'default_key' ||
    host.authMethod === 'default_key' ||
    (host.powerStatus === 'online' && !host.authFailed)
  ) {
    // 目标在线且非密码认证，说明系统通过全局默认私钥或 ssh-agent 成功免密接通
    host.tags = ['默认密钥']
  } else {
    // 离线或尚未探测时保留默认状态
    host.tags = ['免密/密码认证']
  }
}

export async function loadSshHostsFromBackend() {
  try {
    const res = await fetch('http://127.0.0.1:8000/api/v1/ssh/hosts')
    if (!res.ok) return
    const backendHosts: BackendSshHost[] = await res.json()
    if (backendHosts && backendHosts.length > 0) {
      store.hosts = backendHosts.map((h) => ({
        id: h.host_alias,
        name: h.host_alias,
        ip: h.hostname,
        port: h.port,
        user: h.user,
        group: '~/.ssh/config 本地配置',
        status: 'unconnected',
        identityFiles: h.identity_files,
        tags: h.identity_files.length > 0 ? ['密钥认证', ...h.identity_files.map(k => k.split('/').pop() || 'key')] : ['免密/密码认证'],
        connectionCount: h.connection_count ?? 0,
        lastConnectedAt: h.last_connected_at ?? undefined,
        metricsStatus: 'idle',
        powerStatus: 'unknown'
      }))
      // 首次加载成功后，自动执行一次全部服务器开机与连通性探测
      probeAllHosts(true)
    }
  } catch {
    // 后端未启动时静默保持现有状态
  }
}

// 持久彻底删除某台服务器配置 (从 ~/.ssh/config 与 SQLite 中同时移除)
export async function deleteHostPermanently(hostId: string): Promise<boolean> {
  const host = store.hosts.find((h) => h.id === hostId)
  const hostName = host?.name || hostId

  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/hosts/${encodeURIComponent(hostId)}`, {
      method: 'DELETE'
    })
    if (!res.ok) {
      showToast(`删除服务器失败：后端接口响应异常 (${res.status})`)
      return false
    }
  } catch {
    // 若后端连不上，提示用户
    showToast(`无法连接后端服务，暂未能从本地配置文件中物理删除`)
    return false
  }

  // 1. 从前端主机池移除
  store.hosts = store.hosts.filter((h) => h.id !== hostId)

  // 2. 清理顶栏已打开的会话标签
  store.openHostIds = store.openHostIds.filter((id) => id !== hostId)

  // 3. 如果当前处于该主机中，切回剩余会话或返回主机池
  if (store.activeHostId === hostId) {
    if (store.openHostIds.length > 0) {
      store.activeHostId = store.openHostIds[0]
    } else {
      store.activeHostId = ''
      store.activePage = 'P0_HOSTS'
    }
  }

  showToast(`已持久彻底删除服务器「${hostName}」配置`)
  return true
}

// 持久添加一台服务器配置到 ~/.ssh/config 并立即探测
export async function addHostPermanently(payload: {
  name: string
  ip: string
  port?: number
  user?: string
}) {
  const port = payload.port || 22
  const user = payload.user?.trim() || 'root'
  const alias = payload.name.trim()
  const ip = payload.ip.trim()

  try {
    const res = await fetch('http://127.0.0.1:8000/api/v1/ssh/hosts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host_alias: alias,
        hostname: ip,
        port,
        user
      })
    })
    if (res.ok) {
      showToast(`已持久添加主机「${alias}」至 ~/.ssh/config`)
    }
  } catch {
    // 忽略错误，前端先行
  }

  // 更新前端列表
  const existingIdx = store.hosts.findIndex((h) => h.id === alias)
  const newHost: ServerHost = {
    id: alias,
    name: alias,
    ip,
    port,
    user,
    group: '~/.ssh/config 本地配置',
    status: 'unconnected',
    tags: ['自定义新增'],
    metricsStatus: 'idle',
    powerStatus: 'checking',
    connectionCount: 0
  }

  if (existingIdx >= 0) {
    store.hosts[existingIdx] = newHost
  } else {
    store.hosts.unshift(newHost)
  }

  // 立即探测单台开机状态
  await probeHost(alias)
}

export interface ProbeResultItem {
  host_alias: string
  hostname: string
  port: number
  status: 'online' | 'offline'
  online: boolean
  rtt_ms: number | null
  banner: string | null
  message: string
  timestamp: number
  auth_failed?: boolean
  auth_message?: string
  auth_method?: 'password' | 'default_key' | 'custom_key'
}

// 批量并发探测所有服务器开机状态
export async function probeAllHosts(silent = false) {
  if (store.isProbingAll) return
  if (store.hosts.length === 0) return

  store.isProbingAll = true
  store.hosts.forEach((h) => {
    h.powerStatus = 'checking'
  })

  if (!silent) {
    showToast(`正在并发探测全部 ${store.hosts.length} 台服务器开机状态与全页面系统数据...`)
  }

  try {
    const res = await fetch('http://127.0.0.1:8000/api/v1/ssh/probe-all', {
      method: 'POST'
    })
    if (!res.ok) {
      throw new Error(`Probe failed with status ${res.status}`)
    }
    const data: {
      status: string
      count: number
      results: Record<string, ProbeResultItem>
      metrics?: Record<string, HostMetricsResponse>
    } = await res.json()
    const results = data.results || {}
    const metricsMap = data.metrics || {}

    let onlineCount = 0
    let authFailedCount = 0
    let offlineCount = 0

    for (const host of store.hosts) {
      const probeRes = results[host.id]
      if (probeRes) {
        host.powerStatus = probeRes.online ? 'online' : 'offline'
        host.pingMs = probeRes.rtt_ms ?? undefined
        host.sshBanner = probeRes.banner ?? undefined
        host.probeMessage = probeRes.message
        host.lastProbedAt = probeRes.timestamp ? probeRes.timestamp * 1000 : Date.now()

        const m = metricsMap[host.id]
        const authMethod = probeRes.auth_method || m?.auth_method
        const isAuthFailed = Boolean(
          probeRes.auth_failed || (m && (m.status === 'auth_failed' || m.auth_failed))
        )
        host.authFailed = isAuthFailed
        if (isAuthFailed) {
          authFailedCount++
          host.authMessage = probeRes.auth_message || m?.message || '密码错误或身份认证被拒绝 (Permission denied)'
          host.status = 'warning'
          host.metricsStatus = 'error'
        } else {
          host.authMessage = undefined
        }

        // 动态根据探测/认证结果更新卡片标签 (将“免密/密码认证”更名为“密码认证”或“默认密钥”)
        updateHostAuthTags(host, authMethod)

        if (probeRes.online && !isAuthFailed) {
          onlineCount++
          if (host.status === 'unconnected' || host.status === 'offline' || host.status === 'warning') {
            host.status = 'online'
          }

          // 同步后端并发采集的真实指标数据，填充卡片所有健康项
          if (m && m.status === 'online') {
            host.cpuUsage = m.cpuUsage
            if (m.cpuCores && m.cpuCores.length > 0) host.cpuCores = m.cpuCores
            if (m.loadAvg) host.loadAvg = m.loadAvg
            host.memUsedGb = m.memUsedGb
            host.memTotalGb = m.memTotalGb
            host.swapUsedGb = m.swapUsedGb
            host.swapTotalGb = m.swapTotalGb
            host.diskUsedPercent = m.diskUsedPercent
            if (m.diskUsedGb !== undefined) host.diskUsedGb = m.diskUsedGb
            if (m.diskTotalGb !== undefined) host.diskTotalGb = m.diskTotalGb
            if (m.diskReadKbps !== undefined) host.diskReadKbps = m.diskReadKbps
            if (m.diskWriteKbps !== undefined) host.diskWriteKbps = m.diskWriteKbps
            host.netUpKbps = m.netUpKbps
            host.netDownKbps = m.netDownKbps
            host.uptime = m.uptime
            if (m.os) host.os = m.os
            if (m.kernel) host.kernel = m.kernel
            if (m.firewallBackend) host.firewallBackend = m.firewallBackend
            if (typeof m.firewallEnabled === 'boolean') host.firewallEnabled = m.firewallEnabled
            host.metricsStatus = 'synced'
            host.lastMetricsUpdate = Date.now()
          }
        } else if (!probeRes.online) {
          offlineCount++
          host.status = 'offline'
        }
      } else {
        host.powerStatus = 'unknown'
      }
    }

    // 若当前有已激活主机，同步探测刷新其全页面数据
    if (store.activeHostId) {
      inspectHost(store.activeHostId)
    }

    if (!silent) {
      if (authFailedCount > 0) {
        showToast(`全量探测完成：${onlineCount} 台连通正常，${authFailedCount} 台因密码不对未接通，${offlineCount} 台离线`)
      } else {
        showToast(`全量探测完成：${onlineCount} 台在线（已同步全页面数据），${offlineCount} 台离线`)
      }
    }
  } catch (err) {
    store.hosts.forEach((h) => {
      if (h.powerStatus === 'checking') h.powerStatus = 'unknown'
    })
    if (!silent) {
      showToast(`探测失败：后端服务未响应`)
    }
  } finally {
    store.isProbingAll = false
  }
}

// 自动探测定时轮询控制 (每 30 秒静默探测所有服务器)
let autoProbeInterval: ReturnType<typeof setInterval> | null = null

export function initAutoProbeTimer() {
  if (autoProbeInterval) clearInterval(autoProbeInterval)
  if (store.autoProbeEnabled) {
    autoProbeInterval = setInterval(() => {
      // 当处于后台标签或非主机连接池时可静默探测
      if (typeof document !== 'undefined' && document.hidden) return
      probeAllHosts(true)
    }, 30000)
  }
}

export function toggleAutoProbe(targetState?: boolean) {
  const next = targetState !== undefined ? targetState : !store.autoProbeEnabled
  store.autoProbeEnabled = next
  if (typeof window !== 'undefined') {
    localStorage.setItem('termforyou_auto_probe', next ? 'true' : 'false')
  }
  if (next) {
    showToast('已开启自动探测：每 30 秒自动探测全部服务器开机状态')
    initAutoProbeTimer()
    probeAllHosts(false)
  } else {
    if (autoProbeInterval) {
      clearInterval(autoProbeInterval)
      autoProbeInterval = null
    }
    showToast('已停用自动探测')
  }
}

// 启动初始自动探测定时器
if (typeof window !== 'undefined') {
  initAutoProbeTimer()
}

export interface HostMetricsResponse {
  status: 'online' | 'error' | 'auth_failed'
  host_alias: string
  timestamp: number
  cpuUsage: number
  cpuCores: number[]
  loadAvg: [number, number, number]
  memUsedGb: number
  memTotalGb: number
  swapUsedGb: number
  swapTotalGb: number
  diskUsedPercent: number
  diskUsedGb?: number
  diskTotalGb?: number
  diskReadKbps?: number
  diskWriteKbps?: number
  netUpKbps: number
  netDownKbps: number
  uptime: string
  os?: string
  kernel?: string
  firewallBackend?: 'ufw' | 'firewalld' | 'iptables'
  firewallEnabled?: boolean
  message?: string
  auth_failed?: boolean
  auth_method?: 'password' | 'default_key' | 'custom_key'
}

let metricsTimer: ReturnType<typeof setInterval> | null = null
export const METRICS_POLL_INTERVAL_MS = 3000 // 默认 3 秒更新频率，轻量且实时

export async function fetchHostMetrics(hostId: string) {
  const targetHost = store.hosts.find((h) => h.id === hostId)
  if (!targetHost) return

  targetHost.metricsStatus = 'updating'
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/metrics/${encodeURIComponent(hostId)}`)
    if (!res.ok) {
      targetHost.metricsStatus = 'error'
      targetHost.status = 'offline'
      return
    }
    const data: HostMetricsResponse = await res.json()
    if (data.status === 'online') {
      targetHost.cpuUsage = data.cpuUsage
      if (data.cpuCores && data.cpuCores.length > 0) {
        targetHost.cpuCores = data.cpuCores
      }
      targetHost.loadAvg = data.loadAvg
      targetHost.memUsedGb = data.memUsedGb
      targetHost.memTotalGb = data.memTotalGb
      targetHost.swapUsedGb = data.swapUsedGb
      targetHost.swapTotalGb = data.swapTotalGb
      targetHost.diskUsedPercent = data.diskUsedPercent
      if (data.diskUsedGb !== undefined) targetHost.diskUsedGb = data.diskUsedGb
      if (data.diskTotalGb !== undefined) targetHost.diskTotalGb = data.diskTotalGb
      if (data.diskReadKbps !== undefined) targetHost.diskReadKbps = data.diskReadKbps
      if (data.diskWriteKbps !== undefined) targetHost.diskWriteKbps = data.diskWriteKbps
      targetHost.netUpKbps = data.netUpKbps
      targetHost.netDownKbps = data.netDownKbps
      targetHost.uptime = data.uptime
      if (data.os) targetHost.os = data.os
      if (data.kernel) targetHost.kernel = data.kernel
      if (data.firewallBackend) targetHost.firewallBackend = data.firewallBackend
      if (typeof data.firewallEnabled === 'boolean') targetHost.firewallEnabled = data.firewallEnabled
      targetHost.status = 'online'
      targetHost.metricsStatus = 'synced'
      targetHost.lastMetricsUpdate = Date.now()
    } else {
      targetHost.status = 'offline'
      targetHost.metricsStatus = 'error'
    }
  } catch {
    targetHost.status = 'offline'
    targetHost.metricsStatus = 'error'
  }
}

let processRequestVersion = 0
let processHostVersion = 0
let inspectionProcessVersion = 0

export async function refreshProcesses(hostId = store.activeHostId): Promise<boolean> {
  if (!hostId || hostId !== store.activeHostId) return false
  const version = ++processRequestVersion
  store.processesLoading = true
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/processes/${encodeURIComponent(hostId)}`)
    const data = await res.json()
    if (version !== processRequestVersion || store.activeHostId !== hostId) return false
    if (!res.ok || data.status !== 'ok' || !Array.isArray(data.processes)) {
      throw new Error(data.message || data.processesError || '无法读取进程列表')
    }
    store.processes = data.processes
    store.processesError = ''
    return true
  } catch (error) {
    if (version === processRequestVersion && store.activeHostId === hostId) {
      store.processes = []
      store.processesError = error instanceof Error ? error.message : '读取失败，请重试'
    }
    return false
  } finally {
    if (version === processRequestVersion && store.activeHostId === hostId) store.processesLoading = false
  }
}

export async function signalProcess(proc: ProcessItem, signal: ProcessSignal, sudo = false, hostId = store.activeHostId): Promise<boolean> {
  if (!hostId || hostId !== store.activeHostId || !proc.identity || proc.pid <= 1 || proc.state === 'Z') return false
  if (!store.processes.some(p => p.pid === proc.pid && p.identity === proc.identity)) return false
  const key = `${hostId}/${proc.pid}`
  if (store.processActions[key]) return false
  const hostVersion = processHostVersion
  store.processActions[key] = signal
  // Invalidate snapshots started before this mutation.
  ++processRequestVersion
  store.processesLoading = false
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/processes/${encodeURIComponent(hostId)}/kill`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pid: proc.pid, identity: proc.identity, signal, sudo })
    })
    const data: ProcessActionResponse = await res.json()
    const ok = res.ok && data.status === 'ok'
    if (store.activeHostId === hostId && hostVersion === processHostVersion) {
      const detail = typeof data.detail === 'string' ? data.detail : data.detail?.map(d => d.msg).join('；')
      showToast(ok ? data.message || `已向 PID ${proc.pid} 发送 ${signal}` : `操作失败：${data.message || detail || '后端服务异常'}`)
    }
    return ok
  } catch {
    if (store.activeHostId === hostId && hostVersion === processHostVersion) showToast('未能确认信号发送结果，请刷新进程状态后再操作')
    return false
  } finally {
    if (store.activeHostId === hostId && hostVersion === processHostVersion) await refreshProcesses(hostId)
    delete store.processActions[key]
  }
}

export async function restartDockerContainer(containerId: string, sudo = false): Promise<boolean> {
  return controlDockerContainer(containerId, 'restart', sudo)
}

export async function controlDockerContainer(containerId: string, action: DockerContainerAction, sudo = false): Promise<boolean> {
  const hostId = store.activeHostId
  if (!hostId) return false
  const label = { start: '启动', stop: '停止', restart: '重启' }[action]
  const key = `${hostId}/${containerId}`
  if (store.dockerContainerActions[key]) return false
  store.dockerContainerActions[key] = action
  try {
    const endpoint = action === 'restart' ? 'restart' : 'action'
    const res = await fetch(
      `http://127.0.0.1:8000/api/v1/ssh/docker/${encodeURIComponent(hostId)}/containers/${encodeURIComponent(containerId)}/${endpoint}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(action === 'restart' ? { sudo } : { action, sudo }) }
    )
    const data: DockerActionResponse = await res.json()
    if (!res.ok || data.status !== 'ok') {
      showToast(`${label}失败：${data.message || data.detail || '后端服务异常'}`)
      return false
    }
    showToast(data.message || `容器已${label}`)
    if (store.activeHostId === hostId) await inspectHost(hostId)
    return true
  } catch {
    showToast(`未能确认容器${label}结果，请刷新状态后再操作`)
    return false
  } finally {
    delete store.dockerContainerActions[key]
  }
}

export async function removeDockerContainer(containerName: string, force = false, removeVolumes = false): Promise<boolean> {
  const hostId = store.activeHostId
  try {
    const res = await fetch(
      `http://127.0.0.1:8000/api/v1/ssh/docker/${encodeURIComponent(hostId)}/containers/${encodeURIComponent(containerName)}?force=${force}&remove_volumes=${removeVolumes}`,
      { method: 'DELETE' }
    )
    const data = await res.json()
    if (data.status === 'ok') {
      store.dockerContainers = store.dockerContainers.filter(c => c.name !== containerName)
      showToast(data.message || `已删除容器 ${containerName}`)
      return true
    }
    showToast(`删除失败：${data.message || data.detail || '未知错误'}`)
  } catch (e) {
    showToast(`删除失败：${(e as Error).message}`)
  }
  return false
}

// 校验服务器与请求序号，防止过期巡检覆盖当前计划任务和容器列表。
let inspectionRequestVersion = 0

function beginInspectionLoad(hostId: string): number {
  if (store.activeHostId !== hostId) return -1
  inspectionProcessVersion = ++processRequestVersion
  store.processesLoading = true
  store.cronTasksLoading = true
  store.cronTasksError = ''
  store.dockerContainersLoading = true
  store.dockerContainersError = ''
  return ++inspectionRequestVersion
}

function finishInspectionLoad(
  hostId: string,
  version: number,
  data?: { status?: string; cronTasks?: CronTaskItem[]; dockerContainers?: DockerContainerItem[]; processes?: ProcessItem[]; processesError?: string; message?: string; timezone?: ServerTimezone }
) {
  if (version !== inspectionRequestVersion || store.activeHostId !== hostId) return
  if (inspectionProcessVersion === processRequestVersion) {
    store.processesLoading = false
    if (data?.status === 'ok' && Array.isArray(data.processes) && !data.processesError) {
      store.processes = data.processes
      store.processesError = ''
    } else {
      store.processes = []
      store.processesError = data?.processesError || data?.message || '未能读取当前服务器的进程列表，请重试'
    }
  }
  store.cronTasksLoading = false
  // 时区随巡检回包更新；回包缺失说明本次未取到，回落为未知，避免沿用上一台主机的时区。
  store.serverTimezone = data?.timezone?.utcOffset ? data.timezone : null
  if (data?.status === 'ok' && Array.isArray(data.cronTasks)) {
    store.cronTasks = data.cronTasks
    store.cronTasksError = ''
  } else {
    store.cronTasks = []
    store.cronTasksError = data?.message || '未能读取当前服务器的计划任务，请重试'
  }
  store.dockerContainersLoading = false
  if (data?.status === 'ok' && Array.isArray(data.dockerContainers)) {
    store.dockerContainers = data.dockerContainers
    store.dockerContainersError = ''
  } else {
    store.dockerContainers = []
    store.dockerContainersError = data?.message || '未能读取当前服务器的容器列表，请重试'
  }
}

type CronTaskMutationResult = {
  status?: string
  message?: string
  detail?: string
  task?: CronTaskItem
  exit_code?: number
  output?: string
}

async function cronMutationRequest(path: string, body?: Record<string, unknown>): Promise<CronTaskMutationResult | null> {
  try {
    const res = await fetch(`http://127.0.0.1:8000${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {})
    })
    const data = await res.json().catch(() => ({})) as CronTaskMutationResult
    if (!res.ok || data.status !== 'ok') {
      showToast(data.message || data.detail || `Crontab 操作失败 (HTTP ${res.status})`)
      return null
    }
    return data
  } catch {
    showToast('未能连接后端服务，Crontab 状态未改变')
    return null
  }
}

export async function createCronTask(payload: { title: string; expression: string; command: string }): Promise<boolean> {
  const hostId = store.activeHostId
  if (!hostId) return false
  const data = await cronMutationRequest(`/api/v1/ssh/cron/${encodeURIComponent(hostId)}/tasks`, payload)
  if (!data) return false
  showToast(data.message || '已写入远端 Crontab')
  await inspectHost(hostId)
  return true
}

export async function setCronTaskEnabled(task: CronTaskItem, enabled: boolean): Promise<boolean> {
  const hostId = store.activeHostId
  if (!hostId) return false
  const data = await cronMutationRequest(
    `/api/v1/ssh/cron/${encodeURIComponent(hostId)}/tasks/${encodeURIComponent(task.id)}/enabled`,
    { enabled }
  )
  if (!data) return false
  showToast(data.message || (enabled ? '已启用远端 Crontab 任务' : '已禁用远端 Crontab 任务'))
  await inspectHost(hostId)
  return true
}

export async function runCronTask(task: CronTaskItem): Promise<boolean> {
  const hostId = store.activeHostId
  if (!hostId) return false
  const data = await cronMutationRequest(
    `/api/v1/ssh/cron/${encodeURIComponent(hostId)}/tasks/${encodeURIComponent(task.id)}/run`
  )
  if (!data) return false
  const exitCode = data.exit_code ?? data.task?.lastExitCode
  showToast(exitCode === 0 ? `试运行成功：${task.title}` : `试运行结束，退出码 ${exitCode ?? '未知'}：${task.title}`)
  await inspectHost(hostId)
  return exitCode === 0
}

export async function inspectHost(hostId: string) {
  const host = store.hosts.find((h) => h.id === hostId)
  if (!host) return
  const inspectionVersion = beginInspectionLoad(hostId)

  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/inspect/${encodeURIComponent(hostId)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    finishInspectionLoad(hostId, inspectionVersion, data)
    if (data.status === 'ok' || data.status === 'partial') {
      // 1. 同步健康与系统性能指标
      if (data.metrics && data.metrics.status === 'online') {
        const m = data.metrics
        host.cpuUsage = m.cpuUsage
        if (m.cpuCores && m.cpuCores.length > 0) host.cpuCores = m.cpuCores
        if (m.loadAvg) host.loadAvg = m.loadAvg
        host.memUsedGb = m.memUsedGb
        host.memTotalGb = m.memTotalGb
        host.swapUsedGb = m.swapUsedGb
        host.swapTotalGb = m.swapTotalGb
        host.diskUsedPercent = m.diskUsedPercent
        if (m.diskUsedGb !== undefined) host.diskUsedGb = m.diskUsedGb
        if (m.diskTotalGb !== undefined) host.diskTotalGb = m.diskTotalGb
        if (m.diskReadKbps !== undefined) host.diskReadKbps = m.diskReadKbps
        if (m.diskWriteKbps !== undefined) host.diskWriteKbps = m.diskWriteKbps
        host.netUpKbps = m.netUpKbps
        host.netDownKbps = m.netDownKbps
        host.uptime = m.uptime
        if (m.os) host.os = m.os
        if (m.kernel) host.kernel = m.kernel
        if (m.firewallBackend) host.firewallBackend = m.firewallBackend
        if (typeof m.firewallEnabled === 'boolean') host.firewallEnabled = m.firewallEnabled
        host.metricsStatus = 'synced'
        host.lastMetricsUpdate = Date.now()
      }

      // 2. 若是当前正在操作的主机，深度实装所有页面含有的真实数据
      if (store.activeHostId === hostId) {
        if (Array.isArray(data.systemdServices) && data.systemdServices.length > 0) {
          store.systemdServices = data.systemdServices
        }
        if (Array.isArray(data.firewallRules) && data.firewallRules.length > 0) {
          store.firewallRules = data.firewallRules
        }
        if (data.cwd && !host.currentCwd) {
          host.currentCwd = data.cwd
        }
        if (Array.isArray(data.files) && data.files.length > 0) {
          if (!host.currentCwd || host.currentCwd === data.cwd) {
            store.files = data.files
          }
        }
      }
    }
  } catch {
    finishInspectionLoad(hostId, inspectionVersion)
  }
}

export async function probeHost(hostId: string) {
  const host = store.hosts.find((h) => h.id === hostId)
  if (!host) return
  showToast(`正在深度探测主机「${host.name}」开机状态及全页面数据...`)
  host.powerStatus = 'checking'
  const inspectionVersion = beginInspectionLoad(hostId)

  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/probe/${encodeURIComponent(hostId)}`, {
      method: 'POST'
    })
    if (res.ok) {
      const probeRes = await res.json()
      finishInspectionLoad(hostId, inspectionVersion, probeRes.inspection)
      host.powerStatus = probeRes.online ? 'online' : 'offline'
      host.pingMs = probeRes.rtt_ms ?? undefined
      host.sshBanner = probeRes.banner ?? undefined
      host.probeMessage = probeRes.message
      host.lastProbedAt = probeRes.timestamp ? probeRes.timestamp * 1000 : Date.now()
      if (probeRes.online) {
        host.status = 'online'
      } else {
        host.status = 'offline'
      }

      // 识别是否因密码不对或认证失败而未接通
      const isAuthFailed = Boolean(
        probeRes.auth_failed ||
        (probeRes.inspection && (probeRes.inspection.status === 'auth_failed' || probeRes.inspection.auth_failed))
      )
      host.authFailed = isAuthFailed
      if (isAuthFailed) {
        host.authMessage = probeRes.auth_message || probeRes.inspection?.message || '密码错误或身份认证被拒绝 (Permission denied)'
        host.status = 'warning'
        host.metricsStatus = 'error'
      } else {
        host.authMessage = undefined
      }

      const authMethod = probeRes.auth_method || probeRes.inspection?.auth_method
      // 动态根据探测/认证结果更新卡片标签 (将“免密/密码认证”更名为“密码认证”或“默认密钥”)
      updateHostAuthTags(host, authMethod)

      // 若后端已返回全页面深度探测数据
      if (!isAuthFailed && probeRes.inspection && (probeRes.inspection.status === 'ok' || probeRes.inspection.status === 'partial')) {
        const insp = probeRes.inspection
        if (insp.metrics && insp.metrics.status === 'online') {
          const m = insp.metrics
          host.cpuUsage = m.cpuUsage
          if (m.cpuCores && m.cpuCores.length > 0) host.cpuCores = m.cpuCores
          if (m.loadAvg) host.loadAvg = m.loadAvg
          host.memUsedGb = m.memUsedGb
          host.memTotalGb = m.memTotalGb
          host.swapUsedGb = m.swapUsedGb
          host.swapTotalGb = m.swapTotalGb
          host.diskUsedPercent = m.diskUsedPercent
          if (m.diskUsedGb !== undefined) host.diskUsedGb = m.diskUsedGb
          if (m.diskTotalGb !== undefined) host.diskTotalGb = m.diskTotalGb
          if (m.diskReadKbps !== undefined) host.diskReadKbps = m.diskReadKbps
          if (m.diskWriteKbps !== undefined) host.diskWriteKbps = m.diskWriteKbps
          host.netUpKbps = m.netUpKbps
          host.netDownKbps = m.netDownKbps
          host.uptime = m.uptime
          if (m.os) host.os = m.os
          if (m.kernel) host.kernel = m.kernel
          if (m.firewallBackend) host.firewallBackend = m.firewallBackend
          if (typeof m.firewallEnabled === 'boolean') host.firewallEnabled = m.firewallEnabled
          host.metricsStatus = 'synced'
          host.lastMetricsUpdate = Date.now()
        }

        if (store.activeHostId === hostId) {
          if (Array.isArray(insp.systemdServices) && insp.systemdServices.length > 0) store.systemdServices = insp.systemdServices
          if (Array.isArray(insp.firewallRules) && insp.firewallRules.length > 0) store.firewallRules = insp.firewallRules
          if (insp.cwd && !host.currentCwd) host.currentCwd = insp.cwd
          if (Array.isArray(insp.files) && insp.files.length > 0) {
            if (!host.currentCwd || host.currentCwd === insp.cwd) {
              store.files = insp.files
            }
          }
        }
      } else if (!isAuthFailed && host.powerStatus === 'online') {
        await inspectHost(hostId)
      }
    } else {
      finishInspectionLoad(hostId, inspectionVersion)
    }
  } catch {
    finishInspectionLoad(hostId, inspectionVersion)
  }

  // 状态反馈提示
  if (host.authFailed) {
    showToast(`探测提示:「${host.name}」已开机，但因密码不对未接通 (身份认证失败)`)
  } else if (host.powerStatus === 'online') {
    showToast(`深度探测成功:「${host.name}」已开机 (响应 ${host.pingMs || 0}ms · CPU ${host.cpuUsage ?? '--'}%${host.os ? ` · ${host.os}` : ''})`)
  } else {
    host.metricsStatus = 'error'
    showToast(`探测完成:「${host.name}」未能连通 (目标可能关机或网络不可达)`)
  }
}

// 为主机更新 SSH 密码凭证并重新验证连接
export async function updateHostPassword(hostId: string, password: string): Promise<boolean> {
  const host = store.hosts.find((h) => h.id === hostId)
  if (!host) return false

  showToast(`正在验证「${host.name}」的新连接密码...`)
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/credentials/${encodeURIComponent(hostId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    })
    if (!res.ok) {
      showToast('设置密码失败：后端服务异常')
      return false
    }
    const data = await res.json()
    if (data.auth_failed) {
      host.authFailed = true
      host.authMessage = data.auth_message || '密码仍不正确，请重新输入'
      showToast(`密码验证失败：服务器拒绝了该密码`)
      return false
    }

    // 认证通过
    host.authFailed = false
    host.authMessage = undefined
    host.powerStatus = 'online'
    host.status = 'online'
    host.hasCustomPassword = true
    updateHostAuthTags(host, 'password', true)
    showToast(`密码验证成功！已连通服务器「${host.name}」并同步全页面数据`)

    // 重新探测全量数据
    await probeHost(hostId)
    return true
  } catch {
    showToast(`提交密码失败：无法连接后端服务`)
    return false
  }
}

export function refreshCurrentHostMetrics() {
  if (store.activeHostId) {
    return fetchHostMetrics(store.activeHostId)
  }
}

export function startMetricsPolling(interval = METRICS_POLL_INTERVAL_MS) {
  if (metricsTimer) clearInterval(metricsTimer)
  refreshCurrentHostMetrics()
  metricsTimer = setInterval(() => {
    if (typeof document !== 'undefined' && document.hidden) return
    refreshCurrentHostMetrics()
  }, interval)
}

export function stopMetricsPolling() {
  if (metricsTimer) {
    clearInterval(metricsTimer)
    metricsTimer = null
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      refreshCurrentHostMetrics()
    }
  })
}

watch(
  () => store.activeHostId,
  (newId) => {
    ++inspectionRequestVersion
    ++processRequestVersion
    ++processHostVersion
    store.processes = []
    store.processesError = ''
    store.processesLoading = !!newId
    store.cronTasks = []
    store.cronTasksError = ''
    store.cronTasksLoading = !!newId
    store.serverTimezone = null
    store.dockerContainers = []
    store.dockerContainersError = ''
    store.dockerContainersLoading = !!newId
    if (newId) void inspectHost(newId)
  },
  { flush: 'sync' }
)

watch(
  () => store.activeHostId,
  (newId) => {
    if (newId) {
      refreshCurrentHostMetrics()
      const h = store.hosts.find((x) => x.id === newId)
      fetchRemoteDirectory(h?.currentCwd || '~')
    } else {
      stopMetricsPolling()
    }
  }
)

// 自动在客户端初始化时加载本地 ~/.ssh/config
if (typeof window !== 'undefined') {
  loadSshHostsFromBackend()
}

// 实时从远端服务器拉取指定目录的文件列表
export async function fetchRemoteDirectory(path?: string, analyzeDu = true): Promise<boolean> {
  const hostId = store.activeHostId
  if (!hostId) return false

  const targetPath = path || currentHost.value.currentCwd || '~'
  store.filesLoading = true
  store.filesError = ''

  try {
    const url = `http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/list?path=${encodeURIComponent(targetPath)}&show_hidden=${store.showHiddenFiles}`
    const res = await fetch(url)
    if (!res.ok) {
      store.filesError = `读取目录失败 (HTTP ${res.status})`
      return false
    }
    const data = await res.json()
    if (data.status === 'ok') {
      currentHost.value.currentCwd = data.cwd || targetPath
      store.files = Array.isArray(data.files) ? data.files : []
      if (analyzeDu && store.autoCalculateDirSizes) {
        fetchDirectoryDiskUsage(data.cwd || targetPath)
      }
      return true
    } else {
      store.filesError = data.message || `无法访问路径: ${targetPath}`
      showToast(store.filesError)
      return false
    }
  } catch {
    store.filesError = '无法连接后端服务读取远程目录'
    return false
  } finally {
    store.filesLoading = false
  }
}

// 实时分析远端目录各子项体积占用 (ncdu) 并批量更新目录大小映射
export async function fetchDirectoryDiskUsage(path?: string) {
  const hostId = store.activeHostId
  if (!hostId) return

  const targetPath = path || currentHost.value.currentCwd || '~'
  store.dirDiskUsage.loading = true
  try {
    const url = `http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/du?path=${encodeURIComponent(targetPath)}`
    const res = await fetch(url)
    if (!res.ok) return
    const data = await res.json()
    if (data.status === 'ok') {
      store.dirDiskUsage.cwd = data.cwd || targetPath
      store.dirDiskUsage.totalBytes = data.totalBytes || 0
      store.dirDiskUsage.items = Array.isArray(data.items) ? data.items : []
      if (data.dirSizes && typeof data.dirSizes === 'object') {
        Object.assign(store.dirSizes, data.dirSizes)
      }
    }
  } catch {
    // ignore
  } finally {
    store.dirDiskUsage.loading = false
  }
}

// 单独测算某个特定文件夹的真实磁盘占用 (du -sb)
export async function fetchSingleDirSize(dirPath: string, sudo = false): Promise<number | null> {
  const hostId = store.activeHostId
  if (!hostId || !dirPath) return null

  if (!store.calculatingDirs.includes(dirPath)) {
    store.calculatingDirs.push(dirPath)
  }

  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/single-dir-size`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: dirPath, sudo })
    })
    if (!res.ok) return null
    const data = await res.json()
    if (data.status === 'ok' && typeof data.sizeBytes === 'number') {
      store.dirSizes[dirPath] = data.sizeBytes
      return data.sizeBytes
    }
  } catch {
    // ignore
  } finally {
    const idx = store.calculatingDirs.indexOf(dirPath)
    if (idx !== -1) {
      store.calculatingDirs.splice(idx, 1)
    }
  }
  return null
}

// 打开内置代码/配置编辑器抽屉并从远端服务器读取真实文件内容
export async function openFileInEditor(filePath: string, reloadServiceHint = '') {
  const hostId = store.activeHostId
  const existing = store.files.find((f) => f.path === filePath)

  store.editorDrawer.filePath = filePath
  store.editorDrawer.sudoWrite =
    filePath.startsWith('/etc') || filePath.startsWith('/lib') || filePath.startsWith('/usr')
  store.editorDrawer.reloadServiceHint = reloadServiceHint
  store.editorDrawer.open = true

  if (!hostId) {
    store.editorDrawer.content = existing?.content ?? ''
    return
  }

  store.editorDrawer.loading = true
  try {
    const url = `http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/content?path=${encodeURIComponent(filePath)}`
    const res = await fetch(url)
    if (res.ok) {
      const data = await res.json()
      if (data.status === 'ok') {
        store.editorDrawer.content = data.content ?? ''
        if (data.usedSudo) {
          store.editorDrawer.sudoWrite = true
        }
        if (existing) {
          existing.content = data.content
          if (data.permissions) existing.permissions = data.permissions
          if (data.octal) existing.octal = data.octal
          if (data.modifiedAt) existing.modifiedAt = data.modifiedAt
        }
        return
      } else {
        showToast(data.message || `读取文件失败: ${filePath}`)
        if (data.isBinary) {
          store.editorDrawer.open = false
          return
        }
      }
    }
  } catch {
    showToast(`拉取远程文件内容失败，显示本地缓存副本`)
  } finally {
    store.editorDrawer.loading = false
  }

  store.editorDrawer.content =
    existing?.content ??
    `# 自动加载远端文件: ${filePath}\n# Host: ${currentHost.value.name} (${currentHost.value.ip})\n`
}

// 将内置代码编辑器中的内容写回远端服务器
export async function saveRemoteFileContent(): Promise<boolean> {
  const hostId = store.activeHostId
  const filePath = store.editorDrawer.filePath
  if (!filePath) return false

  if (!hostId) {
    showToast('未连接服务器，无法保存文件')
    return false
  }

  store.editorDrawer.saving = true
  try {
    const res = await fetch(
      `http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/content`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: filePath,
          content: store.editorDrawer.content,
          sudo_write: store.editorDrawer.sudoWrite
        })
      }
    )
    const data = await res.json()
    if (res.ok && data.status === 'ok') {
      const existing = store.files.find((f) => f.path === filePath)
      if (existing) {
        existing.content = store.editorDrawer.content
        if (data.file) {
          existing.sizeBytes = data.file.sizeBytes
          existing.permissions = data.file.permissions
          existing.octal = data.file.octal
          existing.modifiedAt = data.file.modifiedAt
        }
      }
      showToast(data.message || `已成功保存远端文件: ${filePath}`)
      fetchRemoteDirectory(currentHost.value.currentCwd, false)
      return true
    } else {
      showToast(data.message || `保存失败: ${filePath}`)
      return false
    }
  } catch {
    showToast('保存失败：无法连接后端服务')
    return false
  } finally {
    store.editorDrawer.saving = false
  }
}

// 记录界面触发的命令，并按需切换至工作台；此函数不发送 SSH 命令
export function executeTerminalCommand(cmd: string, switchToWorkbench = false) {
  const trimmed = cmd.trim()
  if (!trimmed) return

  // 检测 cd 切换目录并联动文件管理器
  if (trimmed.startsWith('cd ')) {
    const targetDir = trimmed.slice(3).trim().split(/\s+/)[0]
    if (targetDir.startsWith('/') || targetDir.startsWith('~')) {
      currentHost.value.currentCwd = targetDir
      fetchRemoteDirectory(targetDir)
    }
  }

  store.rawHistoryLines.unshift(trimmed)

  if (switchToWorkbench) {
    store.activePage = 'P1_WORKBENCH'
  }

  showToast(`已在终端执行: ${trimmed}`)
}

// 打开参数化命令执行弹窗
export function triggerSnippetExecution(snippet: SavedSnippet) {
  if (snippet.variables.length === 0) {
    executeTerminalCommand(snippet.commandTemplate)
    snippet.usageCount++
    return
  }
  const initVals: Record<string, string> = {}
  for (const v of snippet.variables) {
    initVals[v.name] = v.defaultValue
  }
  store.paramModal.snippet = snippet
  store.paramModal.values = initVals
  store.paramModal.open = true
}

// 将自动提炼的候选模板一键转正加入「常用命令库」
export function promoteClusterToSnippet(cluster: ExtractedCommandCluster) {
  const newSnippet: SavedSnippet = {
    id: `snip-${Date.now()}`,
    title: cluster.proposedTitle,
    category: cluster.proposedCategory,
    commandTemplate: cluster.proposedTemplate,
    description: `由 AST 骨架算法从 ${cluster.occurrenceCount} 次历史执行记录中自动提炼`,
    variables: cluster.variables,
    scope: 'global',
    usageCount: cluster.occurrenceCount,
    source: 'auto-extracted'
  }
  store.savedSnippets.unshift(newSnippet)
  showToast(`已将「${cluster.proposedTitle}」加入常用命令库！`)
}

// 计算当前实际渲染的主题 ('light' | 'dark')
export const resolvedColorScheme = computed<'light' | 'dark'>(() => {
  if (store.colorSchemePref === 'light' || store.colorSchemePref === 'dark') {
    return store.colorSchemePref
  }
  return store.systemIsDark ? 'dark' : 'light'
})

// 同步更新 <meta name="color-scheme"> 与 localStorage (遵循 dark-mode-toggle 指南)
export function applyColorSchemeMeta(scheme: 'light dark' | 'light' | 'dark') {
  store.colorSchemePref = scheme
  if (typeof document !== 'undefined') {
    const meta = document.querySelector('meta[name="color-scheme"]')
    if (meta) {
      meta.setAttribute('content', scheme)
    }
  }
  try {
    if (scheme === 'light dark') {
      localStorage.removeItem('color-scheme')
    } else {
      localStorage.setItem('color-scheme', scheme)
    }
  } catch {
    // 忽略隐私模式 localStorage 异常，保持页面主题正常生效
  }
}

// 顶栏三态图标循环切换：白天模式 (light) -> 夜间模式 (dark) -> 自动模式/跟随系统 (light dark)
export function toggleColorScheme() {
  const current = store.colorSchemePref
  const next: 'light' | 'dark' | 'light dark' =
    current === 'light' ? 'dark' : current === 'dark' ? 'light dark' : 'light'

  applyColorSchemeMeta(next)

  if (next === 'light') {
    showToast('已切换至：白天模式 (Light)')
  } else if (next === 'dark') {
    showToast('已切换至：夜间模式 (Dark)')
  } else {
    showToast(`已切换至：自动模式 · 跟随系统 (当前为${store.systemIsDark ? '夜间' : '白天'})`)
  }
}

// 显式指定三态外观 ('light' | 'dark' | 'light dark')
export function setExplicitColorScheme(scheme: 'light dark' | 'light' | 'dark') {
  applyColorSchemeMeta(scheme)
  const label =
    scheme === 'light'
      ? '白天模式 (Light)'
      : scheme === 'dark'
        ? '夜间模式 (Dark)'
        : `自动模式 · 跟随系统 (${store.systemIsDark ? '当前夜间' : '当前白天'})`
  showToast(`外观模式已设为：${label}`)
}

// 初始化媒体查询与跨标签页 storage 监听（绝不在系统偏好变化时清除用户已固定的存储值）
if (typeof window !== 'undefined') {
  try {
    const saved = localStorage.getItem('color-scheme')
    if (saved === 'light' || saved === 'dark') {
      store.colorSchemePref = saved
    }
  } catch {
    // ignore
  }

  if (typeof window.matchMedia === 'function') {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    mql.addEventListener('change', (e) => {
      store.systemIsDark = e.matches
    })
  }

  window.addEventListener('storage', (e) => {
    if (e.key === 'color-scheme') {
      const next =
        e.newValue === 'light' || e.newValue === 'dark' ? e.newValue : 'light dark'
      store.colorSchemePref = next
      const meta = document.querySelector('meta[name="color-scheme"]')
      if (meta) {
        meta.setAttribute('content', next)
      }
    }
  })
}
