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
  Play,
  FileCode2,
  Plus,
  Clock,
  CheckCircle2
} from 'lucide-vue-next'

const cronPresets = [
  { label: '每 5 分钟', expr: '*/5 * * * *', desc: '每 5 分钟执行一次' },
  { label: '每小时整点', expr: '0 * * * *', desc: '每小时第 0 分钟执行' },
  { label: '每天凌晨 02:00', expr: '0 2 * * *', desc: '每天 02:00 准时执行' },
  { label: '每周日凌晨 03:30', expr: '30 3 * * 0', desc: '每周日 03:30 执行' }
]

const builderForm = ref({
  title: '自动清理超过 14 天的 Docker 容器日志',
  expression: '0 2 * * *',
  command: '/opt/scripts/backup_db.sh',
  appendLogRedirect: true
})

const busyTaskIds = ref<Record<string, boolean>>({})
const addingTask = ref(false)

function matchesCronField(value: number, field: string, min: number, max: number): boolean {
  if (field === '*') return true
  return field.split(',').some((piece) => {
    const [base, stepText] = piece.split('/')
    const step = stepText ? Number(stepText) : 1
    if (!Number.isInteger(step) || step < 1) return false
    let start = min
    let end = max
    if (base === '*') {
      // Keep the full range.
    } else if (base.includes('-')) {
      const [a, b] = base.split('-').map(Number)
      if (!Number.isInteger(a) || !Number.isInteger(b)) return false
      start = a
      end = b
    } else {
      start = Number(base)
      end = start
    }
    return value >= start && value <= end && (value - start) % step === 0
  })
}

function nextCronRuns(expression: string, count = 3): string[] {
  const expr = expression.trim()
  if (expr === '@reboot') return ['下次系统重启时']
  const aliases: Record<string, string> = {
    '@hourly': '0 * * * *',
    '@daily': '0 0 * * *',
    '@midnight': '0 0 * * *',
    '@weekly': '0 0 * * 0',
    '@monthly': '0 0 1 * *',
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *'
  }
  const fields = (aliases[expr] || expr).split(/\s+/)
  if (fields.length !== 5) return []
  const allowed = (field: string, min: number, max: number) =>
    Array.from({ length: max - min + 1 }, (_, index) => min + index).filter((value) => matchesCronField(value, field, min, max))
  const minutes = allowed(fields[0], 0, 59)
  const hours = allowed(fields[1], 0, 23)
  const result: string[] = []
  const now = new Date()
  now.setSeconds(0, 0)
  for (let dayOffset = 0; dayOffset <= 366 && result.length < count; dayOffset += 1) {
    const cursor = new Date(now)
    cursor.setHours(0, 0, 0, 0)
    cursor.setDate(cursor.getDate() + dayOffset)
    const dom = matchesCronField(cursor.getDate(), fields[2], 1, 31)
    const dow = matchesCronField(cursor.getDay(), fields[4], 0, 7)
    const dayMatches = fields[2] !== '*' && fields[4] !== '*' ? dom || dow : dom && dow
    if (dayMatches && matchesCronField(cursor.getMonth() + 1, fields[3], 1, 12)) {
      for (const hour of hours) {
        for (const minute of minutes) {
          const candidate = new Date(cursor)
          candidate.setHours(hour, minute, 0, 0)
          if (candidate <= now) continue
          const pad = (value: number) => String(value).padStart(2, '0')
          result.push(`${candidate.getFullYear()}-${pad(candidate.getMonth() + 1)}-${pad(candidate.getDate())} ${pad(candidate.getHours())}:${pad(candidate.getMinutes())}:00`)
          if (result.length >= count) break
        }
        if (result.length >= count) break
      }
    }
  }
  return result
}

const currentNaturalPreview = computed(() => {
  const found = cronPresets.find((p) => p.expr === builderForm.value.expression.trim())
  if (found) return { ...found, next: nextCronRuns(found.expr) }
  return {
    label: '自定义表达式',
    expr: builderForm.value.expression,
    desc: `按 Cron 表达式 "${builderForm.value.expression}" 周期调度`,
    next: nextCronRuns(builderForm.value.expression)
  }
})

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
    <!-- 上半区：Cron 可视化构建器 (自然语言实时翻译 + 未来执行时间点预测) -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 class="text-sm font-bold text-slate-100 flex items-center gap-2">
            <CalendarClock class="w-4 h-4 text-cyan-400" />
            <span>计划任务管理</span>
          </h1>
          <p class="text-xs text-slate-400 mt-0.5">
            Crontab 表达式构建与执行时间预测。
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

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-3 text-xs">
        <div class="space-y-1.5">
          <label class="text-slate-400">任务备注名称</label>
          <input
            v-model="builderForm.title"
            type="text"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-100"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-slate-400 flex justify-between">
            <span>Cron 表达式 (分 时 日 月 周)</span>
            <span class="text-emerald-400 font-semibold">{{ currentNaturalPreview.desc }}</span>
          </label>
          <input
            v-model="builderForm.expression"
            type="text"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 font-mono text-amber-300"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-slate-400">执行脚本路径或 Shell 命令</label>
          <input
            v-model="builderForm.command"
            type="text"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 font-mono text-cyan-300"
          />
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-800 text-xs">
        <div class="flex items-center gap-4">
          <div class="flex items-center gap-1.5 text-slate-300">
            <Clock class="w-3.5 h-3.5 text-cyan-400" />
            <span>未来 3 次触发时间预测：</span>
            <span
              v-for="t in currentNaturalPreview.next"
              :key="t"
              class="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-emerald-300"
            >
              {{ t }}
            </span>
          </div>

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
            <span class="text-xs text-emerald-400 font-medium">({{ task.naturalLanguage }})</span>
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
            <span>下次执行: {{ task.nextRuns[0] }}</span>
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
