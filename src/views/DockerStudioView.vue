<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'
import RealXtermTerminal from '@/components/terminal/RealXtermTerminal.vue'
import DockerContainerDetails from '@/components/docker/DockerContainerDetails.vue'
import type { DockerContainerItem, DockerExecTarget } from '@/types'
import {
  store,
  navigateWithContext,
  removeDockerContainer,
  restartDockerContainer,
  controlDockerContainer,
  inspectHost
} from '@/stores/workbenchStore'
import {
  Container,
  Terminal,
  FolderOpen,
  RotateCw,
  Trash2,
  HardDrive,
  Play,
  Square,
  Loader2,
  ChevronDown,
  X
} from 'lucide-vue-next'

const dockerSudo = ref(false)
const execTarget = ref<DockerExecTarget | null>(null)
const pageScrollEl = ref<HTMLDivElement | null>(null)
const expandedContainers = ref<Set<string>>(new Set())

function toggleDetails(id: string) {
  if (expandedContainers.value.has(id)) expandedContainers.value.delete(id)
  else expandedContainers.value.add(id)
}

function restartPolicyLabel(container: DockerContainerItem) {
  if (!container.restartPolicy) return '未读取'
  return container.restartPolicy + (container.restartPolicy === 'on-failure' && container.restartMaxRetries ? `:${container.restartMaxRetries}` : '')
}

function openPort(container: DockerContainerItem, port: DockerContainerItem['ports'][number]) {
  if (!port.hostPort || port.protocol === 'sctp') return
  navigateWithContext({
    sourcePage: 'P5_DOCKER', targetPage: 'P8_FIREWALL',
    reason: `查看容器 ${container.name} 宿主机端口 ${port.hostPort} 的防火墙规则`,
    highlightPort: port.hostPort,
    prefillFirewallProtocol: port.protocol,
    prefillFirewallComment: `Docker ${container.name}`
  })
}

watch(() => store.activeHostId, () => {
  execTarget.value = null
  dockerSudo.value = false
  expandedContainers.value.clear()
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
            查看网络模式、重启策略与运行参数，管理容器生命周期。
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
        <table class="table-fixed text-left text-xs" style="--label-2: '状态与重启策略'; --label-3: '网络与端口'; --label-4: '存储卷挂载'">
          <colgroup><col class="w-[22%]" /><col class="w-[18%]" /><col class="w-[21%]" /><col class="w-[21%]" /><col class="w-[18%]" /></colgroup>
          <thead class="bg-slate-950 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">容器名 / 镜像</th>
              <th class="py-2.5 px-3">状态 / 重启策略</th>
              <th class="py-2.5 px-3">网络 / 端口映射</th>
              <th class="py-2.5 px-3">宿主机数据卷挂载 (点击直达文件管理)</th>
              <th class="py-2.5 px-3 text-right">容器管控</th>
            </tr>
          </thead>
          <tbody class="[&>tr:last-child>*]:border-b-0">
            <template v-for="c in store.dockerContainers" :key="c.id">
            <tr
              :class="[
                'hover:bg-slate-800/50 transition',
                store.lastJumpContext?.filterContainer === c.id ? 'bg-sky-500/10' : ''
              ]"
            >
              <th class="py-3 px-3 font-medium text-slate-100 align-top text-left border-b border-slate-800">
                <div class="flex items-center gap-2">
                  <span :class="['w-2 h-2 rounded-full', c.status === 'running' ? 'bg-emerald-400' : 'bg-amber-400']" />
                  <span class="font-bold break-all">{{ c.name }}</span>
                  <span
                    v-if="c.composeProject"
                    class="px-1.5 py-0.5 text-[10px] rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/30"
                  >
                    stack: {{ c.composeProject }}
                  </span>
                </div>
                <div class="font-mono text-[11px] text-slate-400 mt-0.5 break-all">{{ c.image }}</div>
                <button type="button" :aria-label="`${expandedContainers.has(c.id) ? '收起' : '查看'}容器 ${c.name} 参数`" :aria-expanded="expandedContainers.has(c.id)" :aria-controls="`docker-details-${c.id}`"
                  @click="toggleDetails(c.id)" class="inline-flex items-center gap-1 mt-2 text-sky-300 hover:underline cursor-pointer">
                  <ChevronDown :class="['w-3 h-3 transition-transform', expandedContainers.has(c.id) ? 'rotate-180' : '']" />
                  {{ expandedContainers.has(c.id) ? '收起参数' : '查看参数' }}
                </button>
              </th>

              <td class="py-3 px-3 font-mono align-top border-b border-slate-800">
                <div class="text-slate-300">{{ containerStateLabel(c) }}</div>
                <div class="text-slate-300 mt-1 break-all">重启 {{ restartPolicyLabel(c) }}</div>
                <span v-if="c.healthStatus" :class="['inline-block rounded px-1.5 py-0.5 mt-1', c.healthStatus === 'healthy' ? 'bg-emerald-500/15 text-emerald-300' : c.healthStatus === 'unhealthy' ? 'bg-rose-500/15 text-rose-300' : 'bg-amber-500/15 text-amber-200']">{{ c.healthStatus }}</span>
                <div v-else class="text-slate-400 text-[11px] mt-1">{{ c.detailsAvailable ? '未配置健康检查' : '详情未读取' }}</div>
                <div v-if="c.diskUsage" class="flex items-start gap-1 mt-1 text-sky-300 text-[11px]" title="容器可写层占用 (virtual 含镜像层)">
                  <HardDrive class="w-3 h-3 shrink-0 mt-0.5" /><span class="break-words">磁盘 {{ c.diskUsage }}</span>
                </div>
              </td>

              <!-- 端口映射 -->
              <td class="py-3 px-3 align-top border-b border-slate-800">
                <span :class="['inline-block mb-2 px-1.5 py-0.5 rounded font-mono', c.networkMode === 'host' ? 'bg-sky-500/15 text-sky-300' : 'bg-slate-800 text-slate-300']">{{ c.networkMode || '网络未读取' }}</span>
                <p v-if="c.networkMode === 'host'" class="text-slate-400 text-[11px]">共享宿主机网络</p>
                <p v-else-if="!c.ports.length" class="text-slate-400 text-[11px]">{{ c.detailsAvailable ? '无端口发布' : '无端口信息' }}</p>
                <div class="flex flex-wrap gap-1.5">
                  <template v-for="p in c.networkMode === 'host' ? [] : c.ports" :key="`${p.hostIp}-${p.hostPort}-${p.containerPort}-${p.protocol}`">
                  <button
                    v-if="p.hostPort && p.protocol !== 'sctp'"
                    type="button"
                    @click="openPort(c, p)"
                    :title="`${p.hostIp || '宿主机'}:${p.hostPort} → ${p.containerPort}/${p.protocol}；点击查看防火墙规则`"
                    class="max-w-full break-all text-left px-2 py-0.5 rounded font-mono text-[11px] border bg-sky-500/15 text-sky-300 border-sky-500/30 hover:bg-sky-500/25 cursor-pointer"
                  >
                    {{ p.hostIp?.includes(':') ? `[${p.hostIp}]` : p.hostIp || '*' }}:{{ p.hostPort }}→{{ p.containerPort }}/{{ p.protocol }}
                  </button>
                  <span v-else class="px-2 py-0.5 rounded bg-slate-800 font-mono text-[11px] text-slate-300">{{ p.hostPort ? `${p.hostPort}→` : '' }}{{ p.containerPort }}/{{ p.protocol }}{{ p.hostPort ? '' : ' · 未发布' }}</span>
                  </template>
                </div>
              </td>

              <!-- 存储卷宿主机目录直达 -->
              <td class="py-3 px-3 align-top border-b border-slate-800">
                <p v-if="!c.volumes.length" class="text-slate-400 text-[11px]">{{ c.detailsAvailable ? '无挂载' : '挂载未读取' }}</p>
                <div class="flex flex-col items-start gap-1">
                  <button
                    v-for="v in c.volumes"
                    :key="v.hostPath + v.containerPath"
                    :title="`${v.type} · ${v.hostPath} → ${v.containerPath} · ${v.readOnly ? '只读' : '读写'}`"
                    :disabled="!v.hostPath"
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P5_DOCKER',
                        targetPage: 'P3_FILES',
                        reason: `在文件管理器打开容器 ${c.name} 挂载路径 ${v.hostPath}`,
                        openPath: v.hostPath
                      })
                    "
                    class="flex items-center gap-1.5 w-full min-w-0 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 font-mono text-[11px] cursor-pointer"
                  >
                    <FolderOpen class="w-3 h-3 shrink-0" />
                    <span class="truncate min-w-0 flex-1">{{ v.hostPath || v.type }}</span>
                    <span class="text-slate-400 truncate max-w-[45%]">→ {{ v.containerPath }}</span>
                    <span class="shrink-0">{{ v.readOnly ? 'RO' : 'RW' }}</span>
                  </button>
                </div>
              </td>

              <!-- 容器动作：启停 / Exec / 重启 / 删除 -->
              <td class="py-3 px-3 text-right align-top border-b border-slate-800">
                <div class="flex flex-wrap justify-end items-center gap-1.5">
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
            <tr v-if="expandedContainers.has(c.id)" :id="`docker-details-${c.id}`" class="container-detail-row">
              <td colspan="5" class="p-3 border-b border-slate-800">
                <DockerContainerDetails :container="c" />
              </td>
            </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
