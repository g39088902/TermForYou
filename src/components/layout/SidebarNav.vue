<script setup lang="ts">
import { computed } from 'vue'
import { store, extractedClusters, hasConnectedHost, showToast } from '@/stores/workbenchStore'
import type { PageId } from '@/types'
import {
  LayoutGrid,
  TerminalSquare,
  Activity,
  FolderOpen,
  Sparkles,
  Container,
  Cog,
  CalendarClock,
  Shield,
  Lock
} from 'lucide-vue-next'

const unallowedPortCount = computed(() => {
  if (!hasConnectedHost.value) return 0
  return store.processes.filter((p) => p.listenPort && p.firewallAllowed === false).length
})

const failedServiceCount = computed(() => {
  if (!hasConnectedHost.value) return 0
  return store.systemdServices.filter((s) => s.state === 'failed').length
})

const runningServiceCount = computed(() => {
  if (!hasConnectedHost.value) return 0
  return store.systemdServices.filter((s) => s.state === 'running').length
})

function handleNavClick(itemId: PageId) {
  if (itemId === 'P0_HOSTS') {
    store.activePage = 'P0_HOSTS'
    return
  }

  if (!hasConnectedHost.value) {
    showToast('未连接任何服务器：请先在「主机连接池」选择并连接一台服务器')
    return
  }

  store.activePage = itemId
}

const navItems = computed(() => [
  {
    id: 'P0_HOSTS' as PageId,
    label: '主机连接池',
    shortCode: 'P0',
    icon: LayoutGrid,
    badge: ''
  },
  {
    id: 'P1_WORKBENCH' as PageId,
    label: '终端工作台',
    shortCode: 'P1',
    icon: TerminalSquare,
    badge: ''
  },
  {
    id: 'P4_COMMANDS' as PageId,
    label: '命令提炼与库',
    shortCode: 'P4',
    icon: Sparkles,
    badge: extractedClusters.value.length > 0 ? `${extractedClusters.value.length} 提炼` : ''
  },
  {
    id: 'P3_FILES' as PageId,
    label: '文件管理',
    shortCode: 'P3',
    icon: FolderOpen,
    badge: ''
  },
  {
    id: 'P2_METRICS_PROCESS' as PageId,
    label: '性能与进程',
    shortCode: 'P2',
    icon: Activity,
    badge: `${store.processes.length}`
  },
  {
    id: 'P5_DOCKER' as PageId,
    label: 'Docker 容器',
    shortCode: 'P5',
    icon: Container,
    badge: `${store.dockerContainers.length}`
  },
  {
    id: 'P6_SYSTEMD' as PageId,
    label: '系统服务',
    shortCode: 'P6',
    icon: Cog,
    badge: `${runningServiceCount.value} 运行`,
    dangerBadge: failedServiceCount.value > 0
  },
  {
    id: 'P7_CRON' as PageId,
    label: '计划任务',
    shortCode: 'P7',
    icon: CalendarClock,
    badge: `${store.cronTasks.length}`
  },
  {
    id: 'P8_FIREWALL' as PageId,
    label: '防火墙安全',
    shortCode: 'P8',
    icon: Shield,
    badge: unallowedPortCount.value > 0 ? `${unallowedPortCount.value} 待放行` : '',
    warnBadge: unallowedPortCount.value > 0
  }
])
</script>

<template>
  <aside
    class="w-52 h-full bg-slate-950 border-r border-slate-800/90 flex flex-col select-none shrink-0 z-20"
    aria-label="全局最高层级功能视图导航"
  >
    <!-- 顶部品牌区域：与右侧 TopSessionBar (h-11) 严格对齐 -->
    <div class="h-11 px-3.5 flex items-center gap-2.5 border-b border-slate-800/90 shrink-0">
      <div class="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
        <TerminalSquare class="w-4 h-4" />
      </div>
      <div class="flex items-center min-w-0">
        <span class="font-bold text-sm tracking-tight text-slate-100">TermForYou</span>
      </div>
    </div>

    <!-- 中间：主功能模块导航 (自适应平滑滚动) -->
    <nav class="flex-1 overflow-y-auto p-2 space-y-1" aria-label="主功能模块导航">
      <div class="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        功能导航
      </div>

      <button
        v-for="item in navItems"
        :key="item.id"
        type="button"
        @click="handleNavClick(item.id)"
        :title="!hasConnectedHost && item.id !== 'P0_HOSTS' ? '未连接任何服务器，请先在主机连接池连接' : ''"
        :class="[
          'w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs font-medium transition',
          !hasConnectedHost && item.id !== 'P0_HOSTS'
            ? 'opacity-35 cursor-not-allowed text-slate-600 border border-transparent'
            : store.activePage === item.id
              ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/40 shadow-sm cursor-pointer'
              : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200 border border-transparent cursor-pointer'
        ]"
      >
        <div class="flex items-center gap-2.5 min-w-0">
          <component
            :is="item.icon"
            :class="[
              'w-4 h-4 shrink-0',
              !hasConnectedHost && item.id !== 'P0_HOSTS'
                ? 'text-slate-600'
                : store.activePage === item.id
                  ? 'text-cyan-400'
                  : 'text-slate-400'
            ]"
          />
          <span class="truncate">{{ item.label }}</span>
        </div>

        <div class="flex items-center gap-1.5 shrink-0">
          <Lock
            v-if="!hasConnectedHost && item.id !== 'P0_HOSTS'"
            class="w-3 h-3 text-slate-600"
          />

          <span
            v-else-if="item.badge"
            :class="[
              'px-1.5 py-0.5 text-[10px] rounded-full font-mono',
              item.dangerBadge
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                : item.warnBadge
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                  : 'bg-slate-800 text-slate-300'
            ]"
          >
            {{ item.badge }}
          </span>
        </div>
      </button>
    </nav>
  </aside>
</template>
