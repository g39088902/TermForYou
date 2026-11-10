<script setup lang="ts">
import { ref } from 'vue'
import { store, showToast, probeHost, connectHost } from '@/stores/workbenchStore'
import {
  Server,
  Terminal,
  Plus,
  ShieldCheck,
  ShieldAlert,
  Cpu,
  HardDrive,
  FolderGit2,
  Trash2,
  RefreshCw,
  Flame
} from 'lucide-vue-next'

const newHostName = ref('')
const newHostIp = ref('')
const newHostUser = ref('root')
const newHostPort = ref(22)

function formatLastConnected(ts?: number) {
  if (!ts) return '从未连接'
  const diffSec = Math.floor(Date.now() / 1000) - ts
  if (diffSec < 60) return '刚刚'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`
  return `${Math.floor(diffSec / 86400)} 天前`
}

function removeHost(hostId: string, hostName: string) {
  if (!confirm(`确定要从主机池中删除服务器「${hostName}」吗？\n删除后相关的会话连接与快捷标签将被一并清理。`)) {
    return
  }

  // 1. 从主机池中移除
  store.hosts = store.hosts.filter((h) => h.id !== hostId)

  // 2. 清理顶栏已打开的会话标签
  store.openHostIds = store.openHostIds.filter((id) => id !== hostId)

  // 3. 如果当前正处于该主机会话中，切换至剩余主机或回到主机池
  if (store.activeHostId === hostId) {
    if (store.openHostIds.length > 0) {
      store.activeHostId = store.openHostIds[0]
    } else {
      store.activeHostId = ''
      store.activePage = 'P0_HOSTS'
    }
  }

  showToast(`已从主机池中移除「${hostName}」`)
}

function quickAddHost() {
  if (!newHostName.value.trim() || !newHostIp.value.trim()) return
  const id = `host-${Date.now()}`
  // 保持纯净的真实状态，未探测的硬件、系统与服务指标不使用任何假数据填充
  store.hosts.push({
    id,
    name: newHostName.value.trim(),
    ip: newHostIp.value.trim(),
    port: newHostPort.value || 22,
    user: newHostUser.value.trim() || 'root',
    group: '自定义新增节点',
    status: 'unconnected',
    tags: ['自定义节点'],
    metricsStatus: 'idle',
    connectionCount: 0
  })
  newHostName.value = ''
  newHostIp.value = ''
  connectHost(id)
}
</script>

<template>
  <div class="p-6 space-y-6 overflow-y-auto h-full">
    <!-- 顶部横幅与快速连接栏 -->
    <div class="flex flex-wrap items-center justify-between gap-4 bg-slate-900/90 border border-slate-800 rounded-xl p-4">
      <div>
        <h1 class="text-lg font-bold text-slate-100 flex items-center gap-2">
          <Server class="w-5 h-5 text-cyan-400" />
          <span>主机连接池</span>
          <span class="text-xs px-2 py-0.5 rounded-full bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 font-normal">
            按手动连接次数降序
          </span>
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          管理与连接远程服务器。主机列表依据手动连接频次降序排序并由后端 SQLite 持久化存储；未连接时其他功能导航将保持锁定。
        </p>
      </div>

      <!-- 快速添加服务器表单 -->
      <form @submit.prevent="quickAddHost" class="flex items-center gap-2 flex-wrap">
        <input
          v-model="newHostName"
          type="text"
          placeholder="别名 (如 HK-Edge-01)"
          class="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none w-36"
        />
        <input
          v-model="newHostIp"
          type="text"
          placeholder="主机 IP / 域名"
          class="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs font-mono text-slate-100 focus:border-cyan-400 focus:outline-none w-36"
        />
        <input
          v-model.number="newHostPort"
          type="number"
          placeholder="端口"
          class="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs font-mono text-slate-100 w-20"
        />
        <button
          type="submit"
          class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer transition"
        >
          <Plus class="w-3.5 h-3.5" />
          <span>快速添加并连接</span>
        </button>
      </form>
    </div>

    <!-- 服务器卡片网格 -->
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div
        v-for="host in store.hosts"
        :key="host.id"
        @dblclick="connectHost(host.id)"
        class="group rounded-xl bg-slate-900/80 hover:bg-slate-900 border border-slate-800 hover:border-cyan-500/50 p-4 flex flex-col justify-between transition shadow-lg"
      >
        <div class="space-y-3">
          <!-- 头部：状态与名称 -->
          <div class="flex items-start justify-between">
            <div>
              <div class="flex items-center gap-2">
                <!-- 真实探测状态灯：仅当真正连通并同步过指标时才点亮绿灯，否则如实呈现未连接/探测中/离线状态 -->
                <span
                  :class="[
                    'w-2.5 h-2.5 rounded-full transition-all',
                    host.status === 'online' && host.lastMetricsUpdate
                      ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]'
                      : host.metricsStatus === 'updating'
                      ? 'bg-cyan-400 animate-pulse'
                      : host.status === 'offline' || host.metricsStatus === 'error'
                      ? 'bg-rose-500'
                      : 'bg-slate-500'
                  ]"
                  :title="
                    host.status === 'online' && host.lastMetricsUpdate
                      ? 'SSH 连通 · 指标已实时同步'
                      : host.metricsStatus === 'updating'
                      ? '正在通过 SSH 探测连通性与性能数据...'
                      : host.status === 'offline' || host.metricsStatus === 'error'
                      ? '探测失败或主机离线'
                      : '尚未连接 · 待探测'
                  "
                />
                <h2 class="text-sm font-bold text-slate-100 group-hover:text-cyan-300 transition">
                  {{ host.name }}
                </h2>
              </div>
              <div class="text-xs font-mono text-slate-400 mt-0.5">
                {{ host.user }}@{{ host.ip }}:{{ host.port }}
                <span v-if="host.os" class="text-slate-300"> · {{ host.os }}</span>
                <span v-else class="text-slate-500"> · 系统待探测</span>
              </div>
            </div>

            <div class="flex items-center gap-1.5">
              <span class="px-2 py-0.5 text-[10px] rounded bg-slate-800 text-slate-300 border border-slate-700">
                {{ host.group }}
              </span>
              <button
                type="button"
                @click.stop="removeHost(host.id, host.name)"
                title="从主机连接池移除此服务器"
                class="opacity-40 group-hover:opacity-100 hover:opacity-100 p-1 rounded-md text-slate-400 hover:text-rose-400 hover:bg-rose-500/15 transition cursor-pointer"
              >
                <Trash2 class="w-3.5 h-3.5" />
                <span class="sr-only">删除主机 {{ host.name }}</span>
              </button>
            </div>
          </div>

          <!-- 标签组 -->
          <div class="flex items-center gap-1.5 flex-wrap">
            <!-- 用户手动连接频次徽章 (基于 SQLite 持久化) -->
            <span
              :class="[
                'px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1 font-mono',
                (host.connectionCount ?? 0) > 0
                  ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                  : 'bg-slate-800/80 text-slate-500 border border-slate-700/50'
              ]"
              :title="host.lastConnectedAt ? `最近连接时间: ${formatLastConnected(host.lastConnectedAt)}` : '尚未连接过该服务器'"
            >
              <Flame v-if="(host.connectionCount ?? 0) > 0" class="w-3 h-3 text-amber-400" />
              <span>{{ (host.connectionCount ?? 0) > 0 ? `连接 ${host.connectionCount} 次` : '从未连接' }}</span>
              <span v-if="host.lastConnectedAt" class="text-slate-400 text-[9px]">({{ formatLastConnected(host.lastConnectedAt) }})</span>
            </span>

            <span
              v-for="tag in host.tags"
              :key="tag"
              class="px-2 py-0.5 text-[10px] rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20"
            >
              {{ tag }}
            </span>

            <!-- 防火墙状态：真实探测到才显示运行状态，未知时不虚构任何规则或类型 -->
            <span
              v-if="host.firewallBackend"
              :class="[
                'px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1',
                host.firewallEnabled
                  ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-300 border border-rose-500/20'
              ]"
              :title="`宿主机底层防火墙: ${host.firewallBackend.toUpperCase()} | 状态: ${host.firewallEnabled ? '运行中且防护中' : '未开启或已停止'}`"
            >
              <ShieldCheck v-if="host.firewallEnabled" class="w-3 h-3" />
              <ShieldAlert v-else class="w-3 h-3" />
              {{ host.firewallBackend.toUpperCase() }}: {{ host.firewallEnabled ? '防护中' : '未开启' }}
            </span>
            <span
              v-else
              class="px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1 bg-slate-800/80 text-slate-400 border border-slate-700/60"
              title="尚未探测该主机的防火墙组件及运行状态"
            >
              <ShieldAlert class="w-3 h-3 opacity-50" />
              防火墙: 未检测
            </span>
          </div>

          <!-- 实时健康快照条：未探测的主机显示中立占位符 '--'，不使用任何编造的假数值 -->
          <div class="grid grid-cols-3 gap-2 pt-2 border-t border-slate-800/80 text-xs">
            <div class="bg-slate-950/80 p-2 rounded-lg border border-slate-800/80">
              <div class="text-[10px] text-slate-400 flex items-center gap-1">
                <Cpu class="w-3 h-3 text-cyan-400" />
                <span>CPU 负载</span>
              </div>
              <div
                class="font-mono font-bold mt-0.5"
                :class="host.cpuUsage !== undefined ? 'text-slate-100' : 'text-slate-500'"
              >
                {{ host.cpuUsage !== undefined ? `${host.cpuUsage}%` : '--' }}
              </div>
            </div>

            <div class="bg-slate-950/80 p-2 rounded-lg border border-slate-800/80">
              <div class="text-[10px] text-slate-400">内存占用</div>
              <div
                class="font-mono font-bold mt-0.5"
                :class="host.memUsedGb !== undefined && host.memTotalGb !== undefined ? 'text-cyan-300' : 'text-slate-500'"
              >
                {{ host.memUsedGb !== undefined && host.memTotalGb !== undefined ? `${host.memUsedGb}/${host.memTotalGb}G` : '--' }}
              </div>
            </div>

            <div class="bg-slate-950/80 p-2 rounded-lg border border-slate-800/80">
              <div class="text-[10px] text-slate-400 flex items-center gap-1">
                <HardDrive class="w-3 h-3 text-indigo-400" />
                <span>磁盘使用</span>
              </div>
              <div
                class="font-mono font-bold mt-0.5"
                :class="host.diskUsedPercent !== undefined ? 'text-indigo-300' : 'text-slate-500'"
              >
                {{ host.diskUsedPercent !== undefined ? `${host.diskUsedPercent}%` : '--' }}
              </div>
            </div>
          </div>
        </div>

        <!-- 底部操作按钮 -->
        <div class="flex items-center justify-between pt-4 mt-4 border-t border-slate-800/80">
          <div
            class="flex items-center gap-1 text-[11px] font-mono"
            :class="host.currentCwd ? 'text-slate-400' : 'text-slate-600'"
            :title="host.currentCwd ? `当前终端工作目录: ${host.currentCwd}` : '尚未建立连接会话'"
          >
            <FolderGit2 class="w-3.5 h-3.5" :class="host.currentCwd ? 'text-amber-400' : 'text-slate-600'" />
            <span>{{ host.currentCwd || '--' }}</span>
          </div>

          <div class="flex items-center gap-2">
            <!-- 单机即时探测按钮 -->
            <button
              type="button"
              @click.stop="probeHost(host.id)"
              :disabled="host.metricsStatus === 'updating'"
              :title="host.metricsStatus === 'updating' ? '探测中...' : '测试 SSH 连通性并采集真实系统指标'"
              class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-cyan-300 border border-slate-700 transition cursor-pointer disabled:opacity-50"
            >
              <RefreshCw
                class="w-3.5 h-3.5"
                :class="{ 'animate-spin text-cyan-400': host.metricsStatus === 'updating' }"
              />
              <span class="sr-only">探测连通性</span>
            </button>

            <!-- 进入终端工作台 -->
            <button
              type="button"
              @click="connectHost(host.id)"
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold transition cursor-pointer shadow-sm hover:shadow-cyan-500/20"
            >
              <Terminal class="w-3.5 h-3.5" />
              <span>进入综合工作台</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
