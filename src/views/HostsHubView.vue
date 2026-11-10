<script setup lang="ts">
import { ref } from 'vue'
import { store, showToast } from '@/stores/workbenchStore'
import {
  Server,
  Terminal,
  Plus,
  KeyRound,
  ShieldCheck,
  ShieldAlert,
  Cpu,
  HardDrive,
  FolderGit2,
  Trash2
} from 'lucide-vue-next'

const newHostName = ref('')
const newHostIp = ref('')
const newHostUser = ref('root')
const newHostPort = ref(22)

function connectHost(hostId: string) {
  if (!store.openHostIds.includes(hostId)) {
    store.openHostIds.push(hostId)
  }
  store.activeHostId = hostId
  store.activePage = 'P1_WORKBENCH'
  const host = store.hosts.find((h) => h.id === hostId)
  showToast(`已通过 SSH 免 Agent 模式连接至 ${host?.name} (${host?.ip})`)
}

function removeHost(hostId: string, hostName: string) {
  if (!confirm(`确定要从主机池中删除服务器「${hostName}」吗？\n删除后相关的会话连接与快捷标签将被一并清理。`)) {
    return
  }

  // 1. 从主机池中移除
  store.hosts = store.hosts.filter((h) => h.id !== hostId)

  // 2. 清理顶栏已打开的会话标签
  store.openHostIds = store.openHostIds.filter((id) => id !== hostId)

  // 3. 如果当前正处于该主机会话中，切换至剩余主机
  if (store.activeHostId === hostId) {
    if (store.openHostIds.length > 0) {
      store.activeHostId = store.openHostIds[0]
    } else if (store.hosts.length > 0) {
      store.activeHostId = store.hosts[0].id
      store.openHostIds.push(store.hosts[0].id)
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
  store.hosts.push({
    id,
    name: newHostName.value.trim(),
    ip: newHostIp.value.trim(),
    port: newHostPort.value,
    user: newHostUser.value,
    group: '自定义新增节点',
    os: 'Ubuntu 24.04 LTS',
    kernel: '6.8.0-generic',
    uptime: '1 天 02 小时',
    status: 'online',
    tags: ['SSH直连', '新节点'],
    cpuUsage: 12,
    cpuCores: [10, 14, 12, 11],
    loadAvg: [0.24, 0.19, 0.15],
    memUsedGb: 1.8,
    memTotalGb: 8,
    swapUsedGb: 0,
    swapTotalGb: 2,
    diskUsedPercent: 28,
    netUpKbps: 120,
    netDownKbps: 85,
    firewallEnabled: true,
    firewallBackend: 'ufw',
    currentCwd: '/root'
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
          <span>P0 主机连接池 (SSH 免 Agent 直连架构)</span>
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          双击或点击「进入工作台」即可建立 SSH + SFTP 多路复用通道，自动探测远端 Systemd、Crontab、Docker 与防火墙状态。
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
          class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer"
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
                <span
                  :class="[
                    'w-2.5 h-2.5 rounded-full',
                    host.status === 'online' ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]' : 'bg-amber-400'
                  ]"
                />
                <h2 class="text-sm font-bold text-slate-100 group-hover:text-cyan-300 transition">
                  {{ host.name }}
                </h2>
              </div>
              <div class="text-xs font-mono text-slate-400 mt-0.5">
                {{ host.user }}@{{ host.ip }}:{{ host.port }} · {{ host.os }}
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
            <span
              v-for="tag in host.tags"
              :key="tag"
              class="px-2 py-0.5 text-[10px] rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20"
            >
              {{ tag }}
            </span>
            <span
              :class="[
                'px-2 py-0.5 text-[10px] rounded-full flex items-center gap-1',
                host.firewallEnabled
                  ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-300 border border-rose-500/20'
              ]"
            >
              <ShieldCheck v-if="host.firewallEnabled" class="w-3 h-3" />
              <ShieldAlert v-else class="w-3 h-3" />
              {{ host.firewallBackend.toUpperCase() }}
            </span>
          </div>

          <!-- 实时健康快照条 -->
          <div class="grid grid-cols-3 gap-2 pt-2 border-t border-slate-800/80 text-xs">
            <div class="bg-slate-950/80 p-2 rounded-lg border border-slate-800/80">
              <div class="text-[10px] text-slate-400 flex items-center gap-1">
                <Cpu class="w-3 h-3 text-cyan-400" />
                <span>CPU 负载</span>
              </div>
              <div class="font-mono font-bold text-slate-100 mt-0.5">{{ host.cpuUsage }}%</div>
            </div>

            <div class="bg-slate-950/80 p-2 rounded-lg border border-slate-800/80">
              <div class="text-[10px] text-slate-400">内存占用</div>
              <div class="font-mono font-bold text-cyan-300 mt-0.5">
                {{ host.memUsedGb }}/{{ host.memTotalGb }}G
              </div>
            </div>

            <div class="bg-slate-950/80 p-2 rounded-lg border border-slate-800/80">
              <div class="text-[10px] text-slate-400 flex items-center gap-1">
                <HardDrive class="w-3 h-3 text-indigo-400" />
                <span>磁盘使用</span>
              </div>
              <div class="font-mono font-bold text-indigo-300 mt-0.5">{{ host.diskUsedPercent }}%</div>
            </div>
          </div>
        </div>

        <!-- 底部操作按钮 -->
        <div class="flex items-center justify-between pt-4 mt-4 border-t border-slate-800/80">
          <div class="flex items-center gap-1 text-[11px] text-slate-400 font-mono">
            <FolderGit2 class="w-3.5 h-3.5 text-amber-400" />
            <span>{{ host.currentCwd }}</span>
          </div>

          <button
            type="button"
            @click="connectHost(host.id)"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold transition cursor-pointer"
          >
            <Terminal class="w-3.5 h-3.5" />
            <span>进入综合工作台</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 底部：SSH 密钥与跳板机隧道说明 -->
    <div class="rounded-xl bg-slate-900/60 border border-slate-800 p-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
          <KeyRound class="w-5 h-5" />
        </div>
        <div>
          <h3 class="text-xs font-semibold text-slate-100">本地 SSH 密钥保险箱与 ProxyJump 跳板机支持</h3>
          <p class="text-[11px] text-slate-400 mt-0.5">
            支持 Ed25519 / RSA 私钥、系统 SSH Agent 转发以及多级 Bastion 跳板机隧道连接，所有凭证使用本地系统 Keychain 加密存储。
          </p>
        </div>
      </div>
      <span class="text-xs font-mono text-emerald-400 bg-emerald-950/50 border border-emerald-700/40 px-2.5 py-1 rounded">
        Keychain 已就绪 (3 把密钥)
      </span>
    </div>
  </div>
</template>
