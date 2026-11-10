<script setup lang="ts">
import { ref } from 'vue'
import { store, currentHost, executeTerminalCommand } from '@/stores/workbenchStore'
import { Terminal, ChevronDown, Send, Maximize2 } from 'lucide-vue-next'

const inputCmd = ref('')

function handleSend() {
  if (!inputCmd.value.trim()) return
  executeTerminalCommand(inputCmd.value)
  inputCmd.value = ''
}
</script>

<template>
  <section
    v-if="store.bottomTerminalOpen && store.activePage !== 'P1_WORKBENCH'"
    aria-label="底部随行 SSH 终端抽屉"
    class="h-56 bg-slate-950 border-t border-cyan-500/40 flex flex-col shrink-0 shadow-2xl"
  >
    <!-- 抽屉顶栏 -->
    <div class="h-8 bg-slate-900 px-3 flex items-center justify-between border-b border-slate-800 text-xs">
      <div class="flex items-center gap-2">
        <Terminal class="w-3.5 h-3.5 text-cyan-400" />
        <span class="font-medium text-slate-200">
          随行 SSH 终端会话 ({{ currentHost.user }}@{{ currentHost.ip }})
        </span>
        <span class="text-[11px] font-mono text-amber-300 bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800">
          {{ currentHost.currentCwd }}
        </span>
        <span class="text-[11px] text-slate-400">
          切换页面不中断连接 · 支持直接注入可视化生成的命令
        </span>
      </div>

      <div class="flex items-center gap-1.5">
        <button
          type="button"
          @click="store.activePage = 'P1_WORKBENCH'"
          class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] cursor-pointer"
        >
          <Maximize2 class="w-3 h-3" />
          <span>切回完整工作台 (P1)</span>
        </button>
        <button
          type="button"
          @click="store.bottomTerminalOpen = false"
          aria-label="收起随行终端"
          class="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-100 cursor-pointer"
        >
          <ChevronDown class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 终端输出流 -->
    <div class="flex-1 overflow-y-auto p-3 font-mono text-xs space-y-2">
      <div
        v-for="item in store.terminalHistory.slice(-4)"
        :key="item.id"
        class="space-y-1 border-l-2 border-cyan-500/40 pl-2.5"
      >
        <div class="flex items-center gap-2 text-slate-400">
          <span class="text-emerald-400">{{ currentHost.user }}@{{ currentHost.name }}</span>
          <span class="text-amber-300">{{ item.cwd }}#</span>
          <span class="text-slate-100 font-semibold">{{ item.command }}</span>
          <span class="text-[10px] text-slate-500 ml-auto">{{ item.timestamp }} ({{ item.durationMs }}ms)</span>
        </div>
        <pre class="text-slate-300 whitespace-pre-wrap text-[11px] leading-relaxed">{{ item.output }}</pre>
      </div>
    </div>

    <!-- 命令输入行 -->
    <form @submit.prevent="handleSend" class="h-9 bg-slate-900/90 border-t border-slate-800 px-3 flex items-center gap-2">
      <span class="font-mono text-xs text-emerald-400 shrink-0">
        {{ currentHost.user }}@{{ currentHost.name }}:{{ currentHost.currentCwd }}#
      </span>
      <input
        v-model="inputCmd"
        type="text"
        placeholder="输入命令并回车（如 systemctl status nginx 或 cd /var/log）..."
        class="flex-1 bg-transparent text-xs font-mono text-slate-100 focus:outline-none"
      />
      <button
        type="submit"
        class="flex items-center gap-1 px-2.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium cursor-pointer"
      >
        <Send class="w-3 h-3" />
        <span>执行</span>
      </button>
    </form>
  </section>
</template>
