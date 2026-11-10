import { reactive, computed, watch } from 'vue'
import type {
  PageId,
  ServerHost,
  TerminalEntry,
  SavedSnippet,
  ExtractedCommandCluster,
  FileEntry,
  ProcessItem,
  CronTaskItem,
  SystemdServiceItem,
  DockerContainerItem,
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
  // 当前主页面路由
  activePage: 'P1_WORKBENCH' as PageId,

  // 色彩模式状态 ('light dark' 跟随系统 | 'light' 白天模式 | 'dark' 暗黑模式)
  colorSchemePref: (typeof window !== 'undefined'
    ? (localStorage.getItem('color-scheme') as 'light' | 'dark' | null) ?? 'light dark'
    : 'light dark') as 'light dark' | 'light' | 'dark',
  systemIsDark:
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : true,

  // 已打开的服务器会话 Tabs
  openHostIds: ['prod-web-01', 'db-master-02'] as string[],
  activeHostId: 'prod-web-01',

  // 底部随行终端抽屉开关 (在 P2-P8 页面保持 SSH 会话不断开)
  bottomTerminalOpen: false,

  // 终端自动同步文件管理器路径 (Follow CWD)
  followCwd: true,

  // 跨模块跳转上下文胶囊横幅
  lastJumpContext: null as CrossModuleLinkPayload | null,

  // 全局 Toast 通知
  toastMessage: '' as string,

  // 右侧文件代码编辑器抽屉状态
  editorDrawer: {
    open: false,
    filePath: '',
    content: '',
    sudoWrite: false,
    reloadServiceHint: ''
  },

  // 全局命令面板 (Cmd+K) 与参数化命令执行弹窗控制
  commandPaletteOpen: false,
  paramModal: {
    open: false,
    snippet: null as SavedSnippet | null,
    values: {} as Record<string, string>,
    execMode: 'execute' as 'execute' | 'paste' | 'silent'
  },

  // 独立实时日志悬浮窗 (Detached Log Tailer)
  detachedLogWindow: {
    open: false,
    title: 'journalctl -u nginx.service -f',
    lines: [
      '2026-11-10 11:05:12 [info] 1042#1042: *98121 client 183.14.29.11 connected to 0.0.0.0:443',
      '2026-11-10 11:05:14 [info] 1042#1042: *98124 upstream response 200 in 14ms (/api/v1/health)',
      '2026-11-10 11:06:01 [warn] 1043#1043: *98155 an upstream response is buffered to a temporary file'
    ]
  },

  // 服务器主机池
  hosts: [
    {
      id: 'prod-web-01',
      name: 'Prod-Web-Gateway-01',
      ip: '47.98.132.210',
      port: 22,
      user: 'root',
      group: '生产集群 (华东)',
      os: 'Ubuntu 24.04.1 LTS',
      kernel: '6.8.0-45-generic',
      uptime: '48 天 14 小时',
      status: 'online',
      tags: ['Nginx', 'Docker', '核心入口'],
      cpuUsage: 32,
      cpuCores: [45, 28, 39, 19, 52, 24, 30, 18],
      loadAvg: [1.42, 1.18, 0.95],
      memUsedGb: 9.4,
      memTotalGb: 16,
      swapUsedGb: 0.4,
      swapTotalGb: 4,
      diskUsedPercent: 64,
      netUpKbps: 2840,
      netDownKbps: 1420,
      firewallEnabled: true,
      firewallBackend: 'ufw',
      currentCwd: '/etc/nginx'
    },
    {
      id: 'db-master-02',
      name: 'DB-Postgres-Master-02',
      ip: '10.16.40.12',
      port: 2222,
      user: 'postgres',
      group: '生产集群 (华东)',
      os: 'Debian 12.7 (Bookworm)',
      kernel: '6.1.0-25-amd64',
      uptime: '129 天 03 小时',
      status: 'warning',
      tags: ['PostgreSQL 16', 'Redis', '内网主库'],
      cpuUsage: 68,
      cpuCores: [78, 82, 64, 59, 71, 60, 66, 62],
      loadAvg: [4.85, 4.12, 3.60],
      memUsedGb: 26.8,
      memTotalGb: 32,
      swapUsedGb: 1.8,
      swapTotalGb: 8,
      diskUsedPercent: 81,
      netUpKbps: 6420,
      netDownKbps: 5190,
      firewallEnabled: true,
      firewallBackend: 'iptables',
      currentCwd: '/var/lib/postgresql/data'
    },
    {
      id: 'ai-gpu-node-03',
      name: 'AI-Inference-L40S-03',
      ip: '192.168.88.105',
      port: 22,
      user: 'ubuntu',
      group: '算力与测试节点',
      os: 'Ubuntu 22.04.4 LTS',
      kernel: '5.15.0-119-generic',
      uptime: '15 天 08 小时',
      status: 'online',
      tags: ['GPU', 'vLLM', 'Docker'],
      cpuUsage: 19,
      cpuCores: [15, 22, 18, 25, 14, 19, 20, 17],
      loadAvg: [0.88, 1.02, 1.15],
      memUsedGb: 41.2,
      memTotalGb: 64,
      swapUsedGb: 0,
      swapTotalGb: 16,
      diskUsedPercent: 47,
      netUpKbps: 820,
      netDownKbps: 310,
      firewallEnabled: false,
      firewallBackend: 'ufw',
      currentCwd: '/opt/models'
    }
  ] as ServerHost[],

  // 终端会话记录
  terminalHistory: [
    {
      id: 'term-1',
      timestamp: '11:01:15',
      cwd: '/root',
      command: 'cd /etc/nginx && ls -la',
      output:
        'drwxr-xr-x 8 root root 4096 Nov 10 09:20 .\n-rw-r--r-- 1 root root 2641 Nov 09 18:12 nginx.conf\ndrwxr-xr-x 2 root root 4096 Nov 10 09:20 conf.d\n-rw-r--r-- 1 root root 1094 Nov 02 10:00 mime.types',
      exitCode: 0,
      durationMs: 28
    },
    {
      id: 'term-2',
      timestamp: '11:03:42',
      cwd: '/etc/nginx',
      command: 'ss -tulnp | grep -E "80|443|8080|6379"',
      output:
        'tcp   LISTEN 0      511          0.0.0.0:80         0.0.0.0:*    users:(("nginx",pid=1042,fd=6))\ntcp   LISTEN 0      511          0.0.0.0:443        0.0.0.0:*    users:(("nginx",pid=1042,fd=7))\ntcp   LISTEN 0      4096         0.0.0.0:8080       0.0.0.0:*    users:(("api-core",pid=2891,fd=3))\ntcp   LISTEN 0      511          0.0.0.0:6379       0.0.0.0:*    users:(("docker-proxy",pid=4120,fd=4))',
      exitCode: 0,
      durationMs: 45
    },
    {
      id: 'term-3',
      timestamp: '11:05:19',
      cwd: '/etc/nginx',
      command: 'docker logs -f --tail 100 nginx-gateway',
      output:
        '172.18.0.1 - - [10/Nov/2026:11:05:10 +0800] "GET /api/v2/cluster/nodes HTTP/2.0" 200 1842\n172.18.0.1 - - [10/Nov/2026:11:05:18 +0800] "POST /api/v2/auth/verify HTTP/2.0" 200 412',
      exitCode: 0,
      durationMs: 112
    }
  ] as TerminalEntry[],

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

  // 进程监控列表 (含端口监听与跨模块标识)
  processes: [
    {
      pid: 1042,
      ppid: 1,
      name: 'nginx',
      cmdline: 'nginx: master process /usr/sbin/nginx -g daemon on;',
      user: 'root',
      state: 'S',
      cpuPercent: 4.2,
      memPercent: 2.1,
      memRssMb: 342,
      listenPort: 443,
      protocol: 'tcp',
      firewallAllowed: true,
      cwd: '/etc/nginx',
      systemdUnit: 'nginx.service',
      uptime: '48d 14h'
    },
    {
      pid: 2891,
      ppid: 1,
      name: 'api-core',
      cmdline: '/opt/api-core/bin/server --port 8080 --env prod',
      user: 'www-data',
      state: 'R',
      cpuPercent: 18.6,
      memPercent: 14.5,
      memRssMb: 2380,
      listenPort: 8080,
      protocol: 'tcp',
      firewallAllowed: false, // 重点演示：已监听但未在防火墙放行！
      cwd: '/opt/api-core',
      systemdUnit: 'api-core.service',
      uptime: '12d 06h'
    },
    {
      pid: 4120,
      ppid: 980,
      name: 'redis-server',
      cmdline: 'redis-server 0.0.0.0:6379 [docker: redis-cache-01]',
      user: '999',
      state: 'S',
      cpuPercent: 6.8,
      memPercent: 8.4,
      memRssMb: 1376,
      listenPort: 6379,
      protocol: 'tcp',
      firewallAllowed: true,
      cwd: '/var/lib/docker/volumes/redis_data/_data',
      dockerContainerId: 'c-redis-01',
      uptime: '19d 22h'
    },
    {
      pid: 5310,
      ppid: 1,
      name: 'node-exporter',
      cmdline: '/usr/local/bin/node_exporter --web.listen-address=:9100',
      user: 'prometheus',
      state: 'S',
      cpuPercent: 1.1,
      memPercent: 0.6,
      memRssMb: 96,
      listenPort: 9100,
      protocol: 'tcp',
      firewallAllowed: false,
      cwd: '/var/lib/node_exporter',
      systemdUnit: 'node-exporter.service',
      uptime: '48d 14h'
    }
  ] as ProcessItem[],

  // 计划任务列表 (Crontab + Systemd Timers)
  cronTasks: [
    {
      id: 'cron-1',
      engine: 'crontab',
      title: '每日凌晨 PostgreSQL 生产库增量备份',
      expression: '0 2 * * *',
      naturalLanguage: '每天 02:00 准时执行',
      command: '/opt/scripts/backup_db.sh >> /var/log/backup_db.log 2>&1',
      scriptPath: '/opt/scripts/backup_db.sh',
      user: 'root',
      enabled: true,
      lastRunAt: '2026-11-10 02:00:01',
      lastExitCode: 0,
      nextRuns: ['2026-11-11 02:00:00', '2026-11-12 02:00:00', '2026-11-13 02:00:00'],
      lastOutput: '[OK] Backup finished at 20261110_020004 (size: 148.2MB)'
    },
    {
      id: 'cron-2',
      engine: 'crontab',
      title: '每 15 分钟清理临时上传缓存目录',
      expression: '*/15 * * * *',
      naturalLanguage: '每 15 分钟执行一次',
      command: 'find /tmp/uploads -name "*.tmp" -mtime +3 -delete',
      user: 'www-data',
      enabled: true,
      lastRunAt: '2026-11-10 11:00:00',
      lastExitCode: 0,
      nextRuns: ['2026-11-10 11:15:00', '2026-11-10 11:30:00', '2026-11-10 11:45:00'],
      lastOutput: 'Deleted 14 expired .tmp files'
    },
    {
      id: 'cron-3',
      engine: 'systemd-timer',
      title: 'Let’s Encrypt SSL 证书自动续期检查',
      expression: '0 3 */7 * *',
      naturalLanguage: '每 7 天凌晨 03:00 执行',
      command: 'certbot renew --quiet --deploy-hook "systemctl reload nginx"',
      user: 'root',
      enabled: true,
      lastRunAt: '2026-11-08 03:00:12',
      lastExitCode: 0,
      nextRuns: ['2026-11-15 03:00:00', '2026-11-22 03:00:00'],
      lastOutput: 'Cert not yet due for renewal; no action taken.'
    }
  ] as CronTaskItem[],

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
  dockerContainers: [
    {
      id: 'c-nginx-01',
      name: 'nginx-gateway',
      image: 'nginx:1.27-alpine',
      status: 'running',
      cpuPercent: 3.4,
      memMb: 128,
      ports: [
        { hostPort: 80, containerPort: 80, protocol: 'tcp', firewallAllowed: true },
        { hostPort: 443, containerPort: 443, protocol: 'tcp', firewallAllowed: true }
      ],
      volumes: [
        { hostPath: '/etc/nginx/nginx.conf', containerPath: '/etc/nginx/nginx.conf' },
        { hostPath: '/var/log/nginx', containerPath: '/var/log/nginx' }
      ],
      composeProject: 'gateway',
      composePath: '/opt/stacks/gateway/docker-compose.yml',
      createdAt: '19 天前'
    },
    {
      id: 'c-redis-01',
      name: 'redis-cache-01',
      image: 'redis:7.4-alpine',
      status: 'running',
      cpuPercent: 6.8,
      memMb: 1376,
      ports: [
        { hostPort: 6379, containerPort: 6379, protocol: 'tcp', firewallAllowed: true }
      ],
      volumes: [
        { hostPath: '/var/lib/docker/volumes/redis_data/_data', containerPath: '/data' }
      ],
      composeProject: 'gateway',
      composePath: '/opt/stacks/gateway/docker-compose.yml',
      createdAt: '19 天前'
    },
    {
      id: 'c-grafana-02',
      name: 'grafana-dashboard',
      image: 'grafana/grafana:11.2.0',
      status: 'running',
      cpuPercent: 1.9,
      memMb: 284,
      ports: [
        { hostPort: 3000, containerPort: 3000, protocol: 'tcp', firewallAllowed: false }
      ],
      volumes: [
        { hostPath: '/var/lib/docker/volumes/grafana_data/_data', containerPath: '/var/lib/grafana' }
      ],
      composeProject: 'monitoring',
      composePath: '/opt/stacks/monitoring/docker-compose.yml',
      createdAt: '5 天前'
    }
  ] as DockerContainerItem[],

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

// 计算当前激活的服务器对象
export const currentHost = computed<ServerHost>(() => {
  return store.hosts.find((h) => h.id === store.activeHostId) ?? store.hosts[0]
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
  store.lastJumpContext = payload
  store.activePage = payload.targetPage

  if (payload.openPath) {
    currentHost.value.currentCwd = payload.openPath
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
}

// 从本地 Python 后端加载真实 ~/.ssh/config 主机列表
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
        os: 'Linux (SSH直连)',
        kernel: 'SSH2 / PTY',
        uptime: '检测就绪',
        status: 'online',
        tags: h.identity_files.length > 0 ? ['密钥认证', ...h.identity_files.map(k => k.split('/').pop() || 'key')] : ['免密/密码认证'],
        cpuUsage: 18,
        cpuCores: [15, 20, 18, 14],
        loadAvg: [0.35, 0.28, 0.22],
        memUsedGb: 3.2,
        memTotalGb: 8,
        swapUsedGb: 0.1,
        swapTotalGb: 2,
        diskUsedPercent: 35,
        netUpKbps: 45,
        netDownKbps: 120,
        firewallEnabled: true,
        firewallBackend: 'ufw',
        currentCwd: '~'
      }))

      // 同步更新打开的会话标签
      if (!store.openHostIds.includes(backendHosts[0].host_alias)) {
        store.openHostIds = [backendHosts[0].host_alias]
        store.activeHostId = backendHosts[0].host_alias
      }

      // 立即触发当前激活主机的性能数据采集与定时轮询
      startMetricsPolling()
    }
  } catch {
    // 后端未启动时静默保持现有状态
  }
}

export interface HostMetricsResponse {
  status: 'online' | 'error'
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
  netUpKbps: number
  netDownKbps: number
  uptime: string
  os?: string
  kernel?: string
  message?: string
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
      targetHost.netUpKbps = data.netUpKbps
      targetHost.netDownKbps = data.netDownKbps
      targetHost.uptime = data.uptime
      if (data.os) targetHost.os = data.os
      if (data.kernel) targetHost.kernel = data.kernel
      targetHost.status = 'online'
      targetHost.metricsStatus = 'synced'
      targetHost.lastMetricsUpdate = Date.now()
    } else {
      targetHost.metricsStatus = 'error'
    }
  } catch {
    targetHost.metricsStatus = 'error'
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
    if (newId) {
      refreshCurrentHostMetrics()
    }
  }
)

// 自动在客户端初始化时加载本地 ~/.ssh/config
if (typeof window !== 'undefined') {
  loadSshHostsFromBackend()
}

// 打开内置代码/配置编辑器抽屉
export function openFileInEditor(filePath: string, reloadServiceHint = '') {
  const existing = store.files.find((f) => f.path === filePath)
  store.editorDrawer.filePath = filePath
  store.editorDrawer.content =
    existing?.content ??
    `# 自动加载远端文件: ${filePath}\n# Host: ${currentHost.value.name} (${currentHost.value.ip})\n\n`
  store.editorDrawer.sudoWrite = filePath.startsWith('/etc') || filePath.startsWith('/lib')
  store.editorDrawer.reloadServiceHint = reloadServiceHint
  store.editorDrawer.open = true
}

// 在当前终端执行一条命令并同步写入历史提炼池
export function executeTerminalCommand(cmd: string, switchToWorkbench = false) {
  const trimmed = cmd.trim()
  if (!trimmed) return

  // 检测 cd 切换目录并联动文件管理器
  if (trimmed.startsWith('cd ')) {
    const targetDir = trimmed.slice(3).trim().split(/\s+/)[0]
    if (targetDir.startsWith('/')) {
      currentHost.value.currentCwd = targetDir
    }
  }

  const now = new Date()
  const timeStr = now.toTimeString().slice(0, 8)

  let simulatedOutput = `[SSH ${currentHost.value.user}@${currentHost.value.ip}] Executed: ${trimmed}\n`
  if (trimmed.startsWith('docker exec')) {
    simulatedOutput = `root@${trimmed.split(' ').slice(-2, -1)[0] ?? 'container'}:/# # 已进入容器交互式 Shell 会话`
  } else if (trimmed.startsWith('sudo ufw')) {
    simulatedOutput = `Rule added\nRule added (v6)\nFirewall reloaded successfully.`
  } else if (trimmed.startsWith('systemctl')) {
    simulatedOutput = `[OK] ${trimmed} completed (0.04s).`
  } else if (trimmed.startsWith('docker logs')) {
    simulatedOutput = `2026-11-10 ${timeStr} [INFO] Stream connected — showing tail lines for ${trimmed.split(' ').pop()}\n2026-11-10 ${timeStr} [INFO] Request handled in 8.4ms (HTTP 200)`
  }

  store.terminalHistory.push({
    id: `term-${Date.now()}`,
    timestamp: timeStr,
    cwd: currentHost.value.currentCwd,
    command: trimmed,
    output: simulatedOutput,
    exitCode: 0,
    durationMs: Math.floor(Math.random() * 60) + 15
  })

  store.rawHistoryLines.unshift(trimmed)

  if (switchToWorkbench) {
    store.activePage = 'P1_WORKBENCH'
  } else if (store.activePage !== 'P1_WORKBENCH') {
    store.bottomTerminalOpen = true
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
  store.paramModal.execMode = 'execute'
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

