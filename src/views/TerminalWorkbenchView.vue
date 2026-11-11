<script setup lang="ts">
import { ref } from 'vue'
import {
  store,
  currentHost,
  extractedClusters,
  executeTerminalCommand,
  triggerSnippetExecution,
  promoteClusterToSnippet
} from '@/stores/workbenchStore'
import RealXtermTerminal from '@/components/terminal/RealXtermTerminal.vue'
import {
  Terminal,
  Sparkles,
  Play,
  Columns2,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  X,
  Loader2,
  Bot,
  ChevronDown,
  ChevronUp
} from 'lucide-vue-next'

const splitPaneMode = ref(false)
const highRiskBlockedCmd = ref('')
// 终端吸附整行后的余量：下半部分由下方 AI Copilot 栏承担（上半部分由终端状态栏承担）
const copilotSlack = ref(0)
function onTerminalSlack(v: { top: number; bottom: number }) {
  const next = Math.round(v.bottom * 2) / 2
  if (next !== copilotSlack.value) copilotSlack.value = next
}

const activeTargetPane = ref<'main' | 'secondary'>('main')

// 终端组件实例引用
const mainTerminalRef = ref<InstanceType<typeof RealXtermTerminal> | null>(null)
const secondaryTerminalRef = ref<InstanceType<typeof RealXtermTerminal> | null>(null)

// 预留的自然语言 AI 生成命令状态
const aiPromptInput = ref('')
const isGenerating = ref(false)
const isAiCopilotCollapsed = ref(false)
const aiSuggestion = ref<{
  prompt: string
  command: string
  explanation: string
} | null>(null)

const quickPromptChips = [
  '查内存最高前5的进程',
  '排查占用80与443端口的程序',
  '搜索大于100M的日志文件',
  '清理所有退出的Docker容器',
  '查看最近50条系统错误日志'
]

function getActiveTerminal() {
  return (splitPaneMode.value && activeTargetPane.value === 'secondary')
    ? secondaryTerminalRef.value
    : mainTerminalRef.value
}

function forceExecuteHighRisk() {
  if (!highRiskBlockedCmd.value) return
  const cmd = highRiskBlockedCmd.value
  highRiskBlockedCmd.value = ''
  runCommandInTerminal(cmd)
}

function runCommandInTerminal(cmd: string) {
  const trimmed = cmd.trim()
  if (!trimmed) return

  // 高危拦截
  if (/^(rm\s+-rf\s+\/|mkfs|dd\s+if=.*of=\/dev|:(){ :\|:& };:)/i.test(trimmed)) {
    highRiskBlockedCmd.value = trimmed
    return
  }

  getActiveTerminal()?.sendCommand(trimmed)
  executeTerminalCommand(trimmed)
}

/**
 * 预留自然语言 AI 生成命令处理函数 (已打通本地启发推导，预留 LLM API 接入管道)
 */
async function handleGenerateCommand() {
  const query = aiPromptInput.value.trim()
  if (!query) return

  isGenerating.value = true
  aiSuggestion.value = null

  // 模拟推理响应
  await new Promise(r => setTimeout(r, 350))

  let generatedCmd = ''
  let explanation = ''

  const q = query.toLowerCase()
  if (q.includes('内存') && (q.includes('最高') || q.includes('5') || q.includes('进程'))) {
    generatedCmd = 'ps aux --sort=-%mem | head -n 6'
    explanation = '按物理内存占用率降序排序并展示 Top 5 进程'
  } else if (q.includes('端口') || q.includes('80') || q.includes('443') || q.includes('占用')) {
    generatedCmd = 'ss -tulnp | grep -E ":(80|443|8080|22)\\b"'
    explanation = '检索网络套接字中匹配 80/443/8080/22 端口的监听进程与 PID'
  } else if (q.includes('大文件') || q.includes('100m') || q.includes('日志')) {
    generatedCmd = 'find / -xdev -type f -size +100M -exec ls -lh {} + 2>/dev/null | sort -rh -k 5 | head -n 10'
    explanation = '在根文件系统检索体积大于 100MB 的文件并按大小降序输出 Top 10'
  } else if (q.includes('docker') && (q.includes('清理') || q.includes('退出') || q.includes('exited'))) {
    generatedCmd = 'docker container prune -f'
    explanation = '一键批量清理全部已停止状态的无害 Docker 容器'
  } else if (q.includes('错误') || q.includes('系统日志') || q.includes('journalctl')) {
    generatedCmd = 'journalctl -p err..emerg -n 50 --no-pager'
    explanation = '检索优先级在 Error 至 Emergency 级别的最新 50 条系统异常日志'
  } else if (q.includes('磁盘') || q.includes('空间') || q.includes('df')) {
    generatedCmd = 'df -hT --exclude-type=tmpfs --exclude-type=devtmpfs'
    explanation = '排查所有实体文件系统与挂载分区的容量与可用空间'
  } else {
    generatedCmd = `echo "# [AI 生成] ${query}" && ${query.replace(/[\r\n]/g, ' ')}`
    explanation = `已基于你的自然语言意图「${query}」自动生成匹配命令`
  }

  aiSuggestion.value = {
    prompt: query,
    command: generatedCmd,
    explanation
  }
  isGenerating.value = false
}

function applyAiCommand() {
  if (!aiSuggestion.value) return
  runCommandInTerminal(aiSuggestion.value.command)
  aiSuggestion.value = null
  aiPromptInput.value = ''
  getActiveTerminal()?.focus()
}

function setPrompt(promptText: string) {
  aiPromptInput.value = promptText
  handleGenerateCommand()
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- 主工作区：左终端 + 右智能命令侧边栏 -->
    <div class="flex-1 flex min-h-0 overflow-hidden">
      <!-- 左侧：多标签/分屏 SSH 终端主舞台 -->
      <div class="flex-1 flex flex-col bg-slate-950 border-r border-slate-800 min-w-0">
        <!-- 终端工具栏 -->
        <div class="h-9 px-3 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between text-xs shrink-0">
          <div class="flex items-center gap-2">
            <Terminal class="w-3.5 h-3.5 text-cyan-400" />
            <span class="font-semibold text-slate-100">SSH 终端 ({{ currentHost.name }})</span>
            <span class="px-1.5 py-0.5 rounded bg-slate-800 text-amber-300 font-mono text-[11px]">
              {{ currentHost.ip }}:{{ currentHost.port }}
            </span>
            <span
              class="flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 font-mono text-[10px] border border-emerald-500/30"
            >
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span>已连接</span>
            </span>
            <span
              v-if="currentHost.uptime && currentHost.uptime !== '检测就绪'"
              class="hidden sm:inline-block px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400 font-mono text-[10px]"
              title="服务器已连续运行时间"
            >
              运行: {{ currentHost.uptime }}
            </span>
          </div>

          <div class="flex items-center gap-2">
            <button
              type="button"
              @click="splitPaneMode = !splitPaneMode"
              :class="[
                'flex items-center gap-1 px-2.5 py-1 rounded text-[11px] border cursor-pointer transition',
                splitPaneMode
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                  : 'bg-slate-800 text-slate-300 border-slate-700 hover:text-white'
              ]"
            >
              <Columns2 class="w-3 h-3" />
              <span>{{ splitPaneMode ? '取消分屏' : '双栏分屏' }}</span>
            </button>
          </div>
        </div>

        <!-- 高危命令拦截警告条 -->
        <div
          v-if="highRiskBlockedCmd"
          class="bg-rose-950/90 border-b border-rose-600/60 px-4 py-2.5 flex items-center justify-between text-xs"
        >
          <div class="flex items-center gap-2 text-rose-200">
            <AlertTriangle class="w-4 h-4 text-rose-400 shrink-0" />
            <span>
              <strong>高危指令安全拦截：</strong>检测到破坏性命令
              <code class="px-1.5 py-0.5 rounded bg-rose-900 font-mono text-white">{{ highRiskBlockedCmd }}</code>，是否确认继续在生产主机执行？
            </span>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              @click="highRiskBlockedCmd = ''"
              class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 cursor-pointer"
            >
              放弃执行
            </button>
            <button
              type="button"
              @click="forceExecuteHighRisk"
              class="px-2.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white font-semibold cursor-pointer"
            >
              确认强制执行
            </button>
          </div>
        </div>

        <!-- 终端输出内容区 (严格 min-h-0，绝不产生物理重叠溢出) -->
        <div class="flex-1 flex min-h-0 overflow-hidden relative">
          <!-- 主终端 -->
          <RealXtermTerminal
            ref="mainTerminalRef"
            :host-alias="currentHost.id"
            :external-slack="copilotSlack"
            @slack="onTerminalSlack"
            class="flex-1 min-h-0 min-w-0"
          />

          <!-- 分屏终端 #2 -->
          <div
            v-if="splitPaneMode"
            class="w-1/2 border-l border-slate-800 flex flex-col min-h-0 min-w-0"
          >
            <RealXtermTerminal
              ref="secondaryTerminalRef"
              :host-alias="currentHost.id"
              :external-slack="copilotSlack"
              class="flex-1 min-h-0 min-w-0"
            />
          </div>
        </div>

        <!-- Copilot 栏容器：承担终端吸附整行后的非整行余量（上下对称内边距），保证整体贴合且不遮挡输入 -->
        <div
          class="bg-slate-900/95 border-t border-slate-800 shrink-0"
          :style="{ paddingTop: `${copilotSlack / 2}px`, paddingBottom: `${copilotSlack / 2}px` }"
        >
          <!-- 预留的自然语言 AI 生成命令操控栏 (AI Copilot，与终端并列，零重叠遮挡) -->
          <!-- 折叠状态 -->
          <div
            v-if="isAiCopilotCollapsed"
            data-testid="ai-copilot-collapsed-bar"
            class="h-7 px-3 flex items-center justify-between text-xs shrink-0 select-none"
          >
            <button
              type="button"
              @click="isAiCopilotCollapsed = false"
              class="flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 transition text-[11px] cursor-pointer"
            >
              <Bot class="w-3.5 h-3.5" />
              <span class="font-semibold">AI Copilot</span>
              <span class="text-slate-500 text-[10px]">输入自然语言智能推导 Linux 命令 (点击展开)</span>
            </button>

            <button
              type="button"
              @click="isAiCopilotCollapsed = false"
              class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 text-[10px] cursor-pointer border border-slate-700/60"
            >
              <span>展开</span>
              <ChevronUp class="w-3 h-3" />
            </button>
          </div>

          <!-- 展开状态 -->
          <div
            v-else
            data-testid="ai-copilot-expanded-bar"
            class="px-3 py-2 flex flex-col gap-1.5 shrink-0 select-none"
          >
            <!-- AI 生成建议悬浮卡片 (当有推荐指令时展开) -->
            <div
              v-if="aiSuggestion"
              class="p-2.5 rounded-lg bg-gradient-to-r from-cyan-950/90 to-slate-900 border border-cyan-500/40 shadow-sm flex items-center justify-between gap-3 text-xs"
            >
              <div class="flex items-center gap-2.5 min-w-0">
                <div class="w-6 h-6 rounded-md bg-cyan-500/20 text-cyan-400 flex items-center justify-center shrink-0">
                  <Sparkles class="w-3.5 h-3.5" />
                </div>
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] text-cyan-300 font-medium">AI 建议指令：</span>
                    <span class="text-[10px] text-slate-400 truncate">{{ aiSuggestion.explanation }}</span>
                  </div>
                  <div class="font-mono text-xs text-emerald-300 bg-slate-950/80 px-2 py-0.5 rounded mt-0.5 font-semibold truncate select-text">
                    {{ aiSuggestion.command }}
                  </div>
                </div>
              </div>

              <div class="flex items-center gap-1.5 shrink-0">
                <button
                  type="button"
                  @click="applyAiCommand"
                  class="px-3 py-1.5 rounded-md bg-cyan-600 hover:bg-cyan-500 active:bg-cyan-700 text-white font-medium text-xs flex items-center gap-1 cursor-pointer transition shadow"
                >
                  <Play class="w-3 h-3 fill-white" />
                  <span>在终端执行</span>
                </button>
                <button
                  type="button"
                  @click="aiSuggestion = null"
                  class="p-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 cursor-pointer"
                  title="关闭"
                >
                  <X class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            <!-- 自然语言输入框与快捷提示标签 -->
            <div class="flex items-center gap-2">
              <form @submit.prevent="handleGenerateCommand" class="flex-1 flex items-center gap-2">
                <div class="relative flex-1">
                  <div class="absolute left-2.5 top-1/2 -translate-y-1/2 flex items-center gap-1 text-cyan-400 pointer-events-none">
                    <Bot class="w-3.5 h-3.5 text-cyan-400" />
                    <span class="text-[11px] font-semibold tracking-wide">AI Copilot</span>
                  </div>

                  <input
                    v-model="aiPromptInput"
                    type="text"
                    placeholder="输入自然语言需求，AI 为当前服务器生成 Linux 命令（例如：“查找大于100M的日志” 或 “排查占用80端口的进程”)..."
                    class="w-full pl-22 pr-20 py-1.5 rounded-lg bg-slate-950 border border-slate-700/80 focus:border-cyan-500 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500/40 transition font-sans"
                  />

                  <button
                    type="submit"
                    :disabled="isGenerating || !aiPromptInput.trim()"
                    class="absolute right-1.5 top-1/2 -translate-y-1/2 px-2 py-0.5 rounded bg-gradient-to-r from-cyan-600 to-sky-600 hover:from-cyan-500 hover:to-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-[11px] font-medium flex items-center gap-1 transition cursor-pointer"
                  >
                    <Loader2 v-if="isGenerating" class="w-3 h-3 animate-spin" />
                    <Sparkles v-else class="w-3 h-3" />
                    <span>{{ isGenerating ? '生成中' : '生成' }}</span>
                  </button>
                </div>
              </form>

              <button
                type="button"
                @click="isAiCopilotCollapsed = true"
                class="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-200 cursor-pointer shrink-0 transition"
                title="收起 AI Copilot，最大化终端视口"
              >
                <ChevronDown class="w-3.5 h-3.5" />
              </button>
            </div>

            <!-- 快捷自然语言推荐标签 -->
            <div class="flex items-center gap-1.5 overflow-x-auto text-[10px] text-slate-400 py-0.5 no-scrollbar">
              <span class="text-[10px] text-slate-500 shrink-0 font-medium">快捷意图:</span>
              <button
                v-for="chip in quickPromptChips"
                :key="chip"
                type="button"
                @click="setPrompt(chip)"
                class="px-2 py-0.5 rounded-full bg-slate-800/80 hover:bg-slate-800 text-slate-300 hover:text-cyan-300 border border-slate-700/60 hover:border-cyan-500/40 whitespace-nowrap cursor-pointer transition shrink-0"
              >
                {{ chip }}
              </button>
            </div>
          </div>

        </div>
      </div>

      <!-- 右上：常用命令与历史提炼侧边栏 -->
      <div class="w-80 bg-slate-900/70 flex flex-col shrink-0">
        <!-- 自动提炼实时提醒卡 -->
        <div class="p-3 border-b border-slate-800 bg-gradient-to-br from-cyan-950/50 to-slate-900">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-1.5 text-xs font-bold text-cyan-300">
              <Sparkles class="w-4 h-4 text-cyan-400" />
              <span>历史命令提炼 ({{ extractedClusters.length }})</span>
            </div>
            <button
              type="button"
              @click="store.activePage = 'P4_COMMANDS'"
              class="text-[11px] text-cyan-400 hover:underline flex items-center gap-0.5 cursor-pointer"
            >
              <span>全部</span>
              <ArrowUpRight class="w-3 h-3" />
            </button>
          </div>
          <p class="text-[11px] text-slate-400 mt-1">
            系统已从你的 <code>.bash_history</code> 中自动聚类相似命令并提取动态参数：
          </p>

          <div v-if="extractedClusters[0]" class="mt-2 p-2.5 rounded-lg bg-slate-950/90 border border-cyan-500/30 space-y-1.5">
            <div class="flex items-center justify-between text-[11px]">
              <span class="font-semibold text-slate-100">{{ extractedClusters[0].proposedTitle }}</span>
              <span class="text-emerald-400 font-mono">重复 {{ extractedClusters[0].occurrenceCount }} 次</span>
            </div>
            <div class="font-mono text-[11px] text-cyan-300 break-all bg-slate-900 p-1.5 rounded">
              {{ extractedClusters[0].proposedTemplate }}
            </div>
            <button
              type="button"
              @click="promoteClusterToSnippet(extractedClusters[0])"
              class="w-full py-1 rounded bg-cyan-600/30 hover:bg-cyan-600/50 text-cyan-200 border border-cyan-500/40 text-[11px] font-medium flex items-center justify-center gap-1 cursor-pointer transition mt-2"
            >
              <CheckCircle2 class="w-3.5 h-3.5" />
              <span>一键转为常用命令模板</span>
            </button>
          </div>
        </div>

        <!-- 常用命令快捷执行列表 -->
        <div class="flex-1 overflow-y-auto p-3 space-y-2">
          <div class="flex items-center justify-between text-xs font-semibold text-slate-300">
            <span>常用命令库 (点击填参执行)</span>
            <span class="text-[11px] text-slate-500">{{ store.savedSnippets.length }} 条</span>
          </div>

          <div
            v-for="snip in store.savedSnippets"
            :key="snip.id"
            class="p-2.5 rounded-lg bg-slate-950/80 hover:bg-slate-950 border border-slate-800 hover:border-slate-700 space-y-1.5 transition"
          >
            <div class="flex items-center justify-between">
              <span class="text-xs font-medium text-slate-200">{{ snip.title }}</span>
              <button
                type="button"
                @click="triggerSnippetExecution(snip)"
                class="flex items-center gap-1 px-2.5 py-0.5 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-[11px] font-medium cursor-pointer transition"
              >
                <Play class="w-2.5 h-2.5" />
                <span>执行</span>
              </button>
            </div>
            <div class="font-mono text-[11px] text-slate-400 truncate" :title="snip.commandTemplate">
              {{ snip.commandTemplate }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
