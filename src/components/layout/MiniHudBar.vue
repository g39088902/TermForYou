<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  store,
  currentHost,
  navigateWithContext,
  refreshCurrentHostMetrics
} from '@/stores/workbenchStore'
import {
  Cpu,
  HardDrive,
  ArrowUpDown,
  ShieldCheck,
  ShieldAlert,
  FolderSync,
  Terminal,
  Sparkles,
  RefreshCw,
  Activity,
  Layers,
  X
} from 'lucide-vue-next'

const isRefreshing = ref(false)

async function handleManualRefresh() {
  if (isRefreshing.value) return
  isRefreshing.value = true
  try {
    await refreshCurrentHostMetrics()
  } finally {
    setTimeout(() => {
      isRefreshing.value = false
    }, 400)
  }
}

const cpuColorClass = computed(() => {
  const usage = currentHost.value.cpuUsage
  if (usage >= 80) return 'text-rose-400 font-bold'
  if (usage >= 60) return 'text-amber-400 font-bold'
  return 'text-emerald-400 font-semibold'
})

const memPercent = computed(() => {
  const total = currentHost.value.memTotalGb || 1
  return Math.round((currentHost.value.memUsedGb / total) * 100)
})

function formatSpeed(kbPerSec: number): string {
  if (!kbPerSec || kbPerSec <= 0) return '0 KB/s'
  if (kbPerSec >= 1024) {
    return `${(kbPerSec / 1024).toFixed(2)} MB/s`
  }
  return `${Math.round(kbPerSec)} KB/s`
}
</script>

<template>
  <div class="bg-slate-900/90 border-b border-slate-800 px-3 py-1.5 flex items-center justify-between text-xs shrink-0 select-none overflow-x-auto">
    <!-- 左侧：实时微缩性能指标条 (Mini HUD)，支持一键跳转对应模块 -->
    <div class="flex items-center gap-2 flex-nowrap shrink-0">
      <!-- 主机网络标识 -->
      <span
        class="text-[11px] font-mono text-slate-400 px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 shrink-0 whitespace-nowrap"
        :title="`系统内核: ${currentHost.kernel} | 运行时间: ${currentHost.uptime}`"
      >
        {{ currentHost.user }}@{{ currentHost.ip }}:{{ currentHost.port }}
      </span>

      <!-- 操作系统版本 (完整名称展示，不省略) -->
      <span
        class="flex items-center gap-1.5 text-[11px] font-mono px-2 py-0.5 rounded bg-slate-950/90 border border-slate-800/90 text-slate-300 shrink-0 whitespace-nowrap"
        :title="`操作系统完整版本: ${currentHost.os}\n系统内核: ${currentHost.kernel}`"
      >
        <Layers class="w-3 h-3 text-cyan-400 shrink-0" />
        <span class="text-slate-400 text-[10px]">OS</span>
        <span class="text-slate-200 font-medium whitespace-nowrap">{{ currentHost.os }}</span>
      </span>

      <!-- 实时 CPU / 内存 / 负载指标块 (点击直达性能与进程中心) -->
      <button
        type="button"
        @click="
          navigateWithContext({
            sourcePage: store.activePage,
            targetPage: 'P2_METRICS_PROCESS',
            reason: '从顶部 Mini HUD 查看 CPU 与内存实时归因'
          })
        "
        class="flex items-center gap-2 px-2.5 py-1 rounded bg-slate-950/90 hover:bg-slate-800 border border-slate-800/90 transition cursor-pointer shrink-0 whitespace-nowrap"
        :title="`点击查看性能与进程详情 (Load: ${currentHost.loadAvg.join(', ')})`"
      >
        <Cpu class="w-3.5 h-3.5 text-cyan-400 shrink-0" />
        <span class="text-slate-400">CPU</span>
        <span :class="['font-mono transition-colors duration-200', cpuColorClass]">
          {{ currentHost.cpuUsage }}%
        </span>
        <span class="text-slate-600">|</span>
        <span class="text-slate-400">MEM</span>
        <span class="font-mono text-cyan-300">
          {{ currentHost.memUsedGb }}/{{ currentHost.memTotalGb }}GB
        </span>
        <span class="text-[10px] text-slate-500 font-mono">({{ memPercent }}%)</span>
      </button>

      <!-- 磁盘使用率 (点击直达文件管理中心) -->
      <button
        type="button"
        @click="
          navigateWithContext({
            sourcePage: store.activePage,
            targetPage: 'P3_FILES',
            reason: '从顶部 Mini HUD 检查目录磁盘占用',
            openPath: currentHost.currentCwd
          })
        "
        class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-950/90 hover:bg-slate-800 border border-slate-800/90 transition cursor-pointer shrink-0 whitespace-nowrap"
        :title="currentHost.diskUsedGb && currentHost.diskTotalGb ? `根分区已用 ${currentHost.diskUsedGb}GB / 共 ${currentHost.diskTotalGb}GB` : '点击进入文件管理'"
      >
        <HardDrive class="w-3.5 h-3.5 text-indigo-400 shrink-0" />
        <span class="text-slate-400">Disk</span>
        <span class="font-mono text-indigo-300">{{ currentHost.diskUsedPercent }}%</span>
      </button>

      <!-- 实时上下行网速 -->
      <div
        class="flex items-center gap-2 px-2.5 py-1 rounded bg-slate-950/90 border border-slate-800/90 font-mono text-[11px] shrink-0 whitespace-nowrap"
        title="网络实时吞吐量 (基于 /proc/net/dev 差值计算)"
      >
        <ArrowUpDown class="w-3.5 h-3.5 text-slate-500 shrink-0" />
        <span class="text-emerald-400">↑ {{ formatSpeed(currentHost.netUpKbps) }}</span>
        <span class="text-sky-400">↓ {{ formatSpeed(currentHost.netDownKbps) }}</span>
      </div>

      <!-- 采样频率与自动更新状态胶囊 (点击立即触发一次采样) -->
      <button
        type="button"
        @click="handleManualRefresh"
        class="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-950/90 hover:bg-slate-800/90 border border-slate-800/90 transition cursor-pointer text-slate-400 hover:text-slate-200 shrink-0 whitespace-nowrap"
        title="免 Agent 纳秒级采集：默认每 3 秒自动轮询更新，点击立即手动采样"
      >
        <RefreshCw
          :class="[
            'w-3 h-3 transition-transform',
            (isRefreshing || currentHost.metricsStatus === 'updating') ? 'animate-spin text-cyan-400' : 'text-slate-500'
          ]"
        />
        <span class="font-mono text-[10px] flex items-center gap-1">
          <span
            :class="[
              'w-1.5 h-1.5 rounded-full inline-block',
              currentHost.metricsStatus === 'error'
                ? 'bg-amber-400'
                : 'bg-emerald-400 ring-2 ring-emerald-400/20'
            ]"
          />
          <span>{{ currentHost.metricsStatus === 'error' ? '待连线' : '3s 轮询' }}</span>
        </span>
      </button>

      <!-- 防火墙状态徽章：点击跳到 P8 防火墙管理 -->
      <button
        type="button"
        @click="
          navigateWithContext({
            sourcePage: store.activePage,
            targetPage: 'P8_FIREWALL',
            reason: '从顶部 Mini HUD 检查防火墙与监听端口放行状态'
          })
        "
        :class="[
          'flex items-center gap-1.5 px-2.5 py-1 rounded border transition cursor-pointer shrink-0 whitespace-nowrap',
          currentHost.firewallEnabled
            ? 'bg-emerald-950/40 border-emerald-700/50 text-emerald-300 hover:bg-emerald-900/40'
            : 'bg-rose-950/50 border-rose-700/50 text-rose-300 hover:bg-rose-900/40'
        ]"
      >
        <ShieldCheck v-if="currentHost.firewallEnabled" class="w-3.5 h-3.5" />
        <ShieldAlert v-else class="w-3.5 h-3.5" />
        <span>{{ currentHost.firewallBackend.toUpperCase() }}: {{ currentHost.firewallEnabled ? '防护中' : '未开启' }}</span>
      </button>

      <!-- 当前 CWD 路径联动徽章 -->
      <button
        type="button"
        @click="
          navigateWithContext({
            sourcePage: store.activePage,
            targetPage: 'P3_FILES',
            reason: `在文件管理器打开当前终端工作目录 ${currentHost.currentCwd}`,
            openPath: currentHost.currentCwd
          })
        "
        class="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-950 hover:bg-slate-800 border border-slate-800 text-slate-300 font-mono text-[11px] cursor-pointer shrink-0 whitespace-nowrap"
        title="点击在文件管理全屏页打开该路径"
      >
        <FolderSync class="w-3.5 h-3.5 text-amber-400" />
        <span>CWD: {{ currentHost.currentCwd }}</span>
      </button>
    </div>

    <!-- 右侧：跨模块跳转轨迹胶囊 + 随行终端抽屉开关 -->
    <div class="flex items-center gap-2 shrink-0 ml-3 whitespace-nowrap">
      <div
        v-if="store.lastJumpContext"
        class="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-500/15 border border-cyan-500/40 text-cyan-300 text-[11px] shrink-0 whitespace-nowrap"
      >
        <Sparkles class="w-3 h-3" />
        <span>联动上下文：{{ store.lastJumpContext.reason }}</span>
        <button
          type="button"
          @click="store.lastJumpContext = null"
          aria-label="清除联动提示"
          class="hover:text-slate-100 cursor-pointer"
        >
          <X class="w-3 h-3" />
        </button>
      </div>

      <button
        v-if="store.activePage !== 'P1_WORKBENCH'"
        type="button"
        @click="store.bottomTerminalOpen = !store.bottomTerminalOpen"
        :class="[
          'flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-medium transition cursor-pointer shrink-0 whitespace-nowrap',
          store.bottomTerminalOpen
            ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
            : 'bg-slate-950 text-slate-300 border-slate-800 hover:bg-slate-800'
        ]"
      >
        <Terminal class="w-3.5 h-3.5 text-cyan-400" />
        <span>随行终端 ({{ store.bottomTerminalOpen ? '已展开' : 'Ctrl+`' }})</span>
      </button>
    </div>
  </div>
</template>
