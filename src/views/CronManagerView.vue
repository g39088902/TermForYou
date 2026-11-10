<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  openFileInEditor,
  executeTerminalCommand,
  showToast
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
  { label: '每 5 分钟', expr: '*/5 * * * *', desc: '每 5 分钟执行一次', next: ['11:15:00', '11:20:00', '11:25:00'] },
  { label: '每小时整点', expr: '0 * * * *', desc: '每小时第 0 分钟执行', next: ['12:00:00', '13:00:00', '14:00:00'] },
  { label: '每天凌晨 02:00', expr: '0 2 * * *', desc: '每天 02:00 准时执行', next: ['明日 02:00:00', '后日 02:00:00'] },
  { label: '每周日凌晨 03:30', expr: '30 3 * * 0', desc: '每周日 03:30 执行', next: ['周日 03:30:00', '下周日 03:30:00'] }
]

const builderForm = ref({
  title: '自动清理超过 14 天的 Docker 容器日志',
  expression: '0 2 * * *',
  command: '/opt/scripts/backup_db.sh',
  appendLogRedirect: true
})

const currentNaturalPreview = computed(() => {
  const found = cronPresets.find((p) => p.expr === builderForm.value.expression.trim())
  if (found) return found
  return {
    label: '自定义表达式',
    expr: builderForm.value.expression,
    desc: `按 Cron 表达式 "${builderForm.value.expression}" 周期调度`,
    next: ['2026-11-11 02:00:00', '2026-11-12 02:00:00', '2026-11-13 02:00:00']
  }
})

function dryRunTask(task: CronTaskItem) {
  executeTerminalCommand(task.command)
  task.lastRunAt = '刚刚 (手动试运行)'
  showToast(`已手动触发试运行任务：${task.title}`)
}

function toggleTaskEnabled(task: CronTaskItem) {
  task.enabled = !task.enabled
  showToast(
    task.enabled
      ? `已取消注释启用计划任务：${task.title}`
      : `已在 Crontab 中注释禁用计划任务：# ${task.expression}`
  )
}

function addCronTask() {
  const finalCmd = builderForm.value.appendLogRedirect
    ? `${builderForm.value.command} >> /var/log/cron_job.log 2>&1`
    : builderForm.value.command

  store.cronTasks.unshift({
    id: `cron-${Date.now()}`,
    engine: 'crontab',
    title: builderForm.value.title,
    expression: builderForm.value.expression,
    naturalLanguage: currentNaturalPreview.value.desc,
    command: finalCmd,
    scriptPath: builderForm.value.command.startsWith('/') ? builderForm.value.command.split(' ')[0] : undefined,
    user: 'root',
    enabled: true,
    lastRunAt: '尚未执行',
    lastExitCode: 0,
    nextRuns: currentNaturalPreview.value.next,
    lastOutput: '等待首次周期触发...'
  })

  executeTerminalCommand(`(crontab -l 2>/dev/null; echo "${builderForm.value.expression} ${finalCmd}") | crontab -`)
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
          class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-semibold cursor-pointer"
        >
          <Plus class="w-3.5 h-3.5" />
          <span>写入 Crontab 并开启监控</span>
        </button>
      </div>
    </div>

    <!-- 下半区：计划任务列表 -->
    <div class="space-y-3">
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
              上次运行: {{ task.lastRunAt }} (Exit {{ task.lastExitCode }})
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
