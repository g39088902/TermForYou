<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  inspectHost,
  openFileInEditor,
  showToast,
  createCronTask,
  setCronTaskEnabled,
  runCronTask
} from '@/stores/workbenchStore'
import type { CronTaskItem } from '@/types'
import {
  CalendarClock,
  Globe,
  Play,
  FileCode2,
  Plus,
  CheckCircle2
} from 'lucide-vue-next'

const cronPresets = [
  { label: '每 5 分钟', expr: '*/5 * * * *' },
  { label: '每小时整点', expr: '0 * * * *' },
  { label: '每天凌晨 02:00', expr: '0 2 * * *' },
  { label: '每周日凌晨 03:30', expr: '30 3 * * 0' }
]

const builderForm = ref({
  title: '自动清理超过 14 天的 Docker 容器日志',
  expression: '0 2 * * *',
  command: '/opt/scripts/backup_db.sh',
  appendLogRedirect: true
})

const busyTaskIds = ref<Record<string, boolean>>({})
const addingTask = ref(false)

const weekdayNames = ['日', '一', '二', '三', '四', '五', '六', '日']

// 北京时间固定为 UTC+08:00；crontab 按服务器本地时区触发，提示语统一换算到该口径。
const BEIJING_UTC_OFFSET = 480

const pad2 = (value: number) => String(value).padStart(2, '0')

/** 解析 `+0800` / `+08:00` 形式的偏移，返回分钟数；无法解析时返回 null。 */
function parseUtcOffset(text?: string | null): number | null {
  if (!text) return null
  const match = /^([+-])(\d{2}):?(\d{2})$/.exec(text.trim())
  if (!match) return null
  const minutes = Number(match[2]) * 60 + Number(match[3])
  return match[1] === '-' ? -minutes : minutes
}

function formatUtcOffset(minutes: number): string {
  const sign = minutes < 0 ? '-' : '+'
  const abs = Math.abs(minutes)
  return `UTC${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`
}

/** 多个时间点跨日情况不一致时给出「部分跨日」，避免只标注其中一种。 */
function describeDayShift(shifts: number[]): string {
  const unique = Array.from(new Set(shifts))
  if (unique.length === 1) {
    if (unique[0] === 0) return ''
    return unique[0] > 0 ? '次日' : '前一日'
  }
  return '部分跨日'
}

const serverOffsetMinutes = computed(() => parseUtcOffset(store.serverTimezone?.utcOffset))

const serverTimezoneText = computed(() => {
  const timezone = store.serverTimezone
  if (!timezone?.utcOffset) return store.cronTasksLoading ? '读取中…' : '未知'
  const offset = parseUtcOffset(timezone.utcOffset)
  return [
    timezone.name && timezone.name !== 'unknown' ? timezone.name : '',
    offset === null ? timezone.utcOffset : formatUtcOffset(offset),
    timezone.abbreviation && timezone.abbreviation !== timezone.utcOffset ? timezone.abbreviation : ''
  ]
    .filter(Boolean)
    .join(' · ')
})

const timezoneSummary = computed(() => {
  const offset = serverOffsetMinutes.value
  if (offset === null) {
    return store.cronTasksLoading ? '正在读取服务器时区…' : '未能读取服务器时区'
  }
  const delta = offset - BEIJING_UTC_OFFSET
  if (delta === 0) return '与北京时间一致'
  const abs = Math.abs(delta)
  const span = [abs >= 60 ? `${Math.floor(abs / 60)} 小时` : '', abs % 60 ? `${abs % 60} 分钟` : '']
    .filter(Boolean)
    .join(' ')
  return `比北京时间${delta < 0 ? '慢' : '快'} ${span}`
})

function describeCron(expression: string): string {
  return cronNaturalLanguage(expression, serverOffsetMinutes.value)
}

/** 月份与星期的字母别名：crontab 允许 `JAN`、`MON-FRI` 这类写法，解析前先归一化成数字。 */
const MONTH_NAMES: Record<string, number> = {
  jan: 1,
  feb: 2,
  mar: 3,
  apr: 4,
  may: 5,
  jun: 6,
  jul: 7,
  aug: 8,
  sep: 9,
  oct: 10,
  nov: 11,
  dec: 12
}
const WEEKDAY_NAMES: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 }

const CRON_ALIASES: Record<string, string> = {
  '@hourly': '0 * * * *',
  '@daily': '0 0 * * *',
  '@midnight': '0 0 * * *',
  '@weekly': '0 0 * * 0',
  '@monthly': '0 0 1 * *',
  '@yearly': '0 0 1 1 *',
  '@annually': '0 0 1 1 *'
}

interface CronFieldSpec {
  label: string
  min: number
  max: number
  names?: Record<string, number>
}

interface CronFieldResult {
  values: number[]
  normalized: string
}

type CronParseResult =
  | { kind: 'reboot' }
  | {
      kind: 'fields'
      minute: CronFieldResult
      hour: CronFieldResult
      day: CronFieldResult
      month: CronFieldResult
      weekday: CronFieldResult
    }
  | { kind: 'error'; error: string }

/**
 * 校验并展开单个 cron 字段。
 *
 * 支持 `*`、单值、`a-b` 区间、`* /n` 步长、`a/n`（从 a 到字段上界）、`a-b/n` 和逗号列表；
 * 字母别名（`mon`、`jan` 等）先换成数字。任何越界、空项、非法步长都返回错误，
 * 避免把 `99` 这类非法值悄悄取模成一个看起来合法的时间。
 */
function parseCronField(raw: string, spec: CronFieldSpec): CronFieldResult | { error: string } {
  const { label, min, max, names } = spec
  // 只替换真正能识别的别名，其余字母原样保留，交给后续语法校验拒绝。
  const normalized = names
    ? raw.replace(/[a-z]+/g, (token) => (names[token] === undefined ? token : String(names[token])))
    : raw
  const values = new Set<number>()
  for (const piece of normalized.split(',')) {
    if (!piece) return { error: `${label}字段存在空的取值项` }
    const [base, stepText, ...extra] = piece.split('/')
    if (extra.length) return { error: `${label}字段「${piece}」格式不支持` }
    let step = 1
    if (stepText !== undefined) {
      if (!/^\d+$/.test(stepText) || Number(stepText) < 1) return { error: `${label}字段的步长必须是正整数` }
      step = Number(stepText)
      if (step > max) return { error: `${label}字段的步长 ${step} 超出 ${min}–${max} 范围` }
    }
    let start: number
    let end: number
    if (base === '*') {
      start = min
      end = max
    } else if (base.includes('-')) {
      const [from, to, ...rest] = base.split('-')
      if (rest.length || !/^\d+$/.test(from) || !/^\d+$/.test(to)) {
        return { error: `${label}字段「${base}」不是合法区间` }
      }
      start = Number(from)
      end = Number(to)
    } else if (/^\d+$/.test(base)) {
      start = Number(base)
      // crontab 里 `a/n` 表示「从 a 开始到字段上界，步长 n」。
      end = stepText === undefined ? start : max
    } else {
      return { error: `${label}字段「${base}」无法识别` }
    }
    if (start < min || start > max || end < min || end > max) {
      return { error: `${label}字段「${base}」超出 ${min}–${max} 范围` }
    }
    if (end < start) return { error: `${label}字段「${base}」的起止顺序颠倒` }
    for (let value = start; value <= end; value += step) values.add(value)
  }
  return { values: Array.from(values).sort((a, b) => a - b), normalized }
}

/** 解析整条表达式：特殊别名单独处理，5 段字段逐一校验。 */
function parseCronExpression(expression: string): CronParseResult {
  const expr = expression.trim().toLowerCase()
  if (!expr) return { kind: 'error', error: '表达式为空' }
  if (expr === '@reboot') return { kind: 'reboot' }
  const fields = (CRON_ALIASES[expr] || expr).split(/\s+/)
  if (fields.length !== 5) return { kind: 'error', error: '需要 5 段（分 时 日 月 周）' }
  const [minute, hour, day, month, weekday] = fields
  const results = [
    parseCronField(minute, { label: '分钟', min: 0, max: 59 }),
    parseCronField(hour, { label: '小时', min: 0, max: 23 }),
    parseCronField(day, { label: '日', min: 1, max: 31 }),
    parseCronField(month, { label: '月', min: 1, max: 12, names: MONTH_NAMES }),
    parseCronField(weekday, { label: '星期', min: 0, max: 7, names: WEEKDAY_NAMES })
  ]
  const failed = results.find((item) => 'error' in item)
  if (failed && 'error' in failed) return { kind: 'error', error: failed.error }
  const [minuteResult, hourResult, dayResult, monthResult, weekdayResult] = results as CronFieldResult[]
  return {
    kind: 'fields',
    minute: minuteResult,
    hour: hourResult,
    day: dayResult,
    month: monthResult,
    weekday: weekdayResult
  }
}

/** 星期按「周一…周日」排序，连续段合并成「周一至周五」。 */
function describeWeekdays(values: number[]): string {
  // 0 和 7 都表示周日，统一换算成 7 排到一周末尾。
  const keys = Array.from(new Set(values.map((value) => (value % 7 === 0 ? 7 : value % 7)))).sort((a, b) => a - b)
  const parts: string[] = []
  let index = 0
  while (index < keys.length) {
    let end = index
    while (end + 1 < keys.length && keys[end + 1] === keys[end] + 1) end += 1
    parts.push(
      end > index ? `周${weekdayNames[keys[index]]}至周${weekdayNames[keys[end]]}` : `周${weekdayNames[keys[index]]}`
    )
    index = end + 1
  }
  return parts.join('、')
}

function cronNaturalLanguage(expression: string, offsetMinutes: number | null): string {
  const parsed = parseCronExpression(expression)
  if (parsed.kind === 'reboot') return '系统启动时执行'
  if (parsed.kind === 'error') return `表达式有误：${parsed.error}`

  const minute = parsed.minute.normalized
  const hour = parsed.hour.normalized
  const month = parsed.month.normalized
  const day = parsed.day.normalized
  const monthValues = parsed.month.values
  const dayValues = parsed.day.values
  const weekdayValues = parsed.weekday.values

  // 时区未知时不做换算，文案明确标注为服务器本地时间，避免假装是北京时间。
  const convertible = offsetMinutes !== null
  const shiftDelta = convertible ? BEIJING_UTC_OFFSET - (offsetMinutes as number) : 0
  /** 服务器本地时刻 → 北京时间；dayShift 表示换算后落在次日（1）或前一日（-1）。 */
  const shiftClock = (hourValue: number, minuteValue: number) => {
    const total = hourValue * 60 + minuteValue + shiftDelta
    const normalized = ((total % 1440) + 1440) % 1440
    return {
      text: `${pad2(Math.floor(normalized / 60))}:${pad2(normalized % 60)}`,
      dayShift: Math.floor(total / 1440)
    }
  }
  const shiftMinute = (minuteValue: number) => (((minuteValue + shiftDelta) % 60) + 60) % 60
  let dayNote = ''
  let fixedClock = false

  let time = ''
  if (minute === '*' && hour === '*') {
    time = '每分钟'
  } else if (hour === '*' && /^\*\/\d+$/.test(minute)) {
    time = `每 ${minute.slice(2)} 分钟`
  } else if (hour === '*' && minute === '0') {
    // 整点按小时循环，整小时偏移下与北京时间的整点一致；半小时时区（如 +05:30）才需要换算分钟。
    const shifted = shiftMinute(0)
    time = shifted === 0 ? '每小时整点' : `每小时第 ${pad2(shifted)} 分钟`
  } else if (hour === '*' && /^\d+(,\d+)*$/.test(minute)) {
    const minutes = minute
      .split(',')
      .map((value) => shiftMinute(Number(value)))
      .sort((a, b) => a - b)
      .map(pad2)
    time = `每小时第 ${minutes.join('、')} 分钟`
  } else if (/^(\d+)\/(\d+)$/.test(hour) && /^\d+$/.test(minute)) {
    const [, start, step] = /^(\d+)\/(\d+)$/.exec(hour) ?? []
    const shifted = shiftClock(Number(start), Number(minute))
    fixedClock = true
    time = `从 ${shifted.text} 起每 ${step} 小时`
  } else if (/^\*\/\d+$/.test(hour) && /^\d+$/.test(minute)) {
    time = `每 ${hour.slice(2)} 小时的第 ${pad2(shiftMinute(Number(minute)))} 分钟`
  } else if (/^(\d+)\/(\d+)$/.test(minute) && hour === '*') {
    const [, start, step] = /^(\d+)\/(\d+)$/.exec(minute) ?? []
    time = `每小时从第 ${pad2(shiftMinute(Number(start)))} 分钟起每 ${step} 分钟`
  } else if (/^\d+(,\d+)*$/.test(hour) && /^\d+(,\d+)*$/.test(minute)) {
    const hours = hour.split(',').map(Number)
    const minutes = minute.split(',').map(Number)
    // 逐个组合成完整时间点，避免拼出「09:00、30」这类歧义串；同时换算为北京时间。
    const points = hours.flatMap((h) => minutes.map((m) => shiftClock(h, m)))
    fixedClock = true
    dayNote = describeDayShift(points.map((point) => point.dayShift))
    // 只有整小时偏移才能把小时、分钟拆开紧凑展示；半小时时区会丢掉分钟相位，必须逐点列出。
    if (hours.length * minutes.length > 6 && shiftDelta % 60 === 0) {
      const hourText = Array.from(new Set(points.map((point) => point.text.slice(0, 2)))).join('、')
      const minuteText = Array.from(new Set(points.map((point) => point.text.slice(3))))
        .sort((a, b) => Number(a) - Number(b))
        .join('、')
      time = `${hourText} 点的第 ${minuteText} 分钟`
    } else {
      time = points.map((point) => point.text).join('、')
    }
  } else if (/^(\d+)-(\d+)$/.test(hour) && /^\*\/\d+$/.test(minute)) {
    // 小时区间 + 分钟步长：换算区间两端，跨零点时明确标注「次日」。
    const [, startHour, endHour] = /^(\d+)-(\d+)$/.exec(hour) ?? []
    const step = minute.slice(2)
    if (convertible) {
      const start = shiftClock(Number(startHour), 0)
      const end = shiftClock(Number(endHour), 0)
      time = `北京时间 ${start.text.slice(0, 2)} 点至${end.dayShift > start.dayShift ? '次日 ' : ' '}${end.text.slice(0, 2)} 点，每 ${step} 分钟`
    } else {
      time = `按服务器时间 ${hour} 时每 ${step} 分钟`
    }
  } else {
    time = `按服务器时间 ${hour} 时 ${minute} 分的周期`
  }

  // 日期部分：用展开后的取值判断是否构成限定，`1-31`、`0-7` 这类全量写法不该被当成限定。
  const monthLimited = monthValues.length < 12
  const dayLimited = dayValues.length < 31
  const weekdayLimited = new Set(weekdayValues.map((value) => value % 7)).size < 7

  const monthStep = /^\*\/(\d+)$/.exec(month)
  const monthOffsetStep = /^(\d+)\/(\d+)$/.exec(month)
  const dayStep = /^\*\/(\d+)$/.exec(day)
  const dayOffsetStep = /^(\d+)\/(\d+)$/.exec(day)
  const dayRangeStep = /^(\d+)-(\d+)\/(\d+)$/.exec(day)

  let schedule = '每天'
  if (monthLimited) {
    if (monthStep) {
      schedule = `每隔 ${monthStep[1]} 个月`
    } else if (monthOffsetStep) {
      schedule = `从 ${monthOffsetStep[1]} 月起每隔 ${monthOffsetStep[2]} 个月`
    } else {
      // 直接罗列展开后的月份，`1-6/2` 才不会退化成 1 到 6 月。
      schedule = `每年 ${monthValues.join('、')} 月`
    }
  }
  if (dayLimited) {
    const prefix = monthLimited ? schedule : '每月'
    if (dayStep) {
      schedule = `${prefix}每隔 ${dayStep[1]} 天`
    } else if (dayOffsetStep) {
      schedule = `${prefix}从 ${dayOffsetStep[1]} 号起每隔 ${dayOffsetStep[2]} 天`
    } else if (dayRangeStep) {
      schedule = `${prefix} ${dayRangeStep[1]} 至 ${dayRangeStep[2]} 日之间每隔 ${dayRangeStep[3]} 天`
    } else {
      schedule = `${prefix} ${dayValues.join('、')} 日`
    }
  }
  if (weekdayLimited) {
    const weekdays = `每${describeWeekdays(weekdayValues)}`
    // crontab 里月份与星期是「与」，日与星期同时限定时才是「或」。
    if (schedule === '每天') schedule = weekdays
    else schedule = dayLimited ? `${schedule}或${weekdays}` : `${schedule}的${weekdays}`
  }
  const hasDateRestriction = monthLimited || dayLimited || weekdayLimited
  // 只有落款了绝对时刻才需要注明时区口径；跨日说明只在存在日期限定时有意义（「每天」本身不受影响）。
  const timezoneNote = fixedClock
    ? `（${convertible ? '北京时间' : '服务器本地时间'}${convertible && hasDateRestriction ? dayNote : ''}）`
    : ''
  if (!hasDateRestriction && (time === '每分钟' || time.startsWith('每小时') || /^每 \d+ (?:分钟|小时)/.test(time))) return `${time}执行${timezoneNote}`
  // 「每 10 分钟」「每 2 小时」这类以频率收尾的短语，与「执行」之间不再多插一个空格。
  const connector = /(?:分钟|小时)$/.test(time) ? '' : ' '
  return `${schedule} ${time}${connector}执行${timezoneNote}`
}

const currentNaturalPreview = computed(() => {
  const found = cronPresets.find((p) => p.expr === builderForm.value.expression.trim())
  if (found) return { ...found, desc: describeCron(found.expr) }
  return {
    label: '自定义表达式',
    expr: builderForm.value.expression,
    desc: describeCron(builderForm.value.expression)
  }
})

/** 表达式非法时预览改用警示色，避免用户把错误文案当成可用配置。 */
const currentExpressionInvalid = computed(() => parseCronExpression(builderForm.value.expression).kind === 'error')

async function dryRunTask(task: CronTaskItem) {
  if (busyTaskIds.value[task.id]) return
  busyTaskIds.value[task.id] = true
  try {
    await runCronTask(task)
  } finally {
    delete busyTaskIds.value[task.id]
  }
}

async function toggleTaskEnabled(task: CronTaskItem) {
  if (busyTaskIds.value[task.id]) return
  busyTaskIds.value[task.id] = true
  try {
    await setCronTaskEnabled(task, !task.enabled)
  } finally {
    delete busyTaskIds.value[task.id]
  }
}

async function addCronTask() {
  if (addingTask.value) return
  const expression = builderForm.value.expression.trim()
  const command = builderForm.value.command.trim()
  const title = builderForm.value.title.trim()
  if (!title || !expression || !command) {
    showToast('任务名称、Cron 表达式和命令不能为空')
    return
  }
  // 本地先拦一次非法表达式，避免远端 crontab 只回一句 bad minute 这类英文报错。
  const expressionCheck = parseCronExpression(expression)
  if (expressionCheck.kind === 'error') {
    showToast(`Cron 表达式有误：${expressionCheck.error}`)
    return
  }
  const finalCmd = builderForm.value.appendLogRedirect
    ? `${command} >> /var/log/cron.log 2>&1`
    : command
  addingTask.value = true
  try {
    await createCronTask({ title, expression, command: finalCmd })
  } finally {
    addingTask.value = false
  }
}
</script>

<template>
  <div class="p-5 space-y-5 overflow-y-auto h-full">
    <!-- 上半区：Cron 可视化构建器 (自然语言实时翻译) -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 class="text-sm font-bold text-slate-100 flex items-center gap-2">
            <CalendarClock class="w-4 h-4 text-cyan-400" />
            <span>计划任务管理</span>
          </h1>
          <p class="text-xs text-slate-400 mt-0.5">
            Crontab 表达式构建与自然语言解释。
          </p>
        </div>

        <!-- 快捷预设胶囊 -->
        <div class="flex items-center gap-1.5 flex-wrap">
          <button
            v-for="preset in cronPresets"
            :key="preset.expr"
            type="button"
            @click="builderForm.expression = preset.expr"
            :class="[
              'px-2.5 py-1 rounded-md text-xs font-mono border transition cursor-pointer',
              builderForm.expression === preset.expr
                ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
                : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200'
            ]"
          >
            {{ preset.label }} ({{ preset.expr }})
          </button>
        </div>
      </div>

      <!-- 服务器时区：crontab 按服务器本地时区触发，提示语统一换算为北京时间 -->
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-[11px]">
        <span class="flex items-center gap-1.5 font-medium text-slate-400">
          <Globe class="w-3.5 h-3.5 text-cyan-400" />
          <span>服务器时区</span>
        </span>
        <span class="font-mono font-semibold text-cyan-300">{{ serverTimezoneText }}</span>
        <span
          :class="[
            'px-1.5 py-0.5 rounded border',
            serverOffsetMinutes === null
              ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
              : serverOffsetMinutes === BEIJING_UTC_OFFSET
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300'
          ]"
        >
          {{ timezoneSummary }}
        </span>
        <span v-if="serverOffsetMinutes !== null" class="ml-auto flex items-center gap-1.5 text-slate-500">
          <span class="hidden sm:inline">提示语按</span>
          <span class="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700 font-mono text-[10px] text-emerald-300">
            北京时间 UTC+08:00
          </span>
          <span class="hidden sm:inline">标注</span>
        </span>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-3 text-xs">
        <div class="space-y-1.5">
          <label class="h-5 flex items-center text-slate-400">任务备注名称</label>
          <input
            v-model="builderForm.title"
            type="text"
            class="box-border h-10 w-full px-3 rounded-lg bg-slate-950 border border-slate-700 text-slate-100"
          />
        </div>

        <div class="space-y-1.5">
          <label class="h-5 min-w-0 flex items-center justify-between gap-2 text-slate-400">
            <span class="truncate">Cron 表达式 (分 时 日 月 周)</span>
            <span
              :class="[
                'min-w-0 max-w-[55%] shrink-0 truncate text-right font-semibold',
                currentExpressionInvalid ? 'text-rose-400' : 'text-emerald-400'
              ]"
              :title="currentNaturalPreview.desc"
            >{{ currentNaturalPreview.desc }}</span>
          </label>
          <input
            v-model="builderForm.expression"
            type="text"
            class="box-border h-10 w-full px-3 rounded-lg bg-slate-950 border border-slate-700 font-mono text-amber-300"
          />
        </div>

        <div class="space-y-1.5">
          <label class="h-5 flex items-center text-slate-400">执行脚本路径或 Shell 命令</label>
          <input
            v-model="builderForm.command"
            type="text"
            class="box-border h-10 w-full px-3 rounded-lg bg-slate-950 border border-slate-700 font-mono text-cyan-300"
          />
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-800 text-xs">
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-1.5 text-slate-300 cursor-pointer">
            <input v-model="builderForm.appendLogRedirect" type="checkbox" class="rounded" />
            <span>自动追加标准输出与错误日志重定向 (<code>&gt;&gt; /var/log/cron.log 2&gt;&amp;1</code>)</span>
          </label>
        </div>

        <button
          type="button"
          @click="addCronTask"
          :disabled="addingTask"
          class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-semibold cursor-pointer"
        >
          <Plus class="w-3.5 h-3.5" />
          <span>写入 Crontab 并开启监控</span>
        </button>
      </div>
    </div>

    <!-- 下半区：计划任务列表 -->
    <div class="space-y-3" :aria-busy="store.cronTasksLoading">
      <p v-if="store.cronTasksLoading" role="status" class="text-xs text-slate-400">
        正在读取当前服务器的计划任务…
      </p>
      <div v-else-if="store.cronTasksError" role="alert" class="rounded-xl border border-rose-500/30 bg-rose-500/15 p-4 text-xs text-rose-300">
        {{ store.cronTasksError }}
        <button type="button" class="ml-3 underline cursor-pointer" @click="inspectHost(store.activeHostId)">重试</button>
      </div>
      <p v-else-if="store.cronTasks.length === 0" role="status" class="rounded-xl border border-slate-800 p-4 text-xs text-slate-400">
        当前服务器的 SSH 用户未配置 Crontab 任务。
      </p>
      <div
        v-for="task in store.cronTasks"
        :key="task.id"
        class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4"
      >
        <div class="space-y-2 flex-1">
          <div class="flex items-center gap-2.5 flex-wrap">
            <span
              :class="[
                'px-2 py-0.5 text-[10px] rounded font-mono font-semibold',
                task.engine === 'crontab'
                  ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30'
                  : 'bg-indigo-500/15 text-indigo-300 border border-indigo-500/30'
              ]"
            >
              {{ task.engine.toUpperCase() }}
            </span>
            <span class="px-2.5 py-0.5 rounded bg-slate-950 border border-slate-700 font-mono text-xs text-amber-300 font-bold">
              {{ task.expression }}
            </span>
            <span class="text-xs text-emerald-400 font-medium">{{ describeCron(task.expression) }}</span>
            <h2 class="text-sm font-bold text-slate-100">{{ task.title }}</h2>
          </div>

          <div class="flex items-center gap-2 flex-wrap">
            <code class="px-2.5 py-1 rounded bg-slate-950 border border-slate-800 font-mono text-xs text-slate-200">
              {{ task.command }}
            </code>

            <!-- 跨模块联动：点击脚本路径直接在内置代码编辑器打开该 .sh 脚本 -->
            <button
              v-if="task.scriptPath"
              type="button"
              @click="openFileInEditor(task.scriptPath)"
              class="flex items-center gap-1 px-2.5 py-1 rounded bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-500/30 text-xs cursor-pointer"
            >
              <FileCode2 class="w-3.5 h-3.5" />
              <span>直接编辑脚本 {{ task.scriptPath }}</span>
            </button>
          </div>

          <div class="flex items-center gap-4 text-[11px] text-slate-400 font-mono">
            <span class="flex items-center gap-1 text-emerald-400">
              <CheckCircle2 class="w-3.5 h-3.5" />
              上次运行: {{ task.lastRunAt }} (Exit {{ task.lastExitCode ?? '—' }})
            </span>
            <span class="text-slate-500 truncate">输出摘要: {{ task.lastOutput }}</span>
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <button
            type="button"
            @click="dryRunTask(task)"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-cyan-300 font-medium cursor-pointer"
          >
            <Play class="w-3.5 h-3.5" />
            <span>立即试运行一次</span>
          </button>

          <button
            type="button"
            @click="toggleTaskEnabled(task)"
            :class="[
              'px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer border',
              task.enabled
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            ]"
          >
            {{ task.enabled ? '已启用 (点击注释禁用)' : '已注释禁用' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
