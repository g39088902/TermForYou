<script setup lang="ts">
import { store, currentHost, navigateWithContext } from '@/stores/workbenchStore'
import {
  Cpu,
  HardDrive,
  ArrowUpDown,
  ShieldCheck,
  ShieldAlert,
  FolderSync,
  Terminal,
  Sparkles,
  X
} from 'lucide-vue-next'
</script>

<template>
  <div class="bg-slate-900/90 border-b border-slate-800 px-3 py-1.5 flex items-center justify-between text-xs shrink-0">
    <!-- 左侧：实时微缩指标条 (Mini HUD)，支持一键跳转对应模块 -->
    <div class="flex items-center gap-2 flex-wrap">
      <span class="text-[11px] font-mono text-slate-400 px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800">
        {{ currentHost.user }}@{{ currentHost.ip }}:{{ currentHost.port }}
      </span>

      <!-- 点击 CPU / 内存 直接跳到 P2 性能与进程中心 -->
      <button
        type="button"
        @click="
          navigateWithContext({
            sourcePage: store.activePage,
            targetPage: 'P2_METRICS_PROCESS',
            reason: '从顶部 Mini HUD 查看 CPU 与内存实时归因'
          })
        "
        class="flex items-center gap-2 px-2.5 py-1 rounded bg-slate-950/90 hover:bg-slate-800 border border-slate-800/90 transition cursor-pointer"
        title="点击查看性能与进程监控"
      >
        <Cpu class="w-3.5 h-3.5 text-cyan-400" />
        <span class="text-slate-300">CPU</span>
        <span
          :class="[
            'font-mono font-semibold',
            currentHost.cpuUsage > 60 ? 'text-amber-400' : 'text-emerald-400'
          ]"
        >
          {{ currentHost.cpuUsage }}%
        </span>
        <span class="text-slate-600">|</span>
        <span class="text-slate-300">MEM</span>
        <span class="font-mono text-cyan-300">
          {{ currentHost.memUsedGb }}/{{ currentHost.memTotalGb }}GB
        </span>
      </button>

      <!-- 点击磁盘跳到 P3 文件管理磁盘分析 -->
      <button
        type="button"
        @click="
          navigateWithContext({
            sourcePage: store.activePage,
            targetPage: 'P3_FILES',
            reason: '从顶部 Mini HUD 檢查目录磁盘占用',
            openPath: currentHost.currentCwd
          })
        "
        class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-950/90 hover:bg-slate-800 border border-slate-800/90 transition cursor-pointer"
      >
        <HardDrive class="w-3.5 h-3.5 text-indigo-400" />
        <span class="text-slate-300">Disk</span>
        <span class="font-mono text-indigo-300">{{ currentHost.diskUsedPercent }}%</span>
      </button>

      <!-- 实时网络上下行速率 -->
      <div class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-950/90 border border-slate-800/90 font-mono text-[11px]">
        <ArrowUpDown class="w-3.5 h-3.5 text-emerald-400" />
        <span class="text-emerald-400">↑ {{ (currentHost.netUpKbps / 1024).toFixed(2) }} MB/s</span>
        <span class="text-sky-400">↓ {{ (currentHost.netDownKbps / 1024).toFixed(2) }} MB/s</span>
      </div>

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
          'flex items-center gap-1.5 px-2.5 py-1 rounded border transition cursor-pointer',
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
        class="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-950 hover:bg-slate-800 border border-slate-800 text-slate-300 font-mono text-[11px] cursor-pointer"
        title="点击在文件管理全屏页打开该路径"
      >
        <FolderSync class="w-3.5 h-3.5 text-amber-400" />
        <span>CWD: {{ currentHost.currentCwd }}</span>
      </button>
    </div>

    <!-- 右侧：跨模块跳转轨迹胶囊 + 随行终端抽屉开关 -->
    <div class="flex items-center gap-2">
      <div
        v-if="store.lastJumpContext"
        class="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-500/15 border border-cyan-500/40 text-cyan-300 text-[11px]"
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
          'flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-medium transition cursor-pointer',
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
