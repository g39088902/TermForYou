<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  executeTerminalCommand,
  openFileInEditor,
  navigateWithContext,
  showToast
} from '@/stores/workbenchStore'
import type { SystemdServiceItem } from '@/types'
import {
  Cog,
  Play,
  Square,
  RotateCw,
  FileCode2,
  FolderOpen,
  Plus,
  Terminal
} from 'lucide-vue-next'

const stateFilter = ref<'ALL' | 'running' | 'failed'>('ALL')
const selectedService = ref<SystemdServiceItem>(store.systemdServices[0])

// 新建自定义 Systemd 服务可视化向导表单
const newSvcForm = ref({
  name: 'my-worker',
  description: 'Custom Background Queue Worker',
  workingDir: '/opt/worker',
  execStart: '/usr/bin/python3 main.py --workers 4',
  user: 'www-data',
  restartPolicy: 'always' as 'always' | 'on-failure' | 'no'
})

const filteredServices = computed(() => {
  if (stateFilter.value === 'ALL') return store.systemdServices
  return store.systemdServices.filter((s) => s.state === stateFilter.value)
})

const generatedUnitContent = computed(() => {
  const f = newSvcForm.value
  return `[Unit]
Description=${f.description}
After=network.target

[Service]
Type=simple
User=${f.user}
WorkingDirectory=${f.workingDir}
ExecStart=${f.execStart}
Restart=${f.restartPolicy}
RestartSec=5

[Install]
WantedBy=multi-user.target`
})

function controlService(svc: SystemdServiceItem, action: 'start' | 'stop' | 'restart') {
  executeTerminalCommand(`sudo systemctl ${action} ${svc.name}`)
  if (action === 'start' || action === 'restart') {
    svc.state = 'running'
    svc.uptime = '刚刚启动 (0m)'
  } else if (action === 'stop') {
    svc.state = 'stopped'
  }
}

function createNewSystemdService() {
  const unitName = newSvcForm.value.name.endsWith('.service')
    ? newSvcForm.value.name
    : `${newSvcForm.value.name}.service`
  const unitPath = `/etc/systemd/system/${unitName}`

  const newItem: SystemdServiceItem = {
    name: unitName,
    description: newSvcForm.value.description,
    state: 'running',
    enabled: true,
    pid: Math.floor(Math.random() * 6000) + 2000,
    memoryMb: 64,
    uptime: '刚刚启动',
    unitFilePath: unitPath,
    workingDir: newSvcForm.value.workingDir,
    execStart: newSvcForm.value.execStart,
    restartPolicy: newSvcForm.value.restartPolicy,
    recentLogs: [`Nov 10 11:15:00 systemd[1]: Started ${newSvcForm.value.description}.`]
  }

  store.systemdServices.unshift(newItem)
  selectedService.value = newItem
  executeTerminalCommand(
    `sudo tee ${unitPath} > /dev/null && sudo systemctl daemon-reload && sudo systemctl enable --now ${unitName}`
  )
  showToast(`已生成 ${unitPath} 并重载守护进程启动服务！`)
}
</script>

<template>
  <div class="p-5 h-full flex flex-col lg:flex-row gap-4 overflow-y-auto">
    <!-- 左侧：Systemd 服务列表 -->
    <div class="lg:w-5/12 bg-slate-900/90 border border-slate-800 rounded-xl flex flex-col overflow-hidden shrink-0">
      <div class="p-3.5 border-b border-slate-800 flex items-center justify-between">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
          <Cog class="w-4 h-4 text-indigo-400" />
          <span>Systemd 系统服务</span>
        </div>

        <div class="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 text-[11px]">
          <button
            type="button"
            @click="stateFilter = 'ALL'"
            :class="[
              'px-2 py-0.5 rounded cursor-pointer',
              stateFilter === 'ALL' ? 'bg-slate-800 text-slate-100' : 'text-slate-400'
            ]"
          >
            全部 ({{ store.systemdServices.length }})
          </button>
          <button
            type="button"
            @click="stateFilter = 'running'"
            :class="[
              'px-2 py-0.5 rounded cursor-pointer',
              stateFilter === 'running' ? 'bg-emerald-500/20 text-emerald-300' : 'text-slate-400'
            ]"
          >
            运行中
          </button>
          <button
            type="button"
            @click="stateFilter = 'failed'"
            :class="[
              'px-2 py-0.5 rounded cursor-pointer',
              stateFilter === 'failed' ? 'bg-rose-500/20 text-rose-300' : 'text-slate-400'
            ]"
          >
            异常退出
          </button>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto divide-y divide-slate-800/70">
        <div
          v-for="svc in filteredServices"
          :key="svc.name"
          @click="selectedService = svc"
          :class="[
            'p-3.5 cursor-pointer transition space-y-2',
            selectedService.name === svc.name || store.lastJumpContext?.filterService === svc.name
              ? 'bg-indigo-500/10 border-l-2 border-indigo-400'
              : 'hover:bg-slate-800/50'
          ]"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span
                :class="[
                  'w-2.5 h-2.5 rounded-full',
                  svc.state === 'running'
                    ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]'
                    : svc.state === 'failed'
                      ? 'bg-rose-500 shadow-[0_0_8px_#f43f5e]'
                      : 'bg-slate-500'
                ]"
              />
              <span class="font-mono text-xs font-bold text-slate-100">{{ svc.name }}</span>
            </div>

            <span
              :class="[
                'px-2 py-0.5 text-[10px] rounded font-mono',
                svc.state === 'running'
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : svc.state === 'failed'
                    ? 'bg-rose-500/20 text-rose-300 font-bold'
                    : 'bg-slate-800 text-slate-400'
              ]"
            >
              {{ svc.state.toUpperCase() }}
            </span>
          </div>

          <p class="text-[11px] text-slate-400 truncate">{{ svc.description }}</p>

          <div class="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-1">
            <span>{{ svc.pid ? `PID ${svc.pid} · ${svc.memoryMb}MB` : svc.uptime }}</span>
            <div class="flex items-center gap-1" @click.stop>
              <button
                type="button"
                @click="controlService(svc, 'restart')"
                class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 cursor-pointer"
              >
                重启
              </button>
              <button
                v-if="svc.state === 'running'"
                type="button"
                @click="controlService(svc, 'stop')"
                class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-rose-300 cursor-pointer"
              >
                停止
              </button>
              <button
                v-else
                type="button"
                @click="controlService(svc, 'start')"
                class="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white cursor-pointer"
              >
                启动
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧：服务详情 + Journalctl 实时日志 + 新建自定义服务可视化向导 -->
    <div class="flex-1 flex flex-col gap-4 min-w-0">
      <!-- 1. 选中服务详情与 Journalctl 实时日志流 -->
      <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
          <div>
            <h2 class="text-sm font-bold text-slate-100 font-mono">{{ selectedService.name }}</h2>
            <p class="text-xs text-slate-400">{{ selectedService.description }}</p>
          </div>

          <div class="flex items-center gap-2">
            <button
              type="button"
              @click="
                navigateWithContext({
                  sourcePage: 'P6_SYSTEMD',
                  targetPage: 'P3_FILES',
                  reason: `打开服务 ${selectedService.name} 的工作目录 ${selectedService.workingDir}`,
                  openPath: selectedService.workingDir
                })
              "
              class="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 text-xs font-mono cursor-pointer"
            >
              <FolderOpen class="w-3.5 h-3.5" />
              <span>{{ selectedService.workingDir }}</span>
            </button>

            <button
              type="button"
              @click="openFileInEditor(selectedService.unitFilePath, selectedService.name)"
              class="flex items-center gap-1.5 px-3 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold cursor-pointer"
            >
              <FileCode2 class="w-3.5 h-3.5" />
              <span>编辑 Unit 配置文件</span>
            </button>
          </div>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center justify-between text-xs">
            <span class="font-mono text-slate-400">
              实时日志流: <code class="text-cyan-300">journalctl -u {{ selectedService.name }} -f</code>
            </span>
            <div class="flex items-center gap-1.5">
              <button
                type="button"
                @click="controlService(selectedService, 'restart')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
              >
                <RotateCw class="w-3 h-3" />
                <span>Restart</span>
              </button>
              <button
                type="button"
                @click="controlService(selectedService, 'stop')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-rose-300 cursor-pointer"
              >
                <Square class="w-3 h-3" />
                <span>Stop</span>
              </button>
              <button
                type="button"
                @click="controlService(selectedService, 'start')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-xs text-white cursor-pointer"
              >
                <Play class="w-3 h-3" />
                <span>Start</span>
              </button>
            </div>
          </div>

          <div class="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] space-y-1 max-h-36 overflow-y-auto">
            <div
              v-for="(line, i) in selectedService.recentLogs"
              :key="i"
              :class="line.includes('ERROR') || line.includes('Failed') ? 'text-rose-400 font-semibold' : 'text-slate-300'"
            >
              {{ line }}
            </div>
          </div>
        </div>
      </div>

      <!-- 2. 可视化新建 Systemd 服务向导 (自动生成 .service 文件并预览底层指令) -->
      <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
            <Plus class="w-4 h-4 text-cyan-400" />
            <span>新建自定义 Systemd 守护进程向导 (免手写 Unit 语法)</span>
          </div>
          <span class="text-[11px] font-mono text-slate-400">自动执行 daemon-reload</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <div class="space-y-2">
            <div>
              <label class="text-slate-400 block mb-1">服务名称 (.service)</label>
              <input
                v-model="newSvcForm.name"
                type="text"
                class="w-full px-2.5 py-1.5 rounded bg-slate-950 border border-slate-700 font-mono text-slate-100"
              />
            </div>
            <div>
              <label class="text-slate-400 block mb-1">工作目录 (WorkingDirectory)</label>
              <input
                v-model="newSvcForm.workingDir"
                type="text"
                class="w-full px-2.5 py-1.5 rounded bg-slate-950 border border-slate-700 font-mono text-amber-300"
              />
            </div>
            <div>
              <label class="text-slate-400 block mb-1">启动命令 (ExecStart)</label>
              <input
                v-model="newSvcForm.execStart"
                type="text"
                class="w-full px-2.5 py-1.5 rounded bg-slate-950 border border-slate-700 font-mono text-cyan-300"
              />
            </div>
          </div>

          <div class="flex flex-col justify-between">
            <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[10px] text-slate-300 whitespace-pre-wrap leading-relaxed">{{ generatedUnitContent }}</div>

            <button
              type="button"
              @click="createNewSystemdService"
              class="mt-2 w-full py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 cursor-pointer"
            >
              <Terminal class="w-3.5 h-3.5" />
              <span>生成 Unit 文件、重载 Daemon 并立即启动</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
