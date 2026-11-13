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
  diskReadKbps?: number
  diskWriteKbps?: number
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
  isSymlink?: boolean
  linkTarget?: string | null
  sizeBytes: number
  permissions: string
  octal: string
  owner: string
  group: string
  modifiedAt: string
  content?: string
}

export interface DiskUsageItem {
  name: string
  path: string
  sizeBytes: number
  isDir: boolean
  percent: number
}

export type ProcessSignal = 'SIGTERM' | 'SIGKILL'

export interface ProcessActionResponse {
  status: 'ok' | 'error'
  message?: string
  detail?: string | { msg: string }[]
  error_type?: string
}

export interface ProcessItem {
  pid: number
  ppid: number
  name: string
  cmdline: string
  user: string
  state: string
  identity?: string
  cpuPercent: number
  memPercent: number
  memRssMb: number
  listenPort?: number
  protocol?: 'tcp' | 'udp'
  firewallAllowed?: boolean | null
  cwd: string
  systemdUnit?: string
  dockerContainerId?: string
  uptime: string
}

/** 服务器时区；crontab 按该时区的本地时间触发，前端据此换算北京时间。 */
export interface ServerTimezone {
  name: string
  abbreviation: string
  /** 形如 `+0800` / `-0500`。 */
  utcOffset: string
}

export interface CronTaskItem {
  id: string
  engine: 'crontab' | 'systemd-timer'
  title: string
  expression: string
  command: string
  scriptPath?: string
  user: string
  enabled: boolean
  lastRunAt: string
  lastExitCode: number | null
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

export type SystemdServiceAction = 'start' | 'stop' | 'restart'

export interface SystemdActionResponse {
  status: 'ok' | 'error'
  service?: string
  message?: string
  detail?: string
  exit_code?: number
  action?: SystemdServiceAction
}

export type DockerContainerAction = 'start' | 'stop' | 'restart'

export interface DockerActionResponse {
  status: 'ok' | 'error'
  container?: string
  message?: string
  detail?: string
  exit_code?: number
  action?: DockerContainerAction
}

export interface DockerExecTarget {
  hostAlias: string
  containerId: string
  name: string
  sudo: boolean
}

export interface DockerContainerItem {
  id: string
  name: string
  image: string
  status: 'running' | 'exited' | 'restarting' | 'created' | 'paused' | 'removing' | 'dead' | 'unknown'
  ports: Array<{
    /** 0 表示仅容器内暴露，未发布至宿主机。 */
    hostPort: number
    hostIp?: string
    containerPort: number
    protocol: 'tcp' | 'udp' | 'sctp'
  }>
  volumes: Array<{
    hostPath: string
    containerPath: string
    type?: string
    readOnly?: boolean
  }>
  diskUsage?: string
  composeProject?: string | null
  composeService?: string | null
  composePath?: string
  createdAt: string
  detailsAvailable?: boolean
  networkMode?: string | null
  networks?: Array<{ name: string; ipAddress: string; ipv6Address: string }>
  restartPolicy?: string | null
  restartMaxRetries?: number | null
  restartCount?: number | null
  healthStatus?: string | null
  startedAt?: string | null
  finishedAt?: string | null
  exitCode?: number | null
  oomKilled?: boolean | null
  memoryLimitBytes?: number | null
  cpuLimit?: number | null
  cpusetCpus?: string | null
  privileged?: boolean | null
  readOnlyRootfs?: boolean | null
  runUser?: string | null
}

export interface FirewallRuleItem {
  id: string
  ruleNumber?: number
  backend?: 'ufw' | 'firewalld' | 'iptables'
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

export interface FirewallRuleCreatePayload {
  port: string
  protocol: 'tcp' | 'udp' | 'any'
  sourceCidr: string
  action: 'ALLOW' | 'DENY' | 'REJECT'
  comment: string
  sudo: boolean
  backend?: 'ufw' | 'firewalld' | 'iptables'
}

export interface FirewallRuleDeletePayload {
  port: string
  protocol: 'tcp' | 'udp' | 'any'
  sourceCidr: string
  action: 'ALLOW' | 'DENY' | 'REJECT'
  ruleNumber?: number
  backend?: 'ufw' | 'firewalld' | 'iptables'
  sudo: boolean
}

export interface FirewallActionResponse {
  status: 'ok' | 'error'
  backend?: 'ufw' | 'firewalld' | 'iptables'
  command?: string
  message?: string
  detail?: string
  exit_code?: number
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
