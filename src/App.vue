<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { store } from '@/stores/workbenchStore'
import TopSessionBar from '@/components/layout/TopSessionBar.vue'
import MiniHudBar from '@/components/layout/MiniHudBar.vue'
import SidebarNav from '@/components/layout/SidebarNav.vue'
import BottomTerminalDock from '@/components/layout/BottomTerminalDock.vue'
import FileEditorDrawer from '@/components/layout/FileEditorDrawer.vue'
import CommandPaletteModal from '@/components/layout/CommandPaletteModal.vue'

import HostsHubView from '@/views/HostsHubView.vue'
import TerminalWorkbenchView from '@/views/TerminalWorkbenchView.vue'
import MetricsProcessView from '@/views/MetricsProcessView.vue'
import FileManagerView from '@/views/FileManagerView.vue'
import CommandIntelView from '@/views/CommandIntelView.vue'
import DockerStudioView from '@/views/DockerStudioView.vue'
import SystemdManagerView from '@/views/SystemdManagerView.vue'
import CronManagerView from '@/views/CronManagerView.vue'
import FirewallSecurityView from '@/views/FirewallSecurityView.vue'

import { Terminal, X, CheckCircle2 } from 'lucide-vue-next'

function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    store.commandPaletteOpen = !store.commandPaletteOpen
  } else if (e.ctrlKey && e.key === '`') {
    e.preventDefault()
    if (store.activePage !== 'P1_WORKBENCH') {
      store.bottomTerminalOpen = !store.bottomTerminalOpen
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <div class="h-screen w-screen flex flex-row bg-slate-950 text-slate-100 overflow-hidden">
    <!-- 1. 最左侧顶天立地：功能视图导航 (最高层级) -->
    <SidebarNav />

    <!-- 2. 右侧主体容器 (顶部会话栏 + Mini HUD + 主舞台 + 随行终端) -->
    <div class="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden relative">
      <!-- 顶部多服务器会话标签与全局命令栏 -->
      <TopSessionBar />

      <!-- 顶部常驻微缩遥测指标与联动横幅 (Mini HUD) -->
      <MiniHudBar v-if="store.activePage !== 'P0_HOSTS'" />

      <!-- 中央主舞台 + 随行终端 -->
      <div class="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden relative">
        <main class="flex-1 min-h-0 overflow-hidden">
          <HostsHubView v-if="store.activePage === 'P0_HOSTS'" />
          <TerminalWorkbenchView v-else-if="store.activePage === 'P1_WORKBENCH'" />
          <MetricsProcessView v-else-if="store.activePage === 'P2_METRICS_PROCESS'" />
          <FileManagerView v-else-if="store.activePage === 'P3_FILES'" />
          <CommandIntelView v-else-if="store.activePage === 'P4_COMMANDS'" />
          <DockerStudioView v-else-if="store.activePage === 'P5_DOCKER'" />
          <SystemdManagerView v-else-if="store.activePage === 'P6_SYSTEMD'" />
          <CronManagerView v-else-if="store.activePage === 'P7_CRON'" />
          <FirewallSecurityView v-else-if="store.activePage === 'P8_FIREWALL'" />
        </main>

        <!-- 底部常驻可折叠随行终端 (切换 P2-P8 时不中断 SSH 会话) -->
        <BottomTerminalDock />
      </div>

      <!-- 右侧滑出式远程代码/配置编辑器抽屉 -->
      <FileEditorDrawer />
    </div>

    <!-- 独立悬浮日志盯盘窗口 (模拟可拖出的独立子窗口) -->
    <aside
      v-if="store.detachedLogWindow.open"
      aria-label="独立实时日志盯盘悬浮窗"
      class="fixed bottom-5 right-5 w-[460px] bg-slate-900/95 border border-purple-500/50 rounded-xl shadow-2xl z-30 overflow-hidden backdrop-blur"
    >
      <div class="px-3 py-2 bg-slate-950 border-b border-slate-800 flex items-center justify-between text-xs">
        <div class="flex items-center gap-2 text-purple-300 font-mono font-semibold">
          <Terminal class="w-3.5 h-3.5" />
          <span>独立置顶日志窗: {{ store.detachedLogWindow.title }}</span>
        </div>
        <button
          type="button"
          @click="store.detachedLogWindow.open = false"
          aria-label="关闭独立日志悬浮窗"
          class="text-slate-400 hover:text-slate-100 cursor-pointer"
        >
          <X class="w-3.5 h-3.5" />
        </button>
      </div>
      <div class="p-3 font-mono text-[11px] text-slate-300 space-y-1.5 max-h-44 overflow-y-auto">
        <div v-for="(line, idx) in store.detachedLogWindow.lines" :key="idx" class="leading-relaxed">
          {{ line }}
        </div>
      </div>
    </aside>

    <!-- 全局操作反馈 Toast -->
    <div
      v-if="store.toastMessage"
      role="status"
      aria-live="polite"
      class="fixed bottom-5 left-1/2 -translate-x-1/2 px-4 py-2 rounded-full bg-cyan-950/95 border border-cyan-500/60 text-cyan-200 text-xs font-medium shadow-2xl flex items-center gap-2 z-50"
    >
      <CheckCircle2 class="w-4 h-4 text-emerald-400 shrink-0" />
      <span>{{ store.toastMessage }}</span>
    </div>

    <!-- 全局原生 <dialog> 模态框组 (Cmd+K 面板 & 参数化命令填参弹窗) -->
    <CommandPaletteModal />
  </div>
</template>
