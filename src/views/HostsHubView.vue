<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  store,
  showToast,
  probeHost,
  connectHost,
  deleteHostPermanently,
  addHostPermanently,
  probeAllHosts,
  toggleAutoProbe,
  updateHostPassword
} from '@/stores/workbenchStore'
import type { ServerHost } from '@/types'
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
  Flame,
  Power,
  PowerOff,
  Radio,
  Loader2,
  KeyRound,
  X
} from 'lucide-vue-next'

const newHostName = ref('')
const newHostIp = ref('')
const newHostUser = ref('root')
const newHostPort = ref(22)
const isAdding = ref(false)

// 密码不对时输入密码弹窗
const passwordModalOpen = ref(false)
const targetAuthHost = ref<ServerHost | null>(null)
const inputPassword = ref('')
const isSubmittingPassword = ref(false)

function openPasswordModal(host: ServerHost) {
  targetAuthHost.value = host
  inputPassword.value = ''
  passwordModalOpen.value = true
}

async function handleSavePassword() {
  if (!targetAuthHost.value) return
  if (!inputPassword.value) {
    showToast('请输入 SSH 密码')
    return
  }
  isSubmittingPassword.value = true
  try {
    const success = await updateHostPassword(targetAuthHost.value.id, inputPassword.value)
    if (success) {
      passwordModalOpen.value = false
      inputPassword.value = ''
      targetAuthHost.value = null
    }
  } finally {
    isSubmittingPassword.value = false
  }
}

function formatLastConnected(ts?: number) {
  if (!ts) return '从未连接'
  const diffSec = Math.floor(Date.now() / 1000) - ts
  if (diffSec < 60) return '刚刚'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`
  return `${Math.floor(diffSec / 86400)} 天前`
}

async function handleDeleteHost(hostId: string, hostName: string) {
  if (
    !confirm(
      `确定要彻底持久删除服务器「${hostName}」的配置吗？\n\n注意：此操作将直接同步修改本地 ~/.ssh/config 移除该 Host 块，并永久清理 SQLite 连接统计历史，此过程不可逆。`
    )
  ) {
    return
  }

  await deleteHostPermanently(hostId)
}

async function handleQuickAddHost() {
  if (!newHostName.value.trim() || !newHostIp.value.trim()) {
    showToast('请填写服务器别名与 IP 地址')
    return
  }

  isAdding.value = true
  const name = newHostName.value.trim()
  const ip = newHostIp.value.trim()
  const port = newHostPort.value || 22
  const user = newHostUser.value.trim() || 'root'

  try {
    await addHostPermanently({ name, ip, port, user })
    newHostName.value = ''
    newHostIp.value = ''
    newHostPort.value = 22
    newHostUser.value = 'root'
    // 自动连接新添加的主机
    connectHost(name)
  } finally {
    isAdding.value = false
  }
}

// 首次进入页面时自动探测一次所有服务器开机状态
onMounted(() => {
  if (store.hosts.length > 0) {
    const hasUnprobed = store.hosts.some((h) => !h.powerStatus || h.powerStatus === 'unknown')
    if (hasUnprobed) {
      probeAllHosts(true)
    }
  }
})
</script>

<template>
  <div class="p-6 space-y-6 overflow-y-auto h-full">
    <!-- 顶部横幅与控制中心 -->
    <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4 bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-lg">
      <div class="space-y-1">
        <h1 class="text-lg font-bold text-slate-100 flex items-center gap-2 flex-wrap">
          <Server class="w-5 h-5 text-cyan-400" />
          <span>主机连接池</span>
          <span class="text-xs px-2 py-0.5 rounded-full bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 font-normal">
            按手动连接次数降序
          </span>
          <span class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700 font-mono">
            共 {{ store.hosts.length }} 台主机
          </span>
        </h1>
        <p class="text-xs text-slate-400">
          本地 ~/.ssh/config 真实服务器配置池；持久删除将同步写回配置文件并安全备份，未连接服务器时其他功能导航将保持锁定。
        </p>
      </div>

      <!-- 探测控制与全量操作栏 -->
      <div class="flex items-center gap-3 flex-wrap">
        <!-- 自动探测开关选项 -->
        <button
          type="button"
          @click="toggleAutoProbe()"
          class="flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold transition cursor-pointer select-none"
          :class="
            store.autoProbeEnabled
              ? 'bg-emerald-950/80 border-emerald-500/70 text-emerald-200 hover:bg-emerald-950 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
              : 'bg-slate-950 border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600'
          "
          :title="store.autoProbeEnabled ? '自动探测已开启：每 30 秒静默全量探测开机状态与全页面系统指标' : '自动探测已停用：点击开启每 30 秒自动探测'"
        >
          <span
            class="w-2 h-2 rounded-full"
            :class="store.autoProbeEnabled ? 'bg-emerald-500 dark:bg-emerald-400 animate-pulse shadow-[0_0_6px_#34d399]' : 'bg-slate-600'"
          />
          <span>自动探测 (30s)</span>
          <span
            class="text-[10px] px-1.5 py-0.5 rounded font-mono font-bold tracking-wider inline-flex items-center justify-center leading-none"
            :class="
              store.autoProbeEnabled
                ? 'bg-emerald-500 text-white dark:bg-emerald-400 dark:text-slate-950 shadow-sm ring-1 ring-emerald-300'
                : 'bg-slate-800 text-slate-300 border border-slate-700'
            "
          >
            {{ store.autoProbeEnabled ? 'ON' : 'OFF' }}
          </span>
        </button>

        <!-- 手动全部探测按钮 -->
        <button
          type="button"
          @click="probeAllHosts(false)"
          :disabled="store.isProbingAll"
          class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 active:bg-slate-800 text-slate-100 hover:text-cyan-300 border border-slate-700 text-xs font-semibold transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          title="立即并发探测主机池中所有服务器的开机与否状态及响应延迟"
        >
          <Radio
            class="w-3.5 h-3.5 text-cyan-400"
            :class="{ 'animate-spin': store.isProbingAll }"
          />
          <span>{{ store.isProbingAll ? '正在并发探测中...' : '全部探测' }}</span>
        </button>
      </div>
    </div>

    <!-- 快速添加服务器表单 -->
    <div class="bg-slate-900/60 border border-slate-800/80 rounded-xl p-3 flex flex-wrap items-center justify-between gap-3">
      <div class="text-xs text-slate-300 flex items-center gap-1.5">
        <Plus class="w-3.5 h-3.5 text-cyan-400" />
        <span class="font-semibold">持久新增服务器至 ~/.ssh/config:</span>
      </div>

      <form @submit.prevent="handleQuickAddHost" class="flex items-center gap-2 flex-wrap">
        <input
          v-model="newHostName"
          type="text"
          placeholder="别名 (如 HK-Edge-01)"
          required
          class="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none w-36"
        />
        <input
          v-model="newHostUser"
          type="text"
          placeholder="用户名 (root)"
          class="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs font-mono text-slate-100 w-28 focus:border-cyan-400 focus:outline-none"
        />
        <input
          v-model="newHostIp"
          type="text"
          placeholder="主机 IP / 域名"
          required
          class="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs font-mono text-slate-100 focus:border-cyan-400 focus:outline-none w-36"
        />
        <input
          v-model.number="newHostPort"
          type="number"
          placeholder="端口 (22)"
          class="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs font-mono text-slate-100 w-20 focus:border-cyan-400 focus:outline-none"
        />
        <button
          type="submit"
          :disabled="isAdding"
          class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer transition disabled:opacity-50"
        >
          <Plus class="w-3.5 h-3.5" />
          <span>{{ isAdding ? '正在持久化...' : '持久添加并连接' }}</span>
        </button>
      </form>
    </div>

    <!-- 服务器卡片网格 -->
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div
        v-for="host in store.hosts"
        :key="host.id"
        @dblclick="connectHost(host.id)"
        class="group rounded-xl bg-slate-900/80 hover:bg-slate-900 border border-slate-800 hover:border-cyan-500/50 p-4 flex flex-col justify-between transition shadow-lg relative"
      >
        <div class="space-y-3">
          <!-- 头部：开机状态指示灯、名称与管理按钮 -->
          <div class="flex items-start justify-between">
            <div class="space-y-1">
              <div class="flex items-center gap-2">
                <!-- 开机/在线状态指示灯 (若密码不对则亮起琥珀黄告警灯) -->
                <span
                  :class="[
                    'w-2.5 h-2.5 rounded-full transition-all shrink-0',
                    host.authFailed
                      ? 'bg-amber-400 shadow-[0_0_8px_#f59e0b]'
                      : host.powerStatus === 'online'
                      ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]'
                      : host.powerStatus === 'checking'
                      ? 'bg-cyan-400 animate-pulse'
                      : host.powerStatus === 'offline'
                      ? 'bg-rose-500 shadow-[0_0_6px_#f43f5e]'
                      : 'bg-slate-500'
                  ]"
                  :title="
                    host.authFailed
                      ? `已开机 · 但因密码不对或身份认证被拒绝未接通 (${host.authMessage || 'Permission denied'})`
                      : host.powerStatus === 'online'
                      ? `主机已开机 · 连通正常 (延迟 ${host.pingMs ?? '--'}ms)`
                      : host.powerStatus === 'checking'
                      ? '正在通过网络探测服务器开机状态...'
                      : host.powerStatus === 'offline'
                      ? `已关机或网络不可达 (${host.probeMessage || '离线'})`
                      : '开机状态待检测'
                  "
                />

                <h2 class="text-sm font-bold text-slate-100 group-hover:text-cyan-300 transition truncate max-w-[180px]">
                  {{ host.name }}
                </h2>

                <!-- 密码不对未接通醒目标识 -->
                <span
                  v-if="host.authFailed"
                  class="px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1 font-semibold bg-amber-500/15 text-amber-200 border border-amber-500/40 shadow-sm"
                  :title="`主机已开机 · 但因密码不对或未完成认证未接通 (${host.authMessage || 'Permission denied'})`"
                >
                  <KeyRound class="w-3 h-3 text-amber-500 dark:text-amber-400 shrink-0" />
                  <span>密码不对 · 未接通</span>
                  <span v-if="host.pingMs !== undefined" class="font-mono text-[9px] text-amber-200/90">{{ host.pingMs }}ms</span>
                </span>

                <!-- 开机连通正常醒目标签 -->
                <span
                  v-else-if="host.powerStatus === 'online'"
                  class="px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1 font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                  :title="`主机已开机 · SSH 端口活跃${host.pingMs !== undefined ? ` · 往返延迟 ${host.pingMs}ms` : ''}${host.sshBanner ? ` · ${host.sshBanner}` : ''}`"
                >
                  <Power class="w-3 h-3 text-emerald-400" />
                  <span>已开机</span>
                  <span v-if="host.pingMs !== undefined" class="font-mono text-[9px] text-emerald-400/90">{{ host.pingMs }}ms</span>
                </span>

                <span
                  v-else-if="host.powerStatus === 'offline'"
                  class="px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1 font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/30"
                  :title="host.probeMessage || '目标主机未开机或网络不可达'"
                >
                  <PowerOff class="w-3 h-3 text-rose-400" />
                  <span>已关机/离线</span>
                </span>

                <span
                  v-else-if="host.powerStatus === 'checking'"
                  class="px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1 font-medium bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 animate-pulse"
                  title="正在探测开机状态与网络连通性..."
                >
                  <Loader2 class="w-3 h-3 animate-spin text-cyan-400" />
                  <span>检测中...</span>
                </span>

                <span
                  v-else
                  class="px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1 font-medium bg-slate-800 text-slate-400 border border-slate-700"
                  title="尚未执行开机状态检测"
                >
                  <span class="w-1.5 h-1.5 rounded-full bg-slate-500" />
                  <span>待检测</span>
                </span>
              </div>

              <!-- 连接信息行 -->
              <div class="text-xs font-mono text-slate-400">
                {{ host.user }}@{{ host.ip }}:{{ host.port }}
                <span v-if="host.os" class="text-slate-300"> · {{ host.os }}</span>
                <span v-else class="text-slate-500"> · 系统待探测</span>
              </div>
            </div>

            <!-- 右上角分组与持久删除按钮 -->
            <div class="flex items-center gap-1.5">
              <span class="px-2 py-0.5 text-[10px] rounded bg-slate-800 text-slate-300 border border-slate-700">
                {{ host.group }}
              </span>

              <!-- 持久删除配置按钮 -->
              <button
                type="button"
                @click.stop="handleDeleteHost(host.id, host.name)"
                title="持久删除此服务器配置 (从 ~/.ssh/config 与 SQLite 中彻底移除)"
                class="opacity-40 group-hover:opacity-100 hover:opacity-100 p-1.5 rounded-md text-slate-400 hover:text-rose-400 hover:bg-rose-500/15 transition cursor-pointer border border-transparent hover:border-rose-500/30"
              >
                <Trash2 class="w-3.5 h-3.5" />
                <span class="sr-only">持久删除主机 {{ host.name }}</span>
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

          <!-- 密码不对未接通时的醒目警告横幅与快捷输入密码入口 -->
          <div
            v-if="host.authFailed"
            class="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg bg-amber-950/70 border border-amber-500/40 text-amber-200 text-xs shadow-sm"
          >
            <div class="flex items-center gap-1.5 truncate">
              <KeyRound class="w-3.5 h-3.5 text-amber-500 dark:text-amber-400 shrink-0" />
              <span class="truncate font-semibold text-[11px]">{{ host.authMessage || '密码错误或身份认证被拒绝，未接通系统' }}</span>
            </div>
            <button
              type="button"
              @click.stop="openPasswordModal(host)"
              class="shrink-0 px-2 py-0.5 text-[10px] rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 font-bold transition cursor-pointer"
            >
              输入密码
            </button>
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
            class="flex items-center gap-1 text-[11px] font-mono truncate max-w-[150px]"
            :class="host.currentCwd ? 'text-slate-400' : 'text-slate-600'"
            :title="host.currentCwd ? `当前终端工作目录: ${host.currentCwd}` : '尚未建立连接会话'"
          >
            <FolderGit2 class="w-3.5 h-3.5 shrink-0" :class="host.currentCwd ? 'text-amber-400' : 'text-slate-600'" />
            <span class="truncate">{{ host.currentCwd || '--' }}</span>
          </div>

          <div class="flex items-center gap-2">
            <!-- 单机即时探测开机状态与性能指标按钮 -->
            <button
              type="button"
              @click.stop="probeHost(host.id)"
              :disabled="host.powerStatus === 'checking' || host.metricsStatus === 'updating'"
              :title="
                host.powerStatus === 'checking' || host.metricsStatus === 'updating'
                  ? '探测中...'
                  : '探测开机状态与 SSH 连通性指标'
              "
              class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-cyan-300 border border-slate-700 transition cursor-pointer disabled:opacity-50"
            >
              <RefreshCw
                class="w-3.5 h-3.5"
                :class="{ 'animate-spin text-cyan-400': host.powerStatus === 'checking' || host.metricsStatus === 'updating' }"
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

    <!-- 针对密码不对的主机快速输入密码弹窗 -->
    <div
      v-if="passwordModalOpen && targetAuthHost"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      @click.self="passwordModalOpen = false"
    >
      <div class="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <div class="flex items-center gap-2">
            <KeyRound class="w-5 h-5 text-amber-400" />
            <h3 class="text-sm font-bold text-slate-100">输入服务器 SSH 连接密码</h3>
          </div>
          <button
            @click="passwordModalOpen = false"
            class="text-slate-400 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-800 cursor-pointer"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="text-xs text-slate-300 space-y-2">
          <p>
            服务器 <span class="font-bold text-cyan-400">「{{ targetAuthHost.name }}」</span>
            ({{ targetAuthHost.user }}@{{ targetAuthHost.ip }}:{{ targetAuthHost.port }}) 已开机，但因密码不匹配或未配置免密私钥而未接通。
          </p>
          <p class="text-slate-400 text-[11px]">
            请输入该主机的登录密码，TermForYou 将立即进行认证验证并同步宿主机全量系统数据：
          </p>
        </div>

        <form @submit.prevent="handleSavePassword" class="space-y-4">
          <input
            v-model="inputPassword"
            type="password"
            autofocus
            placeholder="请输入 SSH 用户密码"
            class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-sm font-mono text-slate-100 focus:border-cyan-400 focus:outline-none"
          />

          <div class="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              @click="passwordModalOpen = false"
              class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 cursor-pointer"
            >
              取消
            </button>
            <button
              type="submit"
              :disabled="isSubmittingPassword || !inputPassword"
              class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold cursor-pointer disabled:opacity-50"
            >
              <Loader2 v-if="isSubmittingPassword" class="w-3.5 h-3.5 animate-spin" />
              <span>{{ isSubmittingPassword ? '正在验证连接...' : '验证密码并接通' }}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
