<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  prefixStats,
  refreshShellHistory,
  showToast
} from '@/stores/workbenchStore'
import { tokenizeShellCommand } from '@/services/commandExtractor'
import {
  History,
  BarChart3,
  RefreshCw,
  Search,
  Copy,
  Check,
  X
} from 'lucide-vue-next'

const searchQuery = ref('')
const selectedPrefix = ref<string | null>(null)
const copiedIndex = ref<number | null>(null)

const historyEntries = computed(() => {
  return store.rawHistoryLines.map((command, idx) => {
    const parsed = tokenizeShellCommand(command)
    return {
      index: idx + 1,
      command,
      prefix: parsed?.baseCmd ?? ''
    }
  })
})

const filteredHistoryEntries = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const prefix = selectedPrefix.value
  return historyEntries.value.filter((entry) => {
    if (prefix && entry.prefix !== prefix) return false
    if (q && !entry.command.toLowerCase().includes(q)) return false
    return true
  })
})

function togglePrefixFilter(prefix: string) {
  selectedPrefix.value = selectedPrefix.value === prefix ? null : prefix
}

async function copyCommand(command: string, index: number) {
  try {
    await navigator.clipboard.writeText(command)
    copiedIndex.value = index
    showToast('已复制历史命令到剪贴板')
    setTimeout(() => {
      if (copiedIndex.value === index) copiedIndex.value = null
    }, 1500)
  } catch {
    showToast('复制失败，请检查浏览器剪贴板权限')
  }
}
</script>

<template>
  <div class="p-5 space-y-5 overflow-y-auto h-full">
    <!-- 顶栏 -->
    <div class="flex flex-wrap items-center justify-between gap-4 bg-slate-900/90 border border-slate-800 rounded-xl p-4">
      <div>
        <h1 class="text-base font-bold text-slate-100 flex items-center gap-2">
          <History class="w-5 h-5 text-cyan-400" />
          <span>历史命令</span>
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          统计当前主机常用命令前缀分布，留痕并检索远端 Shell 与终端会话历史记录。
        </p>
      </div>

      <div class="flex items-center gap-2">
        <span
          v-if="store.shellHistorySource"
          class="px-2 py-1 rounded-md bg-slate-950 border border-slate-800 text-[11px] font-mono text-slate-300"
        >
          来源: {{ store.shellHistorySource }}
        </span>
        <span class="px-2 py-1 rounded-md bg-slate-950 border border-slate-800 text-[11px] font-mono text-slate-400">
          样本总数: {{ store.rawHistoryLines.length }} 条
        </span>
        <button
          type="button"
          @click="refreshShellHistory()"
          :disabled="!store.activeHostId || store.shellHistoryLoading"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-medium text-slate-200 transition cursor-pointer"
          title="从当前主机重新采集 Shell 历史"
        >
          <RefreshCw :class="['w-3.5 h-3.5', store.shellHistoryLoading ? 'animate-spin' : '']" />
          <span>重新采集</span>
        </button>
      </div>
    </div>

    <!-- 核心区 1：常用命令前缀分布 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
          <BarChart3 class="w-4 h-4 text-cyan-400" />
          <span>常用命令前缀分布</span>
          <span class="text-[11px] font-normal text-slate-400">（点击前缀可筛选下方历史留痕）</span>
        </div>

        <button
          v-if="selectedPrefix"
          type="button"
          @click="selectedPrefix = null"
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 text-[11px] hover:bg-cyan-500/25 cursor-pointer"
        >
          <span>已筛选: {{ selectedPrefix }}</span>
          <X class="w-3 h-3" />
        </button>
      </div>

      <div
        v-if="store.shellHistoryLoading && store.rawHistoryLines.length === 0"
        class="py-6 text-center text-xs text-slate-400 flex items-center justify-center gap-2"
      >
        <RefreshCw class="w-3.5 h-3.5 animate-spin text-cyan-400" />
        <span>正在采集远端主机 Shell 历史记录...</span>
      </div>

      <div
        v-else-if="store.shellHistoryError && store.rawHistoryLines.length === 0"
        class="py-6 text-center text-xs text-rose-300 bg-rose-500/10 border border-rose-500/20 rounded-lg px-3"
      >
        {{ store.shellHistoryError }}
      </div>

      <div
        v-else-if="prefixStats.length === 0"
        class="py-6 text-center text-xs text-slate-400"
      >
        暂无常用命令前缀统计（当前主机历史为空或仅包含基础导航命令）
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2.5">
        <button
          v-for="item in prefixStats"
          :key="item.prefix"
          type="button"
          @click="togglePrefixFilter(item.prefix)"
          :class="[
            'w-full text-left p-2 rounded-lg border transition cursor-pointer space-y-1.5',
            selectedPrefix === item.prefix
              ? 'bg-cyan-500/10 border-cyan-500/50'
              : 'bg-slate-950/60 border-slate-800/80 hover:border-slate-700'
          ]"
        >
          <div class="flex items-center justify-between text-xs font-mono">
            <span class="text-cyan-300 font-semibold">{{ item.prefix }}</span>
            <span class="text-slate-400">{{ item.count }} 次 ({{ item.percent }}%)</span>
          </div>
          <div class="h-1.5 rounded-full bg-slate-950 overflow-hidden">
            <div
              class="h-full bg-gradient-to-r from-cyan-500 to-indigo-500 rounded-full"
              :style="{ width: `${Math.max(8, item.percent)}%` }"
            />
          </div>
        </button>
      </div>
    </div>

    <!-- 核心区 2：历史命令留痕 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
          <History class="w-4 h-4 text-cyan-400" />
          <span>历史命令留痕</span>
          <span class="text-[11px] font-mono font-normal text-slate-400">
            ({{ filteredHistoryEntries.length }} / {{ historyEntries.length }})
          </span>
        </div>

        <div class="relative w-full sm:w-72">
          <Search class="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索历史命令关键词..."
            aria-label="搜索历史命令"
            class="w-full pl-8 pr-8 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs font-mono text-slate-200 placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none"
          />
          <button
            v-if="searchQuery"
            type="button"
            @click="searchQuery = ''"
            class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 cursor-pointer"
            aria-label="清空搜索"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div
        v-if="store.shellHistoryLoading && historyEntries.length === 0"
        class="py-8 text-center text-xs text-slate-400"
      >
        正在加载历史命令留痕...
      </div>

      <div
        v-else-if="filteredHistoryEntries.length === 0"
        class="py-8 text-center text-xs text-slate-400"
      >
        {{ historyEntries.length === 0 ? '当前主机暂无历史命令留痕' : '未匹配到符合筛选条件的历史命令' }}
      </div>

      <div v-else class="divide-y divide-slate-800/80 rounded-lg border border-slate-800 bg-slate-950/70 max-h-[420px] overflow-y-auto">
        <div
          v-for="entry in filteredHistoryEntries"
          :key="`${entry.index}-${entry.command}`"
          class="flex items-center justify-between gap-3 px-3 py-2 hover:bg-slate-900/70 transition"
        >
          <div class="flex items-center gap-2.5 min-w-0">
            <span class="text-[11px] font-mono text-slate-500 w-9 shrink-0 text-right">
              #{{ entry.index }}
            </span>
            <span
              v-if="entry.prefix"
              class="px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 text-[10px] font-mono shrink-0"
            >
              {{ entry.prefix }}
            </span>
            <code class="font-mono text-xs text-slate-200 truncate" :title="entry.command">
              {{ entry.command }}
            </code>
          </div>

          <button
            type="button"
            @click="copyCommand(entry.command, entry.index)"
            class="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-[11px] text-slate-300 shrink-0 cursor-pointer transition"
            title="复制命令"
          >
            <Check v-if="copiedIndex === entry.index" class="w-3 h-3 text-emerald-400" />
            <Copy v-else class="w-3 h-3" />
            <span>{{ copiedIndex === entry.index ? '已复制' : '复制' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
