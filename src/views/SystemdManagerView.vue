<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  controlSystemdService,
  inspectHost,
  navigateWithContext
} from '@/stores/workbenchStore'
import type { SystemdServiceItem, SystemdServiceAction } from '@/types'
import {
  Cog,
  Play,
  Square,
  RotateCw,
  FolderOpen,
  Loader2,
  RefreshCw,
  ShieldAlert
} from 'lucide-vue-next'

const stateFilter = ref<'ALL' | 'running' | 'failed'>('ALL')
const selectedServiceName = ref<string | null>(null)
const useSudo = ref(false)
const confirmDialogRef = ref<HTMLDialogElement | null>(null)
const pendingAction = ref<{ service: SystemdServiceItem; action: 'stop' | 'restart' } | null>(null)

const selectedService = computed<SystemdServiceItem | null>(() => {
  if (!selectedServiceName.value) return null
  return store.systemdServices.find((s) => s.name === selectedServiceName.value) ?? null
})

const filteredServices = computed(() => {
  if (stateFilter.value === 'ALL') return store.systemdServices
  return store.systemdServices.filter((s) => s.state === stateFilter.value)
})

function serviceAction(serviceName: string): SystemdServiceAction | undefined {
  if (!store.activeHostId) return undefined
  return store.systemdServiceActions[`${store.activeHostId}/${serviceName}`]
}

function handleActionClick(svc: SystemdServiceItem, action: SystemdServiceAction) {
  if (serviceAction(svc.name)) return
  if (action === 'start') {
    void controlSystemdService(svc.name, 'start', useSudo.value)
    return
  }
  pendingAction.value = { service: svc, action }
  confirmDialogRef.value?.showModal()
}

function closeConfirmDialog() {
  confirmDialogRef.value?.close()
  pendingAction.value = null
}

async function confirmServiceAction() {
  if (!pendingAction.value) return
  const { service, action } = pendingAction.value
  closeConfirmDialog()
  await controlSystemdService(service.name, action, useSudo.value)
}

function refreshServices() {
  if (!store.activeHostId) return
  void inspectHost(store.activeHostId)
}
</script>

<template>
  <div class="p-5 h-full flex flex-col lg:flex-row gap-4 overflow-y-auto">
    <!-- 左侧：Systemd 服务列表 -->
    <div class="lg:w-5/12 bg-slate-900/90 border border-slate-800 rounded-xl flex flex-col overflow-hidden shrink-0">
      <div class="p-3.5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
          <Cog class="w-4 h-4 text-indigo-400" />
          <span>Systemd 系统服务</span>
        </div>

        <div class="flex items-center gap-2">
          <label
            class="flex items-center gap-1.5 text-[11px] text-slate-300 cursor-pointer select-none px-2 py-0.5 rounded bg-slate-950 border border-slate-800"
            title="默认关闭；勾选后使用 sudo -n 执行 systemctl 启停/重启"
          >
            <input
              v-model="useSudo"
              type="checkbox"
              class="rounded border-slate-600 bg-slate-900 text-cyan-500 focus:ring-cyan-500/40"
            />
            <span>sudo</span>
          </label>

          <button
            type="button"
            @click="refreshServices"
            :disabled="store.systemdServicesLoading || !store.activeHostId"
            title="刷新服务列表"
            class="p-1 rounded bg-slate-950 border border-slate-800 text-slate-400 hover:text-slate-200 disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw :class="['w-3.5 h-3.5', store.systemdServicesLoading ? 'animate-spin' : '']" />
          </button>

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
      </div>

      <div class="flex-1 overflow-y-auto divide-y divide-slate-800/70">
        <div
          v-if="store.systemdServicesLoading && store.systemdServices.length === 0"
          class="p-6 flex items-center justify-center gap-2 text-xs text-slate-400"
        >
          <Loader2 class="w-4 h-4 animate-spin text-cyan-400" />
          <span>正在读取当前服务器的系统服务…</span>
        </div>

        <div
          v-else-if="store.systemdServicesError && store.systemdServices.length === 0"
          class="p-6 text-center space-y-2"
        >
          <p class="text-xs text-rose-300">{{ store.systemdServicesError }}</p>
          <button
            type="button"
            @click="refreshServices"
            class="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
          >
            重试
          </button>
        </div>

        <div
          v-else-if="filteredServices.length === 0"
          class="p-6 text-center text-xs text-slate-400"
        >
          {{ store.systemdServices.length === 0 ? '当前服务器未发现 Systemd 服务或不支持 systemctl' : '当前筛选条件下无匹配服务' }}
        </div>

        <div
          v-for="svc in filteredServices"
          v-else
          :key="svc.name"
          tabindex="0"
          role="button"
          @click="selectedServiceName = svc.name"
          @keydown.enter="selectedServiceName = svc.name"
          @keydown.space.prevent="selectedServiceName = svc.name"
          :class="[
            'p-3.5 cursor-pointer transition space-y-2 focus:outline-none focus:ring-1 focus:ring-indigo-400/60',
            selectedService?.name === svc.name || store.lastJumpContext?.filterService === svc.name
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
                :disabled="Boolean(serviceAction(svc.name))"
                @click="handleActionClick(svc, 'restart')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 disabled:opacity-40 cursor-pointer"
              >
                <Loader2 v-if="serviceAction(svc.name) === 'restart'" class="w-3 h-3 animate-spin" />
                <span>重启</span>
              </button>
              <button
                v-if="svc.state === 'running'"
                type="button"
                :disabled="Boolean(serviceAction(svc.name))"
                @click="handleActionClick(svc, 'stop')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-rose-300 disabled:opacity-40 cursor-pointer"
              >
                <Loader2 v-if="serviceAction(svc.name) === 'stop'" class="w-3 h-3 animate-spin" />
                <span>停止</span>
              </button>
              <button
                v-else
                type="button"
                :disabled="Boolean(serviceAction(svc.name))"
                @click="handleActionClick(svc, 'start')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-40 cursor-pointer"
              >
                <Loader2 v-if="serviceAction(svc.name) === 'start'" class="w-3 h-3 animate-spin" />
                <span>启动</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧：服务详情与操作 -->
    <div class="flex-1 flex flex-col gap-4 min-w-0">
      <div
        v-if="!selectedService"
        class="bg-slate-900/90 border border-slate-800 rounded-xl p-8 flex flex-col items-center justify-center text-center gap-2 text-slate-400 min-h-[240px]"
      >
        <Cog class="w-6 h-6 text-slate-500" />
        <p class="text-xs">请从左侧列表选择一个系统服务以查看详情与执行启停操作</p>
      </div>

      <div v-else class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 space-y-3">
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
          </div>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center justify-between text-xs">
            <span class="font-mono text-slate-400">
              Unit 路径: <code class="text-cyan-300">{{ selectedService.unitFilePath }}</code>
            </span>
            <div class="flex items-center gap-1.5">
              <button
                type="button"
                :disabled="Boolean(serviceAction(selectedService.name))"
                @click="handleActionClick(selectedService, 'restart')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 disabled:opacity-40 cursor-pointer"
              >
                <Loader2 v-if="serviceAction(selectedService.name) === 'restart'" class="w-3 h-3 animate-spin" />
                <RotateCw v-else class="w-3 h-3" />
                <span>Restart</span>
              </button>
              <button
                type="button"
                :disabled="Boolean(serviceAction(selectedService.name))"
                @click="handleActionClick(selectedService, 'stop')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-xs text-rose-300 disabled:opacity-40 cursor-pointer"
              >
                <Loader2 v-if="serviceAction(selectedService.name) === 'stop'" class="w-3 h-3 animate-spin" />
                <Square v-else class="w-3 h-3" />
                <span>Stop</span>
              </button>
              <button
                type="button"
                :disabled="Boolean(serviceAction(selectedService.name))"
                @click="handleActionClick(selectedService, 'start')"
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-xs text-white disabled:opacity-40 cursor-pointer"
              >
                <Loader2 v-if="serviceAction(selectedService.name) === 'start'" class="w-3 h-3 animate-spin" />
                <Play v-else class="w-3 h-3" />
                <span>Start</span>
              </button>
            </div>
          </div>

          <div
            v-if="selectedService.recentLogs.length > 0"
            class="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] space-y-1 max-h-48 overflow-y-auto"
          >
            <div
              v-for="(line, i) in selectedService.recentLogs"
              :key="i"
              :class="line.includes('ERROR') || line.includes('Failed') ? 'text-rose-400 font-semibold' : 'text-slate-300'"
            >
              {{ line }}
            </div>
          </div>
          <div
            v-else
            class="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-400"
          >
            当前服务暂无采集日志，可在终端执行 <code class="font-mono text-cyan-300">journalctl -u {{ selectedService.name }} -n 50</code> 查看。
          </div>
        </div>
      </div>
    </div>

    <!-- 停止/重启服务确认对话框 -->
    <dialog
      ref="confirmDialogRef"
      closedby="any"
      @close="pendingAction = null"
      class="m-auto w-full max-w-md rounded-xl bg-slate-900 text-slate-100 border border-slate-700 shadow-2xl p-5 backdrop:bg-slate-950/75"
    >
      <div v-if="pendingAction" class="space-y-4">
        <div class="flex items-center gap-2 text-sm font-bold text-slate-100">
          <ShieldAlert class="w-4 h-4 text-amber-400 shrink-0" />
          <span>确认{{ pendingAction.action === 'stop' ? '停止' : '重启' }}服务</span>
        </div>
        <p class="text-xs text-slate-300 leading-relaxed">
          将在远端服务器执行
          <code class="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 font-mono text-cyan-300">
            {{ useSudo ? 'sudo -n ' : '' }}systemctl {{ pendingAction.action }} -- {{ pendingAction.service.name }}
          </code>
          。确定继续吗？
        </p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            @click="closeConfirmDialog"
            class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 cursor-pointer"
          >
            取消
          </button>
          <button
            type="button"
            @click="confirmServiceAction"
            :class="[
              'px-3 py-1.5 rounded-lg text-xs font-semibold text-white cursor-pointer',
              pendingAction.action === 'stop' ? 'bg-rose-600 hover:bg-rose-500' : 'bg-cyan-600 hover:bg-cyan-500'
            ]"
          >
            确认{{ pendingAction.action === 'stop' ? '停止' : '重启' }}
          </button>
        </div>
      </div>
    </dialog>
  </div>
</template>
