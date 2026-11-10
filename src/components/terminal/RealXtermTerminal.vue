<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Terminal, type ITheme } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { KeyRound, RefreshCw } from 'lucide-vue-next'
import { resolvedColorScheme } from '@/stores/workbenchStore'

const props = defineProps<{
  hostAlias: string
}>()

const terminalEl = ref<HTMLDivElement | null>(null)
let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let ws: WebSocket | null = null

const isConnecting = ref(false)
const isConnected = ref(false)
const needPassword = ref(false)
const passwordInput = ref('')
const authErrorMsg = ref('')

// 暗色主题配色（深空灰黑 + 高对比亮青/绿光标）
const DARK_TERMINAL_THEME: ITheme = {
  background: '#020617', // slate-950
  foreground: '#f8fafc', // slate-50
  cursor: '#22d3ee', // cyan-400
  cursorAccent: '#020617',
  selectionBackground: 'rgba(8, 145, 178, 0.4)',
  black: '#0f172a',
  red: '#f87171',
  green: '#4ade80',
  yellow: '#facc15',
  blue: '#60a5fa',
  magenta: '#c084fc',
  cyan: '#22d3ee',
  white: '#f8fafc',
  brightBlack: '#64748b',
  brightRed: '#ef4444',
  brightGreen: '#22c55e',
  brightYellow: '#eab308',
  brightBlue: '#3b82f6',
  brightMagenta: '#a855f7',
  brightCyan: '#38bdf8',
  brightWhite: '#ffffff'
}

// 亮色主题配色（与 --surface-950 #f8fafc 严格对齐的高对比度调色盘）
const LIGHT_TERMINAL_THEME: ITheme = {
  background: '#f8fafc',
  foreground: '#0f172a', // slate-900
  cursor: '#0284c7', // sky-600
  cursorAccent: '#f8fafc',
  selectionBackground: 'rgba(2, 132, 199, 0.25)',
  black: '#0f172a',
  red: '#dc2626',
  green: '#15803d',
  yellow: '#b45309',
  blue: '#2563eb',
  magenta: '#7e22ce',
  cyan: '#0e7490',
  white: '#64748b',
  brightBlack: '#475569',
  brightRed: '#b91c1c',
  brightGreen: '#166534',
  brightYellow: '#854d0e',
  brightBlue: '#1d4ed8',
  brightMagenta: '#6b21a8',
  brightCyan: '#155e75',
  brightWhite: '#0f172a'
}

function getTerminalTheme(scheme: 'light' | 'dark'): ITheme {
  return scheme === 'dark' ? DARK_TERMINAL_THEME : LIGHT_TERMINAL_THEME
}

/**
 * 净化远端 ANSI 字符流中硬编码的暗色背景代码（如 \e[40m 黑色背景、\e[100m 亮黑背景及 \e[48;5;0m 256色黑底），
 * 将其平滑重映射为终端默认背景色代码（\e[49m），以确保终端始终强制保留与网页主题完全一致的底色，
 * 消除远端 bash PS1 等脚本造成的突兀色块。
 */
let pendingAnsiChunk = ''

function sanitizeAnsiStreamForTheme(text: string): string {
  const combined = pendingAnsiChunk + text
  // 检查数据末尾是否包含因网络分包截断的未闭合 ANSI 转义头（如 \x1b 或 \x1b[37;4）
  const unclosedMatch = combined.match(/\x1b\[?[0-9;]*$/)
  let toProcess = combined
  if (unclosedMatch) {
    toProcess = combined.slice(0, unclosedMatch.index)
    pendingAnsiChunk = unclosedMatch[0]
  } else {
    pendingAnsiChunk = ''
  }

  return toProcess.replace(/\x1b\[([0-9;]*)m/g, (match, paramStr) => {
    if (!paramStr) return match
    const parts = paramStr.split(';')
    let changed = false
    for (let i = 0; i < parts.length; i++) {
      const code = parts[i]
      if (code === '40' || code === '100') {
        parts[i] = '49' // 强制重置为终端默认底色
        changed = true
      } else if (code === '48' && parts[i + 1] === '5' && parts[i + 2] === '0') {
        parts.splice(i, 3, '49')
        changed = true
      }
    }
    return changed ? `\x1b[${parts.join(';')}m` : match
  })
}

function connectTerminal(password?: string) {
  if (!props.hostAlias) return
  if (ws) {
    ws.close()
    ws = null
  }

  isConnecting.value = true
  needPassword.value = false
  authErrorMsg.value = ''
  pendingAnsiChunk = ''

  if (term) {
    term.reset()
    term.writeln(`\x1b[36m正在建立终端会话通道...\x1b[0m`)
  }

  const wsUrl = `ws://127.0.0.1:8000/ws/terminal/${encodeURIComponent(props.hostAlias)}`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    isConnecting.value = false
    isConnected.value = true

    // 发送第一帧初始化与认证数据
    const cols = term ? term.cols : 120
    const rows = term ? term.rows : 34
    ws?.send(
      JSON.stringify({
        action: 'auth',
        payload: {
          password: password || undefined,
          cols,
          rows,
          term: 'xterm-256color'
        }
      })
    )
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.action === 'stdout' || msg.action === 'stderr') {
        const payload = sanitizeAnsiStreamForTheme(msg.payload)
        if (payload) {
          term?.write(payload)
        }
      } else if (msg.action === 'auth_required') {
        needPassword.value = true
        authErrorMsg.value = msg.payload || '需要输入 SSH 密码以继续连接'
        term?.writeln(`\r\n\x1b[33m${authErrorMsg.value}\x1b[0m\r\n`)
      }
    } catch {
      const payload = sanitizeAnsiStreamForTheme(event.data)
      if (payload) {
        term?.write(payload)
      }
    }
  }

  ws.onerror = () => {
    isConnecting.value = false
    isConnected.value = false
    term?.writeln('\r\n\x1b[31m终端服务通信异常，请确认后台服务正常运行 (http://127.0.0.1:8000)\x1b[0m\r\n')
  }

  ws.onclose = () => {
    isConnecting.value = false
    isConnected.value = false
    term?.writeln('\r\n\x1b[33mSSH 会话已断开。\x1b[0m\r\n')
  }
}

function submitPassword() {
  if (!passwordInput.value) return
  const pwd = passwordInput.value
  passwordInput.value = ''
  connectTerminal(pwd)
}

function handleResize() {
  if (!fitAddon || !term || !ws || ws.readyState !== WebSocket.OPEN) return
  try {
    fitAddon.fit()
    ws.send(
      JSON.stringify({
        action: 'resize',
        payload: {
          cols: term.cols,
          rows: term.rows
        }
      })
    )
  } catch {
    // ignore
  }
}

onMounted(() => {
  nextTick(() => {
    if (!terminalEl.value) return

    term = new Terminal({
      cursorBlink: true,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      fontSize: 13,
      lineHeight: 1.25,
      allowTransparency: true,
      theme: getTerminalTheme(resolvedColorScheme.value)
    })

    fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(terminalEl.value)

    // 立即同步执行 fit 计算，杜绝默认 24 行在挂载初期出现底部未填满空隙
    try {
      fitAddon.fit()
    } catch {
      // ignore
    }

    // 在下一渲染帧兜底，确保 flex 容器尺寸微调后精准对齐
    requestAnimationFrame(() => {
      try {
        fitAddon?.fit()
      } catch {
        // ignore
      }
    })

    // 用户在 xterm 敲击键盘输入，直接通过 WebSocket 发往 Python 后端
    term.onData((data) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            action: 'stdin',
            payload: data
          })
        )
      }
    })

    window.addEventListener('resize', handleResize)
    connectTerminal()
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (ws) {
    ws.close()
    ws = null
  }
  if (term) {
    term.dispose()
    term = null
  }
})

// 监听主题变化，动态热更新终端调色板（不重连，无感平滑切换）
watch(resolvedColorScheme, (newScheme) => {
  if (term) {
    term.options.theme = getTerminalTheme(newScheme)
    term.refresh(0, term.rows - 1)
  }
})

watch(
  () => props.hostAlias,
  (newVal, oldVal) => {
    if (newVal !== oldVal) {
      connectTerminal()
    }
  }
)
</script>

<template>
  <div class="relative w-full h-full flex flex-col bg-slate-950 overflow-hidden select-text">
    <!-- 终端状态信息条 -->
    <div class="h-7 px-3 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between text-xs shrink-0 select-none">
      <div class="flex items-center gap-2">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            isConnected ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]' : isConnecting ? 'bg-amber-400 animate-pulse' : 'bg-slate-500'
          ]"
        />
        <span class="font-mono text-slate-300">{{ props.hostAlias }}</span>
      </div>

      <button
        type="button"
        @click="connectTerminal()"
        class="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 border border-slate-700/60 cursor-pointer transition"
        title="重新连接终端"
      >
        <RefreshCw class="w-3 h-3" />
        <span>重连</span>
      </button>
    </div>

    <!-- xterm 容器 -->
    <div ref="terminalEl" class="flex-1 w-full h-full p-2 bg-slate-950 overflow-hidden" />

    <!-- 临时密码交互输入弹窗 -->
    <div
      v-if="needPassword"
      class="absolute inset-0 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4 z-20"
    >
      <div class="w-full max-w-sm rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-2xl space-y-4">
        <div class="flex items-center gap-2.5 text-amber-400">
          <KeyRound class="w-5 h-5 shrink-0" />
          <h3 class="text-sm font-bold text-slate-100">输入 SSH 会话密码</h3>
        </div>

        <p class="text-xs text-slate-400 leading-relaxed">
          目标主机 <span class="font-mono text-cyan-300 font-semibold">{{ props.hostAlias }}</span> 未配置免密私钥。
          密码仅在当前会话握手时使用，不会保存到磁盘。
        </p>

        <form @submit.prevent="submitPassword" class="space-y-3">
          <input
            v-model="passwordInput"
            type="password"
            autofocus
            placeholder="输入 SSH 登录密码..."
            class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-slate-100 focus:outline-none focus:border-cyan-500 font-mono"
          />

          <div class="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              @click="needPassword = false"
              class="px-3 py-1.5 rounded-lg text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer"
            >
              取消
            </button>
            <button
              type="submit"
              class="px-4 py-1.5 rounded-lg text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white cursor-pointer"
            >
              连接
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style>
/* 保证 xterm 视口完美撑满容器，并彻底覆盖 xterm.css 默认硬编码的 #000 黑底，消除强刷与未填满区域闪黑 */
.xterm {
  height: 100%;
}

.xterm,
.xterm .xterm-viewport,
.xterm .xterm-screen {
  background-color: var(--surface-950) !important;
}

.xterm-viewport {
  overflow-y: auto !important;
}
</style>
