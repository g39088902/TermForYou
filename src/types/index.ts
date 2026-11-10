export type PageId =
  | 'P0_HOSTS'
  | 'P1_WORKBENCH'
  | 'P2_METRICS_PROCESS'
  | 'P3_FILES'
  | 'P4_COMMANDS'
  | 'P5_DOCKER'
  | 'P6_SYSTEMD'
  | 'P7_CRON'
  | 'P8_FIREWALL'

export interface ServerHost {
  id: string
  name: string
  ip: string
  port: number
  user: string
  group: string
  os?: string
  kernel?: string
  uptime?: string
  status: 'online' | 'warning' | 'offline' | 'unconnected'
  tags: string[]
  identityFiles?: string[]
  authMethod?: 'password' | 'default_key' | 'custom_key'
  hasCustomPassword?: boolean
  cpuUsage?: number
  cpuCores?: number[]
  loadAvg?: [number, number, number]
  memUsedGb?: number
  memTotalGb?: number
  swapUsedGb?: number
  swapTotalGb?: number
  diskUsedPercent?: number
  diskTotalGb?: number
  diskUsedGb?: number
  netUpKbps?: number
  netDownKbps?: number
  firewallEnabled?: boolean
  firewallBackend?: 'ufw' | 'firewalld' | 'iptables'
  currentCwd?: string
  metricsStatus?: 'idle' | 'updating' | 'synced' | 'error'
  lastMetricsUpdate?: number
  connectionCount?: number
  lastConnectedAt?: number
  powerStatus?: 'online' | 'offline' | 'checking' | 'unknown'
  pingMs?: number
  probeMessage?: string
  sshBanner?: string
  lastProbedAt?: number
  authFailed?: boolean
  authMessage?: string
}

export interface TerminalEntry {
  id: string
  timestamp: string
  cwd: string
  command: string
  output: string
  exitCode: number
  durationMs: number
}

export interface CommandVariableSlot {
  name: string
  defaultValue: string
  description: string
  options?: string[]
}

export interface SavedSnippet {
  id: string
  title: string
  category: 'Docker 运维' | '网络与端口排查' | '日志与文件分析' | '系统服务管控' | '数据库维护'
  commandTemplate: string
  description: string
  variables: CommandVariableSlot[]
  scope: 'global' | string
  usageCount: number
  source: 'manual' | 'auto-extracted' | 'gui-saved'
}

export interface ExtractedCommandCluster {
  id: string
  skeletonHash: string
  baseCommand: string
  proposedTemplate: string
  proposedTitle: string
  proposedCategory: SavedSnippet['category']
  occurrenceCount: number
  rawExamples: string[]
  variables: CommandVariableSlot[]
  confidence: number
  llmAnnotated: boolean
  accepted?: boolean
}

export interface FileEntry {
  name: string
  path: string
  isDir: boolean
  sizeBytes: number
  permissions: string
  octal: string
  owner: string
  group: string
  modifiedAt: string
  content?: string
}

export interface ProcessItem {
  pid: number
  ppid: number
  name: string
  cmdline: string
  user: string
  state: 'R' | 'S' | 'D' | 'Z'
  cpuPercent: number
  memPercent: number
  memRssMb: number
  listenPort?: number
  protocol?: 'tcp' | 'udp'
  firewallAllowed?: boolean
  cwd: string
  systemdUnit?: string
  dockerContainerId?: string
  uptime: string
}

export interface CronTaskItem {
  id: string
  engine: 'crontab' | 'systemd-timer'
  title: string
  expression: string
  naturalLanguage: string
  command: string
  scriptPath?: string
  user: string
  enabled: boolean
  lastRunAt: string
  lastExitCode: number
  nextRuns: string[]
  lastOutput: string
}

export interface SystemdServiceItem {
  name: string
  description: string
  state: 'running' | 'failed' | 'stopped'
  enabled: boolean
  pid?: number
  memoryMb: number
  uptime: string
  unitFilePath: string
  workingDir: string
  execStart: string
  restartPolicy: 'always' | 'on-failure' | 'no'
  recentLogs: string[]
}

export interface DockerContainerItem {
  id: string
  name: string
  image: string
  status: 'running' | 'exited' | 'restarting'
  cpuPercent: number
  memMb: number
  ports: Array<{
    hostPort: number
    containerPort: number
    protocol: 'tcp' | 'udp'
    firewallAllowed: boolean
  }>
  volumes: Array<{
    hostPath: string
    containerPath: string
  }>
  composeProject?: string
  composePath?: string
  createdAt: string
}

export interface FirewallRuleItem {
  id: string
  port: string
  protocol: 'tcp' | 'udp' | 'any'
  sourceCidr: string
  action: 'ALLOW' | 'DENY' | 'REJECT'
  comment: string
  enabled: boolean
  listeningProcess?: {
    pid?: number
    name: string
    type: 'process' | 'docker'
    targetId?: string
  }
}

export interface CrossModuleLinkPayload {
  sourcePage: PageId
  targetPage: PageId
  reason: string
  highlightPort?: number
  highlightPid?: number
  openPath?: string
  editFilePath?: string
  prefillFirewallPort?: number
  prefillFirewallProtocol?: 'tcp' | 'udp'
  prefillFirewallComment?: string
  filterService?: string
  filterContainer?: string
}
