<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import {
  store,
  executeTerminalCommand,
  openFileInEditor,
  navigateWithContext,
  triggerSnippetExecution,
  setExplicitColorScheme
} from '@/stores/workbenchStore'
import { Search, ArrowRight, Play, Sparkles, Sun, Moon } from 'lucide-vue-next'

const spotlightDialogRef = ref<HTMLDialogElement | null>(null)
const paramDialogRef = ref<HTMLDialogElement | null>(null)
const query = ref('')

// 遵循 modern-web-guidance `dialog` 指南：使用原生 <dialog> 的 showModal() 打开，并提供 closedby="any" 降级支持
function attachLightDismissFallback(dialogEl: HTMLDialogElement | null) {
  if (!dialogEl) return
  if (!('closedBy' in HTMLDialogElement.prototype)) {
    const outside = (e: PointerEvent, d: HTMLDialogElement) => {
      const r = d.getBoundingClientRect()
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom
    }
    let pressedOutside = false
    dialogEl.addEventListener('pointerdown', (e) => {
      pressedOutside = outside(e, dialogEl)
    })
    dialogEl.addEventListener('pointerup', (e) => {
      if (pressedOutside && outside(e, dialogEl)) dialogEl.close()
    })
  }
}

onMounted(() => {
  attachLightDismissFallback(spotlightDialogRef.value)
  attachLightDismissFallback(paramDialogRef.value)
})

watch(
  () => store.commandPaletteOpen,
  (isOpen) => {
    const el = spotlightDialogRef.value
    if (!el) return
    if (isOpen && !el.open) {
      query.value = ''
      el.showModal()
    } else if (!isOpen && el.open) {
      el.close()
    }
  }
)

watch(
  () => store.paramModal.open,
  (isOpen) => {
    const el = paramDialogRef.value
    if (!el) return
    if (isOpen && !el.open) {
      el.showModal()
    } else if (!isOpen && el.open) {
      el.close()
    }
  }
)

function handleSpotlightClose() {
  if (spotlightDialogRef.value) {
    spotlightDialogRef.value.returnValue = ''
  }
  store.commandPaletteOpen = false
}

function handleParamModalClose() {
  if (paramDialogRef.value) {
    paramDialogRef.value.returnValue = ''
  }
  store.paramModal.open = false
}

const spotlightActions = computed(() => {
  const q = query.value.trim().toLowerCase()
  const baseActions = [
    {
      id: 'act-theme-light',
      title: '切换 UI 外观为：白天模式 (Light Theme)',
      category: '界面外观与主题',
      run: () => setExplicitColorScheme('light')
    },
    {
      id: 'act-theme-dark',
      title: '切换 UI 外观为：暗黑模式 (Dark Theme)',
      category: '界面外观与主题',
      run: () => setExplicitColorScheme('dark')
    },
    {
      id: 'act-theme-system',
      title: `恢复 UI 外观为：跟随系统 (${store.systemIsDark ? '当前系统为暗黑' : '当前系统为白天'})`,
      category: '界面外观与主题',
      run: () => setExplicitColorScheme('light dark')
    },
    {
      id: 'act-fw-8080',
      title: '防火墙一键放行 8080 端口 (api-core)',
      category: '跨模块动作',
      run: () => {
        navigateWithContext({
          sourcePage: store.activePage,
          targetPage: 'P8_FIREWALL',
          reason: '从 Cmd+K 快捷放行 8080 端口',
          prefillFirewallPort: 8080,
          prefillFirewallProtocol: 'tcp',
          prefillFirewallComment: 'API Core Service'
        })
      }
    },
    {
      id: 'act-edit-nginx',
      title: '使用内置编辑器打开 /etc/nginx/nginx.conf',
      category: '远程文件直达',
      run: () => openFileInEditor('/etc/nginx/nginx.conf', 'nginx.service')
    },
    {
      id: 'act-restart-celery',
      title: '排查并重启异常服务 celery-beat.service',
      category: 'Systemd 管控',
      run: () => {
        navigateWithContext({
          sourcePage: store.activePage,
          targetPage: 'P6_SYSTEMD',
          reason: '从 Cmd+K 定位异常退出的 celery-beat.service',
          filterService: 'celery-beat.service'
        })
      }
    },
    ...store.savedSnippets.map((s) => ({
      id: `snip-${s.id}`,
      title: `常用命令: ${s.title} (${s.commandTemplate})`,
      category: s.category,
      run: () => triggerSnippetExecution(s)
    }))
  ]

  if (!q) return baseActions
  return baseActions.filter(
    (a) => a.title.toLowerCase().includes(q) || a.category.toLowerCase().includes(q)
  )
})

const renderedCommand = computed(() => {
  const snip = store.paramModal.snippet
  if (!snip) return ''
  return snip.commandTemplate.replace(/\{\{([^:}]+)(?::[^}]*)?\}\}/g, (_, varName: string) => {
    return store.paramModal.values[varName] || ''
  })
})

function confirmParameterizedCommand() {
  const finalCmd = renderedCommand.value
  if (store.paramModal.snippet) {
    store.paramModal.snippet.usageCount++
  }
  store.paramModal.open = false
  executeTerminalCommand(finalCmd, true)
}
</script>

<template>
  <!-- 1. 全局 Spotlight 命令与跨页面跳转面板 (原生 <dialog>) -->
  <dialog
    ref="spotlightDialogRef"
    aria-labelledby="spotlight-dialog-title"
    closedby="any"
    @close="handleSpotlightClose"
    class="m-auto w-full max-w-xl rounded-xl bg-slate-900 text-slate-100 border border-slate-700 shadow-2xl p-0 backdrop:bg-slate-950/75"
  >
    <div class="p-3 border-b border-slate-800 flex items-center gap-2.5">
      <Search class="w-4 h-4 text-cyan-400 shrink-0" />
      <h2 id="spotlight-dialog-title" class="sr-only">全局命令与页面跳转面板</h2>
      <input
        v-model="query"
        type="search"
        autofocus
        placeholder="搜索页面、常用命令、监听端口或直接输入文件路径 (/etc/nginx/...)..."
        class="w-full bg-transparent text-sm text-slate-100 focus:outline-none"
      />
      <form method="dialog">
        <button
          type="submit"
          value="cancel"
          class="px-2 py-0.5 text-[11px] rounded bg-slate-800 text-slate-400 hover:text-slate-100 cursor-pointer"
        >
          Esc
        </button>
      </form>
    </div>

    <!-- 快捷三态外观切换条 (System / Light / Dark) -->
    <div class="px-3 py-2 bg-slate-950/70 border-b border-slate-800 flex items-center justify-between text-xs">
      <span class="text-slate-400">UI 主题外观偏好：</span>
      <div class="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800">
        <button
          type="button"
          @click="setExplicitColorScheme('light')"
          :class="[
            'flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition cursor-pointer',
            store.colorSchemePref === 'light'
              ? 'bg-cyan-600 text-white'
              : 'text-slate-400 hover:text-slate-100'
          ]"
        >
          <Sun class="w-3 h-3" />
          <span>白天 (Light)</span>
        </button>
        <button
          type="button"
          @click="setExplicitColorScheme('dark')"
          :class="[
            'flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition cursor-pointer',
            store.colorSchemePref === 'dark'
              ? 'bg-cyan-600 text-white'
              : 'text-slate-400 hover:text-slate-100'
          ]"
        >
          <Moon class="w-3 h-3" />
          <span>暗黑 (Dark)</span>
        </button>
        <button
          type="button"
          @click="setExplicitColorScheme('light dark')"
          :class="[
            'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition cursor-pointer',
            store.colorSchemePref === 'light dark'
              ? 'bg-cyan-600 text-white'
              : 'text-slate-400 hover:text-slate-100'
          ]"
        >
          <span class="relative inline-flex items-center justify-center w-3.5 h-3.5">
            <Sun aria-hidden="true" class="w-3.5 h-3.5" />
            <span
              aria-hidden="true"
              class="absolute -bottom-0.5 -right-1 flex items-center justify-center min-w-[9px] h-[9px] px-[1px] text-[7px] leading-none font-extrabold font-mono rounded-[2px] bg-slate-950 text-cyan-400 ring-1 ring-cyan-500/50"
            >
              A
            </span>
          </span>
          <span>自动模式 ({{ store.systemIsDark ? '当前夜间' : '当前白天' }})</span>
        </button>
      </div>
    </div>

    <div class="max-h-80 overflow-y-auto p-2 space-y-1">
      <button
        v-for="item in spotlightActions"
        :key="item.id"
        type="button"
        @click="
          () => {
            store.commandPaletteOpen = false
            item.run()
          }
        "
        class="w-full flex items-center justify-between px-3 py-2 rounded-lg hover:bg-slate-800/90 text-left transition cursor-pointer group"
      >
        <div class="min-w-0 pr-3">
          <div class="text-xs font-medium text-slate-200 group-hover:text-cyan-300 truncate">
            {{ item.title }}
          </div>
          <div class="text-[10px] text-slate-400">{{ item.category }}</div>
        </div>
        <ArrowRight class="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400 shrink-0" />
      </button>
    </div>
  </dialog>

  <!-- 2. 参数化常用命令变量填写弹窗 (原生 <dialog>) -->
  <dialog
    ref="paramDialogRef"
    aria-labelledby="param-dialog-title"
    closedby="any"
    @close="handleParamModalClose"
    class="m-auto w-full max-w-lg rounded-xl bg-slate-900 text-slate-100 border border-slate-700 shadow-2xl p-0"
  >
    <div v-if="store.paramModal.snippet" class="p-4 space-y-4">
      <div class="flex items-start justify-between border-b border-slate-800 pb-3">
        <div>
          <div class="flex items-center gap-2">
            <Sparkles class="w-4 h-4 text-cyan-400" />
            <h2 id="param-dialog-title" class="text-sm font-semibold text-slate-100">
              执行参数化命令：{{ store.paramModal.snippet.title }}
            </h2>
          </div>
          <p class="text-xs text-slate-400 mt-1">{{ store.paramModal.snippet.description }}</p>
        </div>
        <form method="dialog">
          <button
            type="submit"
            value="cancel"
            class="px-2 py-1 text-xs rounded bg-slate-800 text-slate-400 hover:text-slate-100 cursor-pointer"
          >
            关闭
          </button>
        </form>
      </div>

      <!-- 动态变量输入表单 -->
      <div class="space-y-3">
        <div
          v-for="(v, idx) in store.paramModal.snippet.variables"
          :key="v.name"
          class="space-y-1"
        >
          <label :for="`var-input-${v.name}`" class="flex items-center justify-between text-xs">
            <span class="font-mono text-cyan-300 font-semibold">&#123;&#123; {{ v.name }} &#125;&#125;</span>
            <span class="text-slate-400">{{ v.description }}</span>
          </label>
          <div class="flex gap-2">
            <input
              :id="`var-input-${v.name}`"
              v-model="store.paramModal.values[v.name]"
              :autofocus="idx === 0"
              type="text"
              class="flex-1 px-3 py-1.5 rounded-md bg-slate-950 border border-slate-700 text-xs font-mono text-slate-100 focus:border-cyan-400 focus:outline-none"
            />
            <select
              v-if="v.options && v.options.length > 0"
              v-model="store.paramModal.values[v.name]"
              aria-label="历史高频可选值"
              class="px-2 py-1.5 rounded-md bg-slate-800 border border-slate-700 text-xs text-slate-200"
            >
              <option v-for="opt in v.options" :key="opt" :value="opt">
                历史值: {{ opt }}
              </option>
            </select>
          </div>
        </div>
      </div>

      <!-- 实时合成的最终命令预览 -->
      <div class="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
        <div class="text-[11px] text-slate-400 flex items-center justify-between">
          <span>实时合成待执行 Shell 指令</span>
          <span class="font-mono text-emerald-400">SSH Ready</span>
        </div>
        <div class="font-mono text-xs text-cyan-300 break-all">
          {{ renderedCommand }}
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
        <button
          type="button"
          @click="confirmParameterizedCommand"
          class="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer"
        >
          <Play class="w-3.5 h-3.5" />
          <span>立即注入主终端并执行</span>
        </button>
      </div>
    </div>
  </dialog>
</template>
