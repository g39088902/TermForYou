<script setup lang="ts">
import {
  store,
  showToast,
  toggleColorScheme
} from '@/stores/workbenchStore'
import {
  Server,
  Plus,
  Search,
  Sun,
  Moon,
  X
} from 'lucide-vue-next'

function switchHost(hostId: string) {
  store.activeHostId = hostId
  if (store.activePage === 'P0_HOSTS') {
    store.activePage = 'P1_WORKBENCH'
  }
}

function closeHostTab(hostId: string, e: MouseEvent) {
  e.stopPropagation()
  store.openHostIds = store.openHostIds.filter((id) => id !== hostId)
  if (store.activeHostId === hostId) {
    if (store.openHostIds.length > 0) {
      store.activeHostId = store.openHostIds[0]
    } else {
      store.activeHostId = ''
      store.activePage = 'P0_HOSTS'
      showToast('已关闭所有活动会话，返回主机连接池')
    }
  }
}
</script>

<template>
  <header class="h-11 bg-slate-950 border-b border-slate-800/90 px-3 flex items-center justify-between select-none shrink-0">
    <!-- 左侧：主机池入口与多服务器会话 Tabs -->
    <div class="flex items-center gap-2 overflow-x-auto min-w-0">
      <button
        type="button"
        @click="store.activePage = 'P0_HOSTS'"
        :class="[
          'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer shrink-0',
          store.activePage === 'P0_HOSTS'
            ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
            : 'bg-slate-900 text-slate-300 hover:bg-slate-800 border border-slate-800'
        ]"
        title="打开主机连接池"
      >
        <Server class="w-3.5 h-3.5 text-cyan-400" />
        <span>主机池</span>
        <span class="px-1 py-0.2 text-[10px] rounded bg-slate-800 text-slate-400 font-mono">{{ store.hosts.length }}</span>
      </button>

      <div class="h-4 w-px bg-slate-800 shrink-0 mx-0.5" />

      <!-- 多服务器会话 Tabs -->
      <div v-if="store.openHostIds.length > 0" class="flex items-center gap-1.5">
        <div
          v-for="hostId in store.openHostIds"
          :key="hostId"
          @click="switchHost(hostId)"
          :class="[
            'group flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium cursor-pointer transition border',
            store.activeHostId === hostId && store.activePage !== 'P0_HOSTS'
              ? 'bg-slate-800/95 text-slate-100 border-cyan-500/50 shadow-sm'
              : 'bg-slate-900/60 text-slate-400 border-slate-800/70 hover:bg-slate-900 hover:text-slate-200'
          ]"
        >
          <span
            :class="[
              'w-2 h-2 rounded-full',
              store.hosts.find((h) => h.id === hostId)?.status === 'online'
                ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]'
                : 'bg-amber-400'
            ]"
          />
          <Server class="w-3.5 h-3.5 text-slate-400" />
          <span>{{ store.hosts.find((h) => h.id === hostId)?.name }}</span>
          <span class="text-[10px] text-slate-500 font-mono">
            {{ store.hosts.find((h) => h.id === hostId)?.ip }}
          </span>
          <button
            type="button"
            @click="closeHostTab(hostId, $event)"
            aria-label="关闭服务器会话标签"
            class="opacity-60 hover:opacity-100 hover:bg-slate-700/70 rounded p-0.5"
          >
            <X class="w-3 h-3" />
          </button>
        </div>

        <button
          type="button"
          @click="store.activePage = 'P0_HOSTS'"
          title="连接更多服务器"
          class="p-1.5 rounded-md bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 cursor-pointer"
        >
          <Plus class="w-3.5 h-3.5" />
        </button>
      </div>

      <div v-else class="flex items-center gap-2 text-xs text-slate-500 pl-1">
        <span>当前无活动会话</span>
        <button
          type="button"
          @click="store.activePage = 'P0_HOSTS'"
          class="text-cyan-400 hover:underline cursor-pointer text-xs"
        >
          去连接服务器 →
        </button>
      </div>
    </div>

    <!-- 右侧：外观切换与全局 Cmd+K 命令面板 -->
    <div class="flex items-center gap-2">
      <!-- 三态纯图标外观切换按钮：白天(太阳) / 夜间(月亮) / 自动跟随系统(太阳右下角加A) -->
      <button
        type="button"
        @click="toggleColorScheme"
        class="relative inline-flex items-center justify-center min-w-7 min-h-7 p-1.5 rounded-md bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition cursor-pointer"
        :title="
          store.colorSchemePref === 'light'
            ? '当前：白天模式（点击切换为夜间模式）'
            : store.colorSchemePref === 'dark'
              ? '当前：夜间模式（点击切换为自动跟随系统）'
              : `当前：自动模式 · 跟随系统（当前${store.systemIsDark ? '夜间' : '白天'}，点击切换为白天模式）`
        "
      >
        <!-- 白天模式：太阳图标 -->
        <span class="if-scheme-light items-center justify-center">
          <Sun aria-hidden="true" class="w-4 h-4 text-amber-400" />
          <span class="sr-only">当前白天模式，点击切换为夜间模式</span>
        </span>

        <!-- 夜间模式：月亮图标 -->
        <span class="if-scheme-dark items-center justify-center">
          <Moon aria-hidden="true" class="w-4 h-4 text-cyan-400" />
          <span class="sr-only">当前夜间模式，点击切换为自动模式（跟随系统）</span>
        </span>

        <!-- 自动模式（跟随系统）：太阳图标 + 右下角 A 角标 -->
        <span class="if-scheme-auto relative items-center justify-center w-4 h-4">
          <Sun aria-hidden="true" class="w-4 h-4 text-amber-400" />
          <span
            aria-hidden="true"
            class="absolute -bottom-0.5 -right-1 flex items-center justify-center min-w-[10px] h-[10px] px-[1.5px] text-[8px] leading-none font-extrabold font-mono rounded-[2px] bg-slate-950 text-cyan-400 ring-1 ring-cyan-500/50"
          >
            A
          </span>
          <span class="sr-only">当前自动模式（跟随系统），点击切换为白天模式</span>
        </span>
      </button>

      <button
        type="button"
        @click="store.commandPaletteOpen = true"
        class="flex items-center gap-2 px-3 py-1 rounded-md bg-slate-900 hover:bg-slate-800 border border-slate-700/80 text-xs text-slate-300 transition cursor-pointer"
      >
        <Search class="w-3.5 h-3.5 text-cyan-400" />
        <span>搜索或执行命令...</span>
        <kbd class="px-1.5 py-0.5 text-[10px] font-mono bg-slate-800 text-slate-400 rounded border border-slate-700">
          ⌘K
        </kbd>
      </button>
    </div>
  </header>
</template>
