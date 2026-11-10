import type { ExtractedCommandCluster, CommandVariableSlot, SavedSnippet } from '@/types'

const NOISE_COMMANDS = new Set([
  'ls',
  'll',
  'la',
  'cd',
  'pwd',
  'clear',
  'exit',
  'whoami',
  'history',
  'top',
  'htop'
])

const SUBCOMMAND_CLI_TOOLS = new Set([
  'docker',
  'systemctl',
  'journalctl',
  'git',
  'ufw',
  'firewall-cmd',
  'kubectl',
  'apt',
  'yum',
  'dnf',
  'pm2',
  'ip',
  'ss'
])

export interface TokenizedCommand {
  raw: string
  tokens: string[]
  baseCmd: string
  subCmd?: string
  flags: string[]
  skeletonHash: string
}

/**
 * 轻量级 Shell 命令词法切分器（保留引号包裹字串并清洗敏感凭证）
 */
export function tokenizeShellCommand(rawLine: string): TokenizedCommand | null {
  const cleaned = rawLine
    .trim()
    .replace(/^:\s*\d+:\d+;/, '') // 兼容 zsh_history 时间戳前缀
    .replace(/(password|passwd|token|secret|key)=\S+/gi, '$1=***')

  if (!cleaned || cleaned.startsWith('#')) return null

  const tokens: string[] = []
  const regex = /[^\s"']+|"([^"]*)"|'([^']*)'/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(cleaned)) !== null) {
    tokens.push(match[0])
  }

  if (tokens.length === 0) return null

  // 忽略前缀 sudo 计算核心命令骨架
  const offset = tokens[0] === 'sudo' && tokens.length > 1 ? 1 : 0
  const baseCmd = tokens[offset]
  if (!baseCmd || (NOISE_COMMANDS.has(baseCmd) && tokens.length <= offset + 2)) {
    return null
  }

  const hasSub = SUBCOMMAND_CLI_TOOLS.has(baseCmd) && tokens[offset + 1] && !tokens[offset + 1].startsWith('-')
  const subCmd = hasSub ? tokens[offset + 1] : undefined

  const flags = tokens
    .slice(offset + (hasSub ? 2 : 1))
    .filter((t) => t.startsWith('-'))
    .map((f) => f.split('=')[0])
    .sort()

  const skeletonHash = `${tokens[0] === 'sudo' ? 'sudo:' : ''}${baseCmd}${subCmd ? ':' + subCmd : ''}|flags:${flags.join(',')}|len:${tokens.length}`

  return {
    raw: cleaned,
    tokens,
    baseCmd,
    subCmd,
    flags,
    skeletonHash
  }
}

/**
 * 根据变化位置的值推断变量名与说明
 */
function inferVariableMeta(
  prevToken: string | undefined,
  sampleValues: string[],
  slotIndex: number
): CommandVariableSlot {
  const uniqueVals = Array.from(new Set(sampleValues))
  const firstVal = uniqueVals[0] ?? ''

  if (prevToken === '--tail' || prevToken === '-n' || /^\d+$/.test(firstVal)) {
    if (prevToken?.includes('port') || (Number(firstVal) >= 80 && Number(firstVal) <= 65535 && prevToken !== '--tail' && prevToken !== '-n')) {
      return {
        name: 'port',
        defaultValue: firstVal,
        description: '目标端口号',
        options: uniqueVals
      }
    }
    return {
      name: 'lines',
      defaultValue: firstVal,
      description: '输出行数或数值参数',
      options: uniqueVals
    }
  }

  if (firstVal.startsWith('/') || firstVal.includes('/')) {
    return {
      name: 'target_path',
      defaultValue: firstVal,
      description: '目标文件或目录路径',
      options: uniqueVals
    }
  }

  if (/^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/.test(firstVal)) {
    return {
      name: 'ip_cidr',
      defaultValue: firstVal,
      description: '目标 IP 地址或网段',
      options: uniqueVals
    }
  }

  if (prevToken === '-u' || prevToken === 'restart' || prevToken === 'status' || prevToken === 'stop') {
    return {
      name: 'service_unit',
      defaultValue: firstVal,
      description: 'Systemd 服务单元名',
      options: uniqueVals
    }
  }

  return {
    name: slotIndex === 1 ? 'target_name' : `arg_${slotIndex}`,
    defaultValue: firstVal,
    description: '动态目标名称（如容器名/服务名/关键字）',
    options: uniqueVals
  }
}

function inferCategoryAndTitle(baseCmd: string, subCmd?: string): {
  category: SavedSnippet['category']
  title: string
} {
  if (baseCmd === 'docker') {
    return {
      category: 'Docker 运维',
      title: `Docker ${subCmd ?? '容器'} 参数化操作模板`
    }
  }
  if (baseCmd === 'systemctl' || baseCmd === 'journalctl') {
    return {
      category: '系统服务管控',
      title: `Systemd 服务 ${subCmd ?? '日志/状态'} 快捷管控`
    }
  }
  if (baseCmd === 'ufw' || baseCmd === 'iptables' || baseCmd === 'ss' || baseCmd === 'netstat' || baseCmd === 'curl') {
    return {
      category: '网络与端口排查',
      title: `${baseCmd.toUpperCase()} 网络与防火墙规则模板`
    }
  }
  if (baseCmd === 'mysqldump' || baseCmd === 'psql' || baseCmd === 'redis-cli') {
    return {
      category: '数据库维护',
      title: `${baseCmd} 数据库备份与诊断模板`
    }
  }
  return {
    category: '日志与文件分析',
    title: `${baseCmd} 高频检索与处理模板`
  }
}

/**
 * 核心聚类与参数化提炼算法：从原始历史命令数组中自动识别高频相似命令并生成模板
 */
export function extractParameterizedClusters(rawHistoryLines: string[]): ExtractedCommandCluster[] {
  const buckets = new Map<string, TokenizedCommand[]>()

  for (const line of rawHistoryLines) {
    const parsed = tokenizeShellCommand(line)
    if (!parsed) continue
    const list = buckets.get(parsed.skeletonHash) ?? []
    list.push(parsed)
    buckets.set(parsed.skeletonHash, list)
  }

  const results: ExtractedCommandCluster[] = []

  for (const [skeletonHash, group] of buckets.entries()) {
    if (group.length < 2) continue

    const tokenCount = group[0].tokens.length
    const templateTokens: string[] = []
    const variables: CommandVariableSlot[] = []
    let slotCounter = 1

    for (let i = 0; i < tokenCount; i++) {
      const columnValues = group.map((g) => g.tokens[i])
      const distinctValues = new Set(columnValues)

      if (distinctValues.size === 1) {
        templateTokens.push(columnValues[0])
      } else {
        const prevToken = i > 0 ? group[0].tokens[i - 1] : undefined
        const slot = inferVariableMeta(prevToken, columnValues, slotCounter++)
        // 避免重名变量
        if (variables.some((v) => v.name === slot.name)) {
          slot.name = `${slot.name}_${slotCounter}`
        }
        variables.push(slot)
        templateTokens.push(`{{${slot.name}:${slot.defaultValue}}}`)
      }
    }

    // 即使完全相同但重复执行 >= 3 次的高价值长命令也提炼
    if (variables.length === 0 && (group.length < 3 || tokenCount < 4)) {
      continue
    }

    const { category, title } = inferCategoryAndTitle(group[0].baseCmd, group[0].subCmd)
    const uniqueRawExamples = Array.from(new Set(group.map((g) => g.raw)))

    results.push({
      id: `cluster_${skeletonHash.replace(/[^a-zA-Z0-9]/g, '_')}`,
      skeletonHash,
      baseCommand: group[0].baseCmd,
      proposedTemplate: templateTokens.join(' '),
      proposedTitle: title,
      proposedCategory: category,
      occurrenceCount: group.length,
      rawExamples: uniqueRawExamples.slice(0, 5),
      variables,
      confidence: Math.min(99, 78 + group.length * 4 + variables.length * 3),
      llmAnnotated: false
    })
  }

  return results.sort((a, b) => b.occurrenceCount - a.occurrenceCount)
}

/**
 * 统计命令前缀分布
 */
export function computeCommandPrefixStats(rawHistoryLines: string[]): Array<{ prefix: string; count: number; percent: number }> {
  const counts = new Map<string, number>()
  let total = 0

  for (const line of rawHistoryLines) {
    const parsed = tokenizeShellCommand(line)
    if (!parsed) continue
    counts.set(parsed.baseCmd, (counts.get(parsed.baseCmd) ?? 0) + 1)
    total++
  }

  if (total === 0) return []

  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([prefix, count]) => ({
      prefix,
      count,
      percent: Math.round((count / total) * 100)
    }))
}
