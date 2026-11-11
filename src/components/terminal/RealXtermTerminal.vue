<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Terminal, type ITheme } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { KeyRound, RefreshCw } from 'lucide-vue-next'
import { resolvedColorScheme } from '@/stores/workbenchStore'

const props = withDefaults(
  defineProps<{
    hostAlias: string
    dockerContainer?: string
    sudo?: boolean
    /** 父级为吸收取整余量而额外撑高的像素（用于还原不含余量的原始可用高度） */
    externalSlack?: number
  }>(),
  { externalSlack: 0 }
)

const emit = defineEmits<{
  /** 终端吸附到整行后剩余的非整行高度（px），由父级的上下可伸缩组件承担 */
  (e: 'slack', value: { top: number; bottom: number }): void
}>()

const HEADER_BASE_HEIGHT = 28
const rootEl = ref<HTMLDivElement | null>(null)
const headerExtra = ref(0)
const terminalHeight = ref<number | null>(null)

const terminalEl = ref<HTMLDivElement | null>(null)
let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let ws: WebSocket | null = null
let authSent = false
let lastSentCols = 0
let lastSentRows = 0
let resizeObserver: ResizeObserver | null = null

const isConnecting = ref(false)
const isConnected = ref(false)
const needPassword = ref(false)
const passwordInput = ref('')
const authErrorMsg = ref('')

const currentCols = ref(80)
const currentRows = ref(24)

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

function isUserAtBottom(): boolean {
  if (!term) return true
  try {
    const buffer = term.buffer.active
    return buffer.viewportY >= buffer.baseY
  } catch {
    return true
  }
}

function connectTerminal(password?: string) {
  if (!props.hostAlias) return
  if (ws) {
    ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null
    ws.close()
    ws = null
  }

  isConnecting.value = true
  isConnected.value = false
  authSent = false
  needPassword.value = false
  authErrorMsg.value = ''
  pendingAnsiChunk = ''
  lastSentCols = 0
  lastSentRows = 0

  if (term) {
    term.reset()
    term.writeln(`\x1b[36m正在建立终端会话通道...\x1b[0m`)
  }

  const wsUrl = `ws://127.0.0.1:8000/ws/terminal/${encodeURIComponent(props.hostAlias)}`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    // 握手前精准测量尺寸
    handleResize()
    const cols = term ? term.cols : 80
    const rows = term ? term.rows : 24
    lastSentCols = cols
    lastSentRows = rows

    ws?.send(
      JSON.stringify({
        action: 'auth',
        payload: {
          password: password || undefined,
          cols,
          rows,
          term: 'xterm-256color',
          docker_container: props.dockerContainer || undefined,
          sudo: props.sudo ?? false
        }
      })
    )
    authSent = true
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.action === 'ready') {
        isConnecting.value = false
        isConnected.value = true
        term?.focus()
      } else if (msg.action === 'stdout' || msg.action === 'stderr') {
        const payload = sanitizeAnsiStreamForTheme(msg.payload)
        if (payload) {
          const wasAtBottom = isUserAtBottom()
          term?.write(payload, () => {
            // 系统终端标准体验：
            // 若用户当前处于最底部，新输出自动跟随滚动到底部；
            // 若用户主动往上滚使输入区居中或查看历史日志，绝不强行拽到底部打断用户
            if (wasAtBottom) {
              term?.scrollToBottom()
            }
          })
        }
      } else if (msg.action === 'auth_required') {
        isConnecting.value = false
        needPassword.value = true
        authErrorMsg.value = msg.payload || '需要输入 SSH 密码以继续连接'
        term?.writeln(`\r\n\x1b[33m${authErrorMsg.value}\x1b[0m\r\n`)
      }
    } catch {
      const payload = sanitizeAnsiStreamForTheme(event.data)
      if (payload) {
        const wasAtBottom = isUserAtBottom()
        term?.write(payload, () => {
          if (wasAtBottom) {
            term?.scrollToBottom()
          }
        })
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

/**
 * 终端尺寸解算：
 * 终端显示区严格吸附到单元格行高的整数倍（xterm 自身高度 = rows × cellHeight），背景与之同高无缝跟随；
 * 浏览器窗口自由缩放产生的非整行余量，不留在终端内部，而是拆分给上方状态栏（本组件）
 * 与下方 AI Copilot 栏（父级，经 `slack` 事件上报）承担，两者仅表现为内边距略有伸缩。
 */
function handleResize() {
  if (!term || !terminalEl.value || !rootEl.value) return
  try {
    const rect = rootEl.value.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return

    const core = (term as any)._core
    const renderCellWidth = core?._renderService?.dimensions?.css?.cell?.width || 0
    const renderCellHeight = core?._renderService?.dimensions?.css?.cell?.height || 0
    const cellWidth = Math.max(7.5, renderCellWidth || 7.82)
    const cellHeight = Math.max(18.0, renderCellHeight || 19.0)

    // 不含任何余量时的原始可用高度（根高度 + 父级已承担的余量 - 状态栏基础高度）
    const baseHeight = rect.height + props.externalSlack - HEADER_BASE_HEIGHT
    const cols = Math.max(20, Math.floor(rect.width / cellWidth))
    const rows = Math.max(5, Math.floor(baseHeight / cellHeight))

    const slack = Math.max(0, baseHeight - rows * cellHeight)
    const top = Math.floor(slack / 2)
    const bottom = slack - top
    headerExtra.value = top
    terminalHeight.value = rows * cellHeight
    emit('slack', { top, bottom })

    if (term.cols !== cols || term.rows !== rows) {
      term.resize(cols, rows)
    }

    currentCols.value = term.cols
    currentRows.value = term.rows

    // 若用户原本处于底端，新尺寸生效后滚至底端贴底；若用户在向上翻看历史，不干扰其视线
    if (isUserAtBottom()) {
      term.scrollToBottom()
    }

    if (authSent && ws && ws.readyState === WebSocket.OPEN) {
      if (term.cols !== lastSentCols || term.rows !== lastSentRows) {
        lastSentCols = term.cols
        lastSentRows = term.rows
        ws.send(
          JSON.stringify({
            action: 'resize',
            payload: {
              cols: term.cols,
              rows: term.rows
            }
          })
        )
      }
    }
  } catch {
    // 降级兜底
    try {
      fitAddon?.fit()
      if (term) {
        currentCols.value = term.cols
        currentRows.value = term.rows
      }
    } catch {
      // ignore
    }
  }
}

function sendData(data: string) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(
      JSON.stringify({
        action: 'stdin',
        payload: data
      })
    )
  }
}

function sendCommand(command: string) {
  if (!command) return
  const payload = command.endsWith('\r') || command.endsWith('\n') ? command : `${command}\r`
  sendData(payload)
}

function interrupt() {
  sendData('\x03') // Ctrl+C
}

function clearScreen() {
  sendData('clear\r')
  term?.clear()
}

function focus() {
  term?.focus()
}

defineExpose({
  sendData,
  sendCommand,
  interrupt,
  clearScreen,
  focus,
  cols: currentCols,
  rows: currentRows,
  isConnected,
  isConnecting
})

onMounted(() => {
  nextTick(() => {
    if (!terminalEl.value) return

    term = new Terminal({
      cursorBlink: true,
      cursorStyle: 'block',
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      fontSize: 13,
      lineHeight: 1.267,
      scrollback: 5000,
      scrollOnUserInput: true,
      smoothScrollDuration: 100,
      allowTransparency: true,
      theme: getTerminalTheme(resolvedColorScheme.value)
    })

    fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(terminalEl.value)

    // 立即执行精准防截断尺寸计算
    try {
      handleResize()
    } catch {
      // ignore
    }

    // 在下一渲染帧兜底，确保 flex 容器尺寸微调后精准对齐
    requestAnimationFrame(() => {
      try {
        handleResize()
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
    if (terminalEl.value && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        handleResize()
      })
      resizeObserver.observe(rootEl.value ?? terminalEl.value)
    }
    connectTerminal()
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (ws) {
    ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null
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
  () => [props.hostAlias, props.dockerContainer, props.sudo],
  () => {
    connectTerminal()
  }
)
</script>

<template>
  <div ref="rootEl" class="relative w-full h-full flex flex-col bg-slate-950 overflow-hidden select-text">
    <!-- 终端状态信息条 -->
    <div
      class="px-3 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between text-xs shrink-0 select-none"
      :style="{ height: `${HEADER_BASE_HEIGHT + headerExtra}px` }"
    >
      <div class="flex items-center gap-2">
        <span
          :class="[
            'w-2 h-2 rounded-full',
            isConnected ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]' : isConnecting ? 'bg-amber-400 animate-pulse' : 'bg-slate-500'
          ]"
        />
        <span class="font-mono text-slate-300">{{ props.hostAlias }}</span>
        <span v-if="props.dockerContainer" class="font-mono text-sky-300">/ {{ props.dockerContainer }}</span>
      </div>

      <div class="flex items-center gap-2">
        <span class="font-mono text-[10px] text-slate-500 select-none">
          {{ currentCols }} × {{ currentRows }}
        </span>
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
    </div>

    <!-- xterm 终端视口：高度严格为 rows × 行高，吸附整行；其余空间由上下栏承担 -->
    <div
      ref="terminalEl"
      class="w-full p-0 bg-slate-950 overflow-hidden shrink-0"
      :style="{ height: terminalHeight === null ? 'auto' : `${terminalHeight}px` }"
    />

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
/* 保证 xterm 视口完美撑满容器，消除突兀边界，并彻底覆盖 xterm.css 默认硬编码的 #000 黑底 */
.xterm {
  height: 100%;
  width: 100%;
  padding: 0;
}

.xterm,
.xterm .xterm-viewport,
.xterm .xterm-scrollable-element,
.xterm .xterm-screen {
  background-color: var(--surface-950) !important;
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
}

.xterm-viewport {
  overflow-y: auto !important;
}
</style>
