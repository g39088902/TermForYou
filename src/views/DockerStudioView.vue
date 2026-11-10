<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  navigateWithContext,
  executeTerminalCommand,
  openFileInEditor,
  showToast
} from '@/stores/workbenchStore'
import {
  Container,
  Terminal,
  FolderOpen,
  ShieldAlert,
  ShieldCheck,
  FileCode2,
  RotateCw,
  ArrowLeftRight,
  Star
} from 'lucide-vue-next'

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
  <div class="p-5 space-y-5 overflow-y-auto h-full">
    <!-- 顶部：容器全生命周期管理列表 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 overflow-hidden">
      <div class="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 id="docker-table-heading" class="text-sm font-bold text-slate-100 flex items-center gap-2">
            <Container class="w-4 h-4 text-sky-400" />
            <span>P5 Docker 容器与 Compose 编排中心</span>
          </h1>
          <p class="text-xs text-slate-400 mt-0.5">
            支持一键进入容器交互式 Shell (<code>docker exec -it</code>)、点击存储卷直达文件管理器、点击映射端口联动防火墙。
          </p>
        </div>

        <button
          type="button"
          @click="openFileInEditor('/opt/stacks/gateway/docker-compose.yml')"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white cursor-pointer"
        >
          <FileCode2 class="w-3.5 h-3.5" />
          <span>编辑 Gateway Compose 栈 (YAML)</span>
        </button>
      </div>

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
          <tbody class="divide-y divide-slate-800/70">
            <tr
              v-for="c in store.dockerContainers"
              :key="c.id"
              :class="[
                'hover:bg-slate-800/50 transition',
                store.lastJumpContext?.filterContainer === c.id ? 'bg-sky-500/10' : ''
              ]"
            >
              <th class="py-3 px-3 font-medium text-slate-100">
                <div class="flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full bg-emerald-400" />
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

              <td class="py-3 px-3 font-mono">
                <div class="text-emerald-400">CPU {{ c.cpuPercent }}%</div>
                <div class="text-slate-400 text-[11px]">MEM {{ c.memMb }} MB</div>
              </td>

              <!-- 端口映射与防火墙状态联动 -->
              <td class="py-3 px-3">
                <div class="flex flex-wrap gap-1.5">
                  <button
                    v-for="p in c.ports"
                    :key="p.hostPort"
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
              <td class="py-3 px-3">
                <div class="space-y-1">
                  <button
                    v-for="v in c.volumes"
                    :key="v.hostPath"
                    type="button"
                    @click="
                      navigateWithContext({
                        sourcePage: 'P5_DOCKER',
                        targetPage: 'P3_FILES',
                        reason: `在文件管理器打开容器 ${c.name} 挂载路径 ${v.hostPath}`,
                        openPath: v.hostPath
                      })
                    "
                    class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 font-mono text-[11px] cursor-pointer"
                  >
                    <FolderOpen class="w-3 h-3 shrink-0" />
                    <span class="truncate max-w-[230px]">{{ v.hostPath }}</span>
                  </button>
                </div>
              </td>

              <!-- 容器动作：一键进入容器终端 / 重启 -->
              <td class="py-3 px-3 text-right">
                <div class="inline-flex items-center gap-1.5">
                  <button
                    type="button"
                    @click="executeTerminalCommand(`docker exec -it ${c.name} /bin/sh`, true)"
                    class="flex items-center gap-1 px-2.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-[11px] font-medium cursor-pointer"
                  >
                    <Terminal class="w-3 h-3" />
                    <span>Exec 终端</span>
                  </button>
                  <button
                    type="button"
                    @click="executeTerminalCommand(`docker restart ${c.name}`)"
                    class="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer"
                    title="重启容器"
                  >
                    <RotateCw class="w-3.5 h-3.5" />
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
