<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import RealXtermTerminal from '@/components/terminal/RealXtermTerminal.vue'
import type { DockerContainerItem, DockerExecTarget } from '@/types'
import {
  store,
  navigateWithContext,
  executeTerminalCommand,
  showToast,
  removeDockerContainer,
  restartDockerContainer,
  controlDockerContainer,
  inspectHost
} from '@/stores/workbenchStore'
import {
  Container,
  Terminal,
  FolderOpen,
  ShieldAlert,
  ShieldCheck,
  RotateCw,
  ArrowLeftRight,
  Star,
  Trash2,
  HardDrive,
  Play,
  Square,
  Loader2,
  X
} from 'lucide-vue-next'

const dockerSudo = ref(false)
const execTarget = ref<DockerExecTarget | null>(null)
const pageScrollEl = ref<HTMLDivElement | null>(null)

watch(() => store.activeHostId, () => {
  execTarget.value = null
  dockerSudo.value = false
}, { flush: 'sync' })

onMounted(() => {
  if (!store.dockerContainersLoading) void inspectHost(store.activeHostId)
})

function containerAction(containerId: string) {
  return store.dockerContainerActions[`${store.activeHostId}/${containerId}`]
}

function isContainerBusy(containerId: string) {
  return !!containerAction(containerId)
}

function containerStateLabel(container: DockerContainerItem) {
  const action = containerAction(container.id)
  return action ? { start: '启动中…', stop: '停止中…', restart: '重启中…' }[action] : container.status
}

function canStop(container: DockerContainerItem) {
  return container.status === 'running' || container.status === 'restarting'
}

async function toggleContainer(container: DockerContainerItem) {
  const action = canStop(container) ? 'stop' : 'start'
  if (action === 'stop' && !window.confirm(`确认停止容器 ${container.name}？容器服务将停止运行。`)) return
  if (execTarget.value?.containerId === container.id) execTarget.value = null
  await controlDockerContainer(container.id, action, dockerSudo.value)
}

async function restartContainer(container: DockerContainerItem) {
  if (!window.confirm(`确认重启容器 ${container.name}？容器服务会短暂中断。`)) return
  await restartDockerContainer(container.id, dockerSudo.value)
}

async function openExec(container: DockerContainerItem) {
  execTarget.value = {
    hostAlias: store.activeHostId,
    containerId: container.id,
    name: container.name,
    sudo: dockerSudo.value
  }
  await nextTick()
  pageScrollEl.value?.scrollTo({ top: 0, behavior: 'instant' })
}

async function confirmRemove(name: string, running: boolean) {
  const msg = running
    ? `容器 ${name} 正在运行，确认强制删除？`
    : `确认删除容器 ${name}？`
  if (!window.confirm(msg)) return
  const withVols = window.confirm('是否同时删除该容器关联的匿名数据卷？(宿主机 bind 挂载目录不会被删除)')
  await removeDockerContainer(name, running, withVols)
}

const dockerRunInput = ref(
  'docker run -d --name mysql-prod --restart always -p 3306:3306 -v /data/mysql:/var/lib/mysql -e MYSQL_ROOT_PASSWORD=secret mysql:8.4'
)

// 实时解析 docker run 为可视化结构与 Compose 预览
const parsedDockerRun = computed(() => {
  const raw = dockerRunInput.value.trim()
  const nameMatch = raw.match(/--name\s+([^\s]+)/)
  const portMatch = raw.match(/-p\s+([^\s]+)/)
  const volMatch = raw.match(/-v\s+([^\s]+)/)
  const restartMatch = raw.match(/--restart\s+([^\s]+)/)
  const tokens = raw.split(/\s+/)
  const image = tokens[tokens.length - 1] || 'nginx:alpine'

  return {
    name: nameMatch?.[1] ?? 'custom-container',
    port: portMatch?.[1] ?? '8080:80',
    volume: volMatch?.[1] ?? '/opt/data:/data',
    restart: restartMatch?.[1] ?? 'unless-stopped',
    image
  }
})

function saveDockerRunAsSnippet() {
  store.savedSnippets.unshift({
    id: `snip-dk-${Date.now()}`,
    title: `创建容器 ${parsedDockerRun.value.name}`,
    category: 'Docker 运维',
    commandTemplate: dockerRunInput.value,
    description: '由 Docker 可视化向导一键转存的容器部署命令',
    variables: [],
    scope: 'global',
    usageCount: 1,
    source: 'gui-saved'
  })
  showToast('已将该 docker run 部署命令加入常用命令库！')
}
</script>

<template>
  <div ref="pageScrollEl" class="p-5 space-y-5 overflow-y-auto h-full">
    <section v-if="execTarget" class="rounded-xl border border-slate-800 overflow-hidden" aria-label="容器 Exec 终端">
      <div class="px-4 py-2 bg-slate-900 flex items-center justify-between text-xs text-slate-100">
        <span>容器终端 · {{ execTarget.name }} · {{ execTarget.hostAlias }} · /bin/sh</span>
        <button type="button" @click="execTarget = null" aria-label="关闭容器终端" class="p-1 rounded hover:bg-slate-800 cursor-pointer"><X class="w-4 h-4" /></button>
      </div>
      <div class="h-[420px] flex min-h-0">
        <RealXtermTerminal
          :key="`${execTarget.hostAlias}/${execTarget.containerId}/${execTarget.sudo}`"
          :host-alias="execTarget.hostAlias"
          :docker-container="execTarget.containerId"
          :sudo="execTarget.sudo"
          class="flex-1 min-h-0 min-w-0"
        />
      </div>
    </section>
    <!-- 顶部：容器全生命周期管理列表 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 overflow-hidden">
      <div class="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 id="docker-table-heading" class="text-sm font-bold text-slate-100 flex items-center gap-2">
            <Container class="w-4 h-4 text-sky-400" />
            <span>Docker 容器与编排</span>
          </h1>
          <p class="text-xs text-slate-400 mt-0.5">
            容器实例运行状态、资源占用与端口映射管理。
          </p>
        </div>
        <div class="flex items-center gap-3 text-xs text-slate-300">
          <label class="flex items-center gap-1.5 cursor-pointer">
            <input v-model="dockerSudo" type="checkbox" />
            使用 sudo 启停 / 重启 / Exec
          </label>
          <button type="button" :disabled="store.dockerContainersLoading" @click="inspectHost(store.activeHostId)" class="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-50 cursor-pointer">刷新</button>
        </div>
      </div>

      <p v-if="store.dockerContainersLoading" role="status" class="p-4 text-xs text-slate-400">正在读取当前服务器的容器列表…</p>
      <div v-else-if="store.dockerContainersError" role="alert" class="m-4 p-3 rounded bg-rose-500/15 text-xs text-rose-300">
        {{ store.dockerContainersError }}
        <button type="button" @click="inspectHost(store.activeHostId)" class="ml-3 underline cursor-pointer">重试</button>
      </div>
      <p v-else-if="store.dockerContainers.length === 0" role="status" class="p-4 text-xs text-slate-400">当前服务器未返回容器。</p>
      <div tabindex="0" role="region" aria-labelledby="docker-table-heading" class="table-wrapper">
        <table class="text-left text-xs" style="--label-2: '资源占用'; --label-3: '端口映射与防火墙'; --label-4: '存储卷挂载'">
          <thead class="bg-slate-950 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">容器名 / 镜像</th>
              <th class="py-2.5 px-3">状态 / CPU & 内存</th>
              <th class="py-2.5 px-3">端口映射 (点击联动防火墙)</th>
              <th class="py-2.5 px-3">宿主机数据卷挂载 (点击直达文件管理)</th>
              <th class="py-2.5 px-3 text-right">容器管控</th>
            </tr>
          </thead>
          <tbody class="[&>tr:last-child>*]:border-b-0">
            <tr
              v-for="c in store.dockerContainers"
              :key="c.id"
              :class="[
                'hover:bg-slate-800/50 transition',
                store.lastJumpContext?.filterContainer === c.id ? 'bg-sky-500/10' : ''
              ]"
            >
              <th class="py-3 px-3 font-medium text-slate-100 align-top text-left border-b border-slate-800">
                <div class="flex items-center gap-2">
                  <span :class="['w-2 h-2 rounded-full', c.status === 'running' ? 'bg-emerald-400' : 'bg-amber-400']" />
                  <span class="font-bold">{{ c.name }}</span>
                  <span
                    v-if="c.composeProject"
                    class="px-1.5 py-0.5 text-[10px] rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/30"
                  >
                    stack: {{ c.composeProject }}
                  </span>
                </div>
                <div class="font-mono text-[11px] text-slate-400 mt-0.5">{{ c.image }}</div>
              </th>

              <td class="py-3 px-3 font-mono align-top border-b border-slate-800">
                <div class="text-slate-300">{{ containerStateLabel(c) }}</div>
                <div class="text-emerald-400">CPU {{ c.cpuPercent }}%</div>
                <div class="text-slate-400 text-[11px]">MEM {{ c.memMb }} MB</div>
                <div v-if="c.diskUsage" class="flex items-center gap-1 text-sky-300 text-[11px]" title="容器可写层占用 (virtual 含镜像层)">
                  <HardDrive class="w-3 h-3" /><span>磁盘 {{ c.diskUsage }}</span>
                </div>
              </td>

              <!-- 端口映射与防火墙状态联动 -->
              <td class="py-3 px-3 align-top border-b border-slate-800">
                <div class="flex flex-wrap gap-1.5">
                  <button
                    v-for="p in c.ports"
                    :key="`${p.hostPort}-${p.containerPort}-${p.protocol}`"
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P5_DOCKER',
                        targetPage: 'P8_FIREWALL',
                        reason: p.firewallAllowed
                          ? `查看容器 ${c.name} 端口 ${p.hostPort} 的防火墙规则`
                          : `为容器 ${c.name} 放行宿主机映射端口 ${p.hostPort}`,
                        prefillFirewallPort: p.firewallAllowed ? undefined : p.hostPort,
                        prefillFirewallProtocol: p.protocol,
                        prefillFirewallComment: `Docker ${c.name}`,
                        highlightPort: p.hostPort
                      })
                    "
                    :class="[
                      'flex items-center gap-1 px-2 py-0.5 rounded font-mono text-[11px] border cursor-pointer',
                      p.firewallAllowed
                        ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/20'
                        : 'bg-amber-500/20 text-amber-300 border-amber-500/40 hover:bg-amber-500/30'
                    ]"
                  >
                    <ShieldCheck v-if="p.firewallAllowed" class="w-3 h-3" />
                    <ShieldAlert v-else class="w-3 h-3" />
                    <span>{{ p.hostPort }}→{{ p.containerPort }}</span>
                    <span v-if="!p.firewallAllowed" class="text-[10px] underline ml-0.5">去放行</span>
                  </button>
                </div>
              </td>

              <!-- 存储卷宿主机目录直达 -->
              <td class="py-3 px-3 align-top border-b border-slate-800">
                <div class="flex flex-col items-start gap-1 min-w-[260px]">
                  <button
                    v-for="v in c.volumes"
                    :key="v.hostPath + v.containerPath"
                    :title="`${v.hostPath} → ${v.containerPath}`"
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P5_DOCKER',
                        targetPage: 'P3_FILES',
                        reason: `在文件管理器打开容器 ${c.name} 挂载路径 ${v.hostPath}`,
                        openPath: v.hostPath
                      })
                    "
                    class="flex items-center gap-1.5 max-w-full px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 font-mono text-[11px] cursor-pointer"
                  >
                    <FolderOpen class="w-3 h-3 shrink-0" />
                    <span class="truncate max-w-[200px]">{{ v.hostPath }}</span>
                    <span class="text-slate-400 shrink-0 whitespace-nowrap">→ {{ v.containerPath }}</span>
                  </button>
                </div>
              </td>

              <!-- 容器动作：启停 / Exec / 重启 / 删除 -->
              <td class="py-3 px-3 text-right align-top whitespace-nowrap border-b border-slate-800">
                <div class="inline-flex items-center gap-1.5 whitespace-nowrap">
                  <button
                    type="button"
                    @click="toggleContainer(c)"
                    :disabled="isContainerBusy(c.id) || store.dockerContainersLoading || !['running', 'restarting', 'exited', 'created'].includes(c.status)"
                    :aria-label="`${canStop(c) ? '停止' : '启动'}容器 ${c.name}`"
                    :class="[
                      'flex items-center gap-1 px-2.5 py-1 rounded border text-[11px] font-medium disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer',
                      canStop(c) ? 'bg-amber-500/15 text-amber-300 border-amber-500/30 hover:bg-amber-500/25' : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/25'
                    ]"
                  >
                    <Loader2 v-if="isContainerBusy(c.id)" class="w-3 h-3 animate-spin" />
                    <Square v-else-if="canStop(c)" class="w-3 h-3" />
                    <Play v-else class="w-3 h-3" />
                    <span>{{ containerAction(c.id) === 'start' ? '启动中…' : containerAction(c.id) === 'stop' ? '停止中…' : canStop(c) ? '停止' : '启动' }}</span>
                  </button>
                  <button
                    type="button"
                    @click="openExec(c)"
                    :disabled="c.status !== 'running' || isContainerBusy(c.id) || store.dockerContainersLoading"
                    :aria-label="`进入容器 ${c.name} 终端`"
                    class="flex items-center gap-1 whitespace-nowrap shrink-0 px-2.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-[11px] font-medium cursor-pointer"
                  >
                    <Terminal class="w-3 h-3" />
                    <span>Exec 终端</span>
                  </button>
                  <button
                    type="button"
                    @click="restartContainer(c)"
                    :disabled="isContainerBusy(c.id) || store.dockerContainersLoading"
                    :aria-label="`重启容器 ${c.name}`"
                    class="p-1.5 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300 cursor-pointer"
                    title="重启容器"
                  >
                    <RotateCw :class="['w-3.5 h-3.5', containerAction(c.id) === 'restart' ? 'animate-spin' : '']" />
                  </button>
                  <button
                    type="button"
                    @click="confirmRemove(c.name, c.status === 'running')"
                    :disabled="isContainerBusy(c.id) || store.dockerContainersLoading"
                    class="p-1.5 rounded bg-rose-500/15 hover:bg-rose-500/30 text-rose-300 cursor-pointer"
                    title="删除容器"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 下半区：一行 docker run 与可视化表单 / Compose YAML 双向互转器 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
          <ArrowLeftRight class="w-4 h-4 text-cyan-400" />
          <span><code>docker run</code> 命令 ↔ 可视化配置表单 & Compose 双向解析器</span>
        </div>

        <div class="flex items-center gap-2">
          <button
            type="button"
            @click="saveDockerRunAsSnippet"
            class="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 text-xs cursor-pointer"
          >
            <Star class="w-3.5 h-3.5" />
            <span>存为常用命令</span>
          </button>
          <button
            type="button"
            @click="executeTerminalCommand(dockerRunInput)"
            class="px-3 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold cursor-pointer"
          >
            立即部署执行
          </button>
        </div>
      </div>

      <input
        v-model="dockerRunInput"
        type="text"
        aria-label="docker run 命令输入"
        class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono text-xs text-cyan-300 focus:border-cyan-400 focus:outline-none"
      />

      <div class="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
        <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div class="text-[10px] text-slate-400">解析容器名称 (--name)</div>
          <div class="font-mono font-bold text-slate-100 mt-0.5">{{ parsedDockerRun.name }}</div>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div class="text-[10px] text-slate-400">目标镜像 (Image)</div>
          <div class="font-mono font-bold text-sky-300 mt-0.5">{{ parsedDockerRun.image }}</div>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div class="text-[10px] text-slate-400">端口映射 (-p)</div>
          <div class="font-mono font-bold text-emerald-300 mt-0.5">{{ parsedDockerRun.port }}</div>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div class="text-[10px] text-slate-400">持久化挂载 (-v)</div>
          <div class="font-mono font-bold text-amber-300 truncate mt-0.5">{{ parsedDockerRun.volume }}</div>
        </div>
        <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div class="text-[10px] text-slate-400">重启策略 (--restart)</div>
          <div class="font-mono font-bold text-indigo-300 mt-0.5">{{ parsedDockerRun.restart }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
