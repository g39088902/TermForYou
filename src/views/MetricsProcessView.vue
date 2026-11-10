<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  currentHost,
  navigateWithContext,
  executeTerminalCommand,
  showToast
} from '@/stores/workbenchStore'
import {
  Activity,
  Cpu,
  HardDrive,
  Search,
  ShieldAlert,
  ShieldCheck,
  FolderOpen,
  Cog,
  Container,
  Skull
} from 'lucide-vue-next'

const searchQuery = ref('')
const onlyListeningPorts = ref(false)

const filteredProcesses = computed(() => {
  return store.processes.filter((p) => {
    if (onlyListeningPorts.value && !p.listenPort) return false
    const q = searchQuery.value.trim().toLowerCase()
    if (!q) return true
    return (
      p.name.toLowerCase().includes(q) ||
      p.cmdline.toLowerCase().includes(q) ||
      String(p.pid).includes(q) ||
      String(p.listenPort ?? '').includes(q)
    )
  })
})

function sendSignal(pid: number, name: string, signal: 'SIGTERM' | 'SIGKILL') {
  executeTerminalCommand(`sudo kill -s ${signal} ${pid} # (${name})`)
  showToast(`已向进程 ${name} (PID ${pid}) 发送 ${signal} 信号`)
}
</script>

<template>
  <div class="p-5 space-y-5 overflow-y-auto h-full">
    <!-- 上半区：性能监控核心仪表盘 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <!-- 1. CPU 单核矩阵与 Load Average -->
      <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
            <Cpu class="w-4 h-4 text-cyan-400" />
            <span>CPU 多核实时负载矩阵</span>
          </div>
          <span class="font-mono text-sm font-bold text-cyan-300">{{ currentHost.cpuUsage }}%</span>
        </div>

        <div class="grid grid-cols-4 gap-2">
          <div
            v-for="(usage, idx) in currentHost.cpuCores"
            :key="idx"
            class="p-2 rounded-lg bg-slate-950 border border-slate-800/80 space-y-1"
          >
            <div class="flex items-center justify-between text-[10px] text-slate-400 font-mono">
              <span>Core #{{ idx }}</span>
              <span :class="usage > 70 ? 'text-amber-400' : 'text-emerald-400'">{{ usage }}%</span>
            </div>
            <div class="h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div
                :class="[
                  'h-full rounded-full transition-all',
                  usage > 70 ? 'bg-amber-400' : 'bg-cyan-400'
                ]"
                :style="{ width: `${usage}%` }"
              />
            </div>
          </div>
        </div>

        <div class="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-800/80 font-mono">
          <span>Load Avg (1/5/15m):</span>
          <span class="text-slate-200">{{ currentHost.loadAvg ? currentHost.loadAvg.join(' / ') : '--' }}</span>
        </div>
      </div>

      <!-- 2. 内存与 Swap 细分 -->
      <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3 flex flex-col justify-between">
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
              <Activity class="w-4 h-4 text-emerald-400" />
              <span>物理内存与 Swap 交换分区</span>
            </div>
            <span class="font-mono text-sm font-bold text-emerald-300">
              {{ currentHost.memUsedGb !== undefined && currentHost.memTotalGb !== undefined ? `${currentHost.memUsedGb} / ${currentHost.memTotalGb} GB` : '--' }}
            </span>
          </div>

          <div class="space-y-1.5">
            <div class="flex justify-between text-[11px] text-slate-400">
              <span>已用物理内存 (Used + Buffers/Cache)</span>
              <span class="font-mono text-slate-200">
                {{ currentHost.memUsedGb !== undefined && currentHost.memTotalGb ? `${Math.round((currentHost.memUsedGb / currentHost.memTotalGb) * 100)}%` : '--' }}
              </span>
            </div>
            <div class="h-2.5 rounded-full bg-slate-950 border border-slate-800 overflow-hidden flex">
              <div
                class="bg-emerald-500 h-full"
                :style="{ width: `${currentHost.memTotalGb ? (currentHost.memUsedGb! / currentHost.memTotalGb) * 80 : 0}%` }"
                title="应用独占内存"
              />
              <div
                class="bg-cyan-500/60 h-full"
                :style="{ width: `${currentHost.memTotalGb ? (currentHost.memUsedGb! / currentHost.memTotalGb) * 20 : 0}%` }"
                title="PageCache / Buffers"
              />
            </div>
          </div>

          <div class="space-y-1">
            <div class="flex justify-between text-[11px] text-slate-400">
              <span>Swap 交换分区</span>
              <span class="font-mono text-slate-300">
                {{ currentHost.swapUsedGb !== undefined && currentHost.swapTotalGb !== undefined ? `${currentHost.swapUsedGb} / ${currentHost.swapTotalGb} GB` : '--' }}
              </span>
            </div>
            <div class="h-1.5 rounded-full bg-slate-950 border border-slate-800 overflow-hidden">
              <div
                class="bg-amber-400 h-full"
                :style="{ width: `${currentHost.swapTotalGb ? (currentHost.swapUsedGb! / currentHost.swapTotalGb) * 100 : 0}%` }"
              />
            </div>
          </div>
        </div>

        <div class="text-[11px] text-slate-400 pt-2 border-t border-slate-800/80 flex items-center justify-between">
          <span>支持点击下方进程表按 RSS 内存排序</span>
          <button
            type="button"
            @click="executeTerminalCommand('free -h && vmstat 1 3')"
            class="text-cyan-400 hover:underline cursor-pointer"
          >
            在随行终端运行 free -h
          </button>
        </div>
      </div>

      <!-- 3. 磁盘挂载点与网络吞吐 -->
      <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3 flex flex-col justify-between">
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
              <HardDrive class="w-4 h-4 text-indigo-400" />
              <span>磁盘 I/O 与实时网络吞吐</span>
            </div>
            <span class="font-mono text-xs text-indigo-300">根分区 / ({{ currentHost.diskUsedPercent !== undefined ? `${currentHost.diskUsedPercent}%` : '--' }})</span>
          </div>

          <div class="grid grid-cols-2 gap-2 text-xs font-mono">
            <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
              <div class="text-[10px] text-slate-400">网卡上行 (eth0 TX)</div>
              <div class="text-emerald-400 font-bold mt-0.5">
                ↑ {{ currentHost.netUpKbps ? (currentHost.netUpKbps / 1024).toFixed(2) : '0.00' }} MB/s
              </div>
            </div>
            <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
              <div class="text-[10px] text-slate-400">网卡下行 (eth0 RX)</div>
              <div class="text-sky-400 font-bold mt-0.5">
                ↓ {{ currentHost.netDownKbps ? (currentHost.netDownKbps / 1024).toFixed(2) : '0.00' }} MB/s
              </div>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-between text-[11px] pt-2 border-t border-slate-800/80">
          <span class="text-slate-400">磁盘读写: R 14.2MB/s · W 8.6MB/s</span>
          <button
            type="button"
            @click="
              navigateWithContext({
                sourcePage: 'P2_METRICS_PROCESS',
                targetPage: 'P3_FILES',
                reason: '从性能监控跳转文件管理器分析大文件占用',
                openPath: '/var/log'
              })
            "
            class="text-cyan-400 hover:underline cursor-pointer"
          >
            分析大目录占用 →
          </button>
        </div>
      </div>
    </div>

    <!-- 下半区：交互式进程监控与端口监听反查表 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 overflow-hidden">
      <div class="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="process-table-heading" class="text-sm font-bold text-slate-100">
            交互式进程监控与端口反查表 (支持一键跳转防火墙 / 文件目录 / Systemd / 容器)
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">
            点击表格中的「端口放行状态」、「CWD 路径」或「所属服务/容器」胶囊按钮即可跨页面带上下文直达。
          </p>
        </div>

        <div class="flex items-center gap-3">
          <label class="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
            <input v-model="onlyListeningPorts" type="checkbox" class="rounded" />
            <span>仅看含监听端口进程 (ss -tulnp)</span>
          </label>

          <div class="relative">
            <Search class="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2" />
            <input
              v-model="searchQuery"
              type="search"
              placeholder="过滤 PID / 进程名 / 端口 (如 8080)..."
              class="pl-8 pr-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none w-64"
            />
          </div>
        </div>
      </div>

      <div tabindex="0" role="region" aria-labelledby="process-table-heading" class="table-wrapper">
        <table class="text-left text-xs" style="--label-2: 'CPU/内存'; --label-3: '监听端口与防火墙'; --label-4: '跨模块直达'">
          <thead class="bg-slate-950 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">PID / 进程名</th>
              <th class="py-2.5 px-3">CPU% / 内存 (RSS)</th>
              <th class="py-2.5 px-3">监听端口 & 防火墙联动</th>
              <th class="py-2.5 px-3">工作目录 (CWD) & 托管归属</th>
              <th class="py-2.5 px-3 text-right">信号管控</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/70">
            <tr
              v-for="proc in filteredProcesses"
              :key="proc.pid"
              :class="[
                'hover:bg-slate-800/50 transition',
                store.lastJumpContext?.highlightPid === proc.pid ? 'bg-cyan-500/10' : ''
              ]"
            >
              <!-- PID 与启动命令 -->
              <th class="py-2.5 px-3 font-medium text-slate-100">
                <div class="flex items-center gap-2">
                  <span class="px-1.5 py-0.5 rounded bg-slate-800 font-mono text-[11px] text-cyan-300">
                    PID {{ proc.pid }}
                  </span>
                  <span class="font-bold">{{ proc.name }}</span>
                  <span class="text-[11px] text-slate-400">({{ proc.user }})</span>
                </div>
                <div class="font-mono text-[11px] text-slate-400 mt-1 truncate max-w-md" :title="proc.cmdline">
                  {{ proc.cmdline }}
                </div>
              </th>

              <!-- CPU / MEM -->
              <td class="py-2.5 px-3 font-mono">
                <div :class="proc.cpuPercent > 15 ? 'text-amber-400 font-bold' : 'text-emerald-400'">
                  CPU {{ proc.cpuPercent }}%
                </div>
                <div class="text-slate-400 text-[11px]">
                  MEM {{ proc.memPercent }}% ({{ proc.memRssMb }} MB)
                </div>
              </td>

              <!-- 监听端口与防火墙联动胶囊 -->
              <td class="py-2.5 px-3">
                <div v-if="proc.listenPort" class="flex items-center gap-2 flex-wrap">
                  <span class="font-mono font-bold text-slate-100 bg-slate-800 px-2 py-0.5 rounded">
                    :{{ proc.listenPort }}/{{ proc.protocol }}
                  </span>

                  <button
                    v-if="!proc.firewallAllowed"
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P2_METRICS_PROCESS',
                        targetPage: 'P8_FIREWALL',
                        reason: `为进程 ${proc.name} (PID ${proc.pid}) 放行端口 ${proc.listenPort}`,
                        prefillFirewallPort: proc.listenPort,
                        prefillFirewallProtocol: proc.protocol,
                        prefillFirewallComment: `${proc.name} service port`
                      })
                    "
                    class="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-[11px] cursor-pointer"
                    title="点击跳转到防火墙页面并自动预填放行该端口"
                  >
                    <ShieldAlert class="w-3 h-3" />
                    <span>未放行 · 一键去放行 →</span>
                  </button>

                  <button
                    v-else
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P2_METRICS_PROCESS',
                        targetPage: 'P8_FIREWALL',
                        reason: `查看端口 ${proc.listenPort} 的防火墙放行策略`,
                        highlightPort: proc.listenPort
                      })
                    "
                    class="flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 text-[11px] cursor-pointer"
                  >
                    <ShieldCheck class="w-3 h-3" />
                    <span>防火墙已放行</span>
                  </button>
                </div>
                <span v-else class="text-slate-500 text-[11px]">无网络监听</span>
              </td>

              <!-- 工作目录 (CWD) 与所属服务/容器跨页面跳转胶囊 -->
              <td class="py-2.5 px-3">
                <div class="flex items-center gap-1.5 flex-wrap">
                  <button
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P2_METRICS_PROCESS',
                        targetPage: 'P3_FILES',
                        reason: `打开进程 ${proc.name} 的工作目录 ${proc.cwd}`,
                        openPath: proc.cwd
                      })
                    "
                    class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 font-mono text-[11px] cursor-pointer"
                  >
                    <FolderOpen class="w-3 h-3" />
                    <span>{{ proc.cwd }}</span>
                  </button>

                  <button
                    v-if="proc.systemdUnit"
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P2_METRICS_PROCESS',
                        targetPage: 'P6_SYSTEMD',
                        reason: `从进程 PID ${proc.pid} 跳转管理 Systemd 服务 ${proc.systemdUnit}`,
                        filterService: proc.systemdUnit
                      })
                    "
                    class="flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-300 border border-indigo-500/30 text-[11px] cursor-pointer"
                  >
                    <Cog class="w-3 h-3" />
                    <span>{{ proc.systemdUnit }}</span>
                  </button>

                  <button
                    v-if="proc.dockerContainerId"
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P2_METRICS_PROCESS',
                        targetPage: 'P5_DOCKER',
                        reason: `从进程 PID ${proc.pid} 跳转管理所属 Docker 容器`,
                        filterContainer: proc.dockerContainerId
                      })
                    "
                    class="flex items-center gap-1 px-2 py-0.5 rounded bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-500/30 text-[11px] cursor-pointer"
                  >
                    <Container class="w-3 h-3" />
                    <span>跳转容器详情</span>
                  </button>
                </div>
              </td>

              <!-- 信号发送 -->
              <td class="py-2.5 px-3 text-right">
                <div class="inline-flex items-center gap-1.5">
                  <button
                    type="button"
                    @click="sendSignal(proc.pid, proc.name, 'SIGTERM')"
                    class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] cursor-pointer"
                  >
                    优雅停止 (15)
                  </button>
                  <button
                    type="button"
                    @click="sendSignal(proc.pid, proc.name, 'SIGKILL')"
                    class="flex items-center gap-1 px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 text-[11px] cursor-pointer"
                  >
                    <Skull class="w-3 h-3" />
                    <span>强杀 (9)</span>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
