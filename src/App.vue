<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { store, hasConnectedHost } from '@/stores/workbenchStore'
import TopSessionBar from '@/components/layout/TopSessionBar.vue'
import MiniHudBar from '@/components/layout/MiniHudBar.vue'
import SidebarNav from '@/components/layout/SidebarNav.vue'
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

import { CheckCircle2 } from 'lucide-vue-next'

function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    store.commandPaletteOpen = !store.commandPaletteOpen
  }
}

// 路由安全看门狗：如果用户未连接任何服务器，强制停留在主机连接池 P0_HOSTS
watch(
  () => [hasConnectedHost.value, store.activePage],
  ([connected, page]) => {
    if (!connected && page !== 'P0_HOSTS') {
      store.activePage = 'P0_HOSTS'
    }
  },
  { immediate: true }
)

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

    <!-- 2. 右侧主体容器 (顶部会话栏 + Mini HUD + 主舞台) -->
    <div class="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden relative">
      <!-- 顶部多服务器会话标签与全局命令栏 -->
      <TopSessionBar />

      <!-- 顶部常驻微缩遥测指标与联动横幅 (Mini HUD，仅当已连接服务器且非主机池页面时呈现) -->
      <MiniHudBar v-if="store.activePage !== 'P0_HOSTS' && hasConnectedHost" />

      <!-- 中央主舞台 -->
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
      </div>

      <!-- 右侧滑出式远程代码/配置编辑器抽屉 -->
      <FileEditorDrawer />
    </div>

    <!-- 全局操作反馈 Toast (居顶悬浮，避免遮挡底部核心终端与命令交互中枢) -->
    <div
      v-if="store.toastMessage"
      role="status"
      aria-live="polite"
      class="fixed top-5 left-1/2 -translate-x-1/2 px-4 py-2 rounded-full bg-cyan-950/95 border border-cyan-500/60 text-cyan-200 text-xs font-medium shadow-2xl flex items-center gap-2 z-50 transition-all pointer-events-none backdrop-blur-sm"
    >
      <CheckCircle2 class="w-4 h-4 text-emerald-400 shrink-0" />
      <span>{{ store.toastMessage }}</span>
    </div>

    <!-- 全局原生 <dialog> 模态框组 (Cmd+K 面板 & 参数化命令填参弹窗) -->
    <CommandPaletteModal />
  </div>
</template>
