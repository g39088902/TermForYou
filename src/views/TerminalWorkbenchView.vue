<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  currentHost,
  executeTerminalCommand
} from '@/stores/workbenchStore'
import RealXtermTerminal from '@/components/terminal/RealXtermTerminal.vue'
import {
  Terminal,
  Sparkles,
  Play,
  Columns2,
  AlertTriangle,
  X,
  Loader2,
  Bot,
  ChevronDown,
  ChevronUp,
  KeyRound
} from 'lucide-vue-next'

const DEEPSEEK_API_URL = 'https://api.deepseek.com/chat/completions'
const DEEPSEEK_MODEL = 'deepseek-flash'
const DEEPSEEK_KEY_STORAGE_KEY = 'termforyou_deepseek_api_key'

const DEEPSEEK_SYSTEM_PROMPT = `你是一个专业的 Linux 运维与 Shell 命令专家。请根据用户的自然语言需求，生成准确、可直接执行的 Linux 命令。
必须严格以 JSON 对象格式返回，包含以下两个字段：
- "command": 字符串，生成的单条或多步串联 Linux 命令（不要包含 markdown 代码块标记，不要包含多余换行或注释）
- "explanation": 字符串，简短的中文说明，解释该命令的作用与关键参数

示例输入：查内存最高前5的进程
示例 JSON 输出：{"command": "ps aux --sort=-%mem | head -n 6", "explanation": "按物理内存占用率降序排序并展示前 5 个进程"}`

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

// 自然语言 AI 生成命令状态
const aiPromptInput = ref('')
const isGenerating = ref(false)
const isAiCopilotCollapsed = ref(false)
const copilotError = ref('')
const aiSuggestion = ref<{
  prompt: string
  command: string
  explanation: string
} | null>(null)

// DeepSeek API Key 浏览器本地存储状态
function readStoredDeepseekKey(): string {
  try {
    return localStorage.getItem(DEEPSEEK_KEY_STORAGE_KEY)?.trim() || ''
  } catch {
    return ''
  }
}

const deepseekApiKey = ref(readStoredDeepseekKey())
const isDeepseekKeyConfigured = computed(() => Boolean(deepseekApiKey.value))
const showKeyModal = ref(false)
const deepseekKeyInput = ref('')
const isSavingKey = ref(false)
const keyModalError = ref('')

function openKeyModal() {
  keyModalError.value = ''
  deepseekKeyInput.value = ''
  showKeyModal.value = true
}

function closeKeyModal() {
  if (isSavingKey.value) return
  showKeyModal.value = false
  keyModalError.value = ''
  deepseekKeyInput.value = ''
}

async function saveDeepseekKey() {
  const key = deepseekKeyInput.value.trim()
  if (!key) {
    keyModalError.value = '请输入 DeepSeek API Key'
    return
  }
  isSavingKey.value = true
  keyModalError.value = ''
  try {
    localStorage.setItem(DEEPSEEK_KEY_STORAGE_KEY, key)
    deepseekApiKey.value = key
    showKeyModal.value = false
    deepseekKeyInput.value = ''
    copilotError.value = ''
    if (aiPromptInput.value.trim()) {
      await handleGenerateCommand()
    }
  } catch {
    keyModalError.value = '保存至浏览器本地存储失败，请检查浏览器权限设置'
  } finally {
    isSavingKey.value = false
  }
}

function clearDeepseekKey() {
  try {
    localStorage.removeItem(DEEPSEEK_KEY_STORAGE_KEY)
  } catch {
    // 忽略存储清理异常
  }
  deepseekApiKey.value = ''
  showKeyModal.value = false
  deepseekKeyInput.value = ''
}

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

function extractJsonObject(rawContent: string): { command?: unknown; explanation?: unknown } {
  let text = rawContent.trim()
  if (text.startsWith('```')) {
    text = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
  }
  return JSON.parse(text)
}

/**
 * 浏览器直连 DeepSeek (deepseek-flash, 关闭思考, JSON 格式返回) 生成 Linux 命令
 */
async function handleGenerateCommand() {
  const query = aiPromptInput.value.trim()
  if (!query) return

  const apiKey = deepseekApiKey.value.trim()
  if (!apiKey) {
    openKeyModal()
    return
  }

  isGenerating.value = true
  copilotError.value = ''
  aiSuggestion.value = null

  const contextParts: string[] = []
  if (currentHost.value?.os) {
    contextParts.push(`目标系统: ${currentHost.value.os}`)
  }
  if (currentHost.value?.currentCwd) {
    contextParts.push(`当前目录: ${currentHost.value.currentCwd}`)
  }
  const contextPrefix = contextParts.length > 0 ? `（${contextParts.join('，')}）\n` : ''
  const userMessage = `${contextPrefix}请生成满足以下需求的 Linux 命令并返回 JSON：\n${query}`

  try {
    const res = await fetch(DEEPSEEK_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: DEEPSEEK_MODEL,
        messages: [
          { role: 'system', content: DEEPSEEK_SYSTEM_PROMPT },
          { role: 'user', content: userMessage }
        ],
        response_format: { type: 'json_object' },
        thinking: { type: 'disabled' },
        temperature: 0.2,
        max_tokens: 512
      })
    })

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}))
      const errMsg = errBody?.error?.message || `请求失败 (${res.status})`
      if (res.status === 401 || res.status === 403) {
        throw new Error(`DeepSeek API Key 无效或无权限：${errMsg}`)
      }
      if (res.status === 429) {
        throw new Error(`DeepSeek API 请求过于频繁或额度不足：${errMsg}`)
      }
      throw new Error(`DeepSeek API 调用失败 (${res.status})：${errMsg}`)
    }

    const body = await res.json()
    const content: string = body?.choices?.[0]?.message?.content || ''
    if (!content.trim()) {
      throw new Error('DeepSeek 返回内容为空')
    }

    let parsed: { command?: unknown; explanation?: unknown }
    try {
      parsed = extractJsonObject(content)
    } catch {
      throw new Error('DeepSeek 返回的 JSON 格式无法解析，请重试')
    }

    const command = String(parsed.command ?? '').trim()
    const explanation = String(parsed.explanation ?? '').trim()
    if (!command) {
      throw new Error('DeepSeek 返回的 JSON 中缺少 command 字段')
    }

    aiSuggestion.value = {
      prompt: query,
      command,
      explanation: explanation || '已由 DeepSeek 生成 Linux 命令'
    }
  } catch (err) {
    copilotError.value = err instanceof Error ? err.message : '生成命令失败，请检查网络或 API Key'
  } finally {
    isGenerating.value = false
  }
}

function applyAiCommand() {
  if (!aiSuggestion.value) return
  runCommandInTerminal(aiSuggestion.value.command)
  aiSuggestion.value = null
  aiPromptInput.value = ''
  getActiveTerminal()?.focus()
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

            <!-- AI 错误提示条 -->
            <div
              v-if="copilotError"
              class="px-3 py-1.5 rounded-lg bg-rose-950/80 border border-rose-500/40 flex items-center justify-between gap-2 text-xs text-rose-200"
            >
              <div class="flex items-center gap-2 min-w-0">
                <AlertTriangle class="w-3.5 h-3.5 text-rose-400 shrink-0" />
                <span class="truncate">{{ copilotError }}</span>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  @click="openKeyModal"
                  class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] cursor-pointer"
                >
                  设置 Key
                </button>
                <button
                  type="button"
                  @click="copilotError = ''"
                  class="p-0.5 text-rose-300 hover:text-white cursor-pointer"
                  title="关闭"
                >
                  <X class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            <!-- 自然语言输入框与 DeepSeek Key 设置按钮 -->
            <div class="flex items-center gap-2">
              <button
                v-if="!isDeepseekKeyConfigured"
                type="button"
                @click="openKeyModal"
                class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 text-amber-200 border border-amber-500/40 text-xs font-medium shrink-0 cursor-pointer transition"
              >
                <KeyRound class="w-3.5 h-3.5" />
                <span>设置 DeepSeek Key</span>
              </button>

              <button
                v-else
                type="button"
                @click="openKeyModal"
                class="flex items-center gap-1 px-2 py-1.5 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 text-[11px] shrink-0 cursor-pointer transition"
                title="点击更换或清除 DeepSeek API Key"
              >
                <KeyRound class="w-3 h-3" />
                <span>Key 已设置</span>
              </button>

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
          </div>

        </div>
      </div>
    </div>

    <!-- DeepSeek API Key 设置弹窗 -->
    <div
      v-if="showKeyModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 backdrop-blur-xs p-4"
      @click.self="closeKeyModal"
      @keydown.esc="closeKeyModal"
    >
      <div class="w-full max-w-md rounded-xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 text-slate-100">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-cyan-500/15 text-cyan-400 flex items-center justify-center">
              <KeyRound class="w-4 h-4" />
            </div>
            <div>
              <h3 class="text-sm font-semibold">配置 DeepSeek API Key</h3>
              <p class="text-[11px] text-slate-400">模型：deepseek-flash（关闭思考 · JSON 输出）</p>
            </div>
          </div>
          <button
            type="button"
            @click="closeKeyModal"
            class="p-1 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <form @submit.prevent="saveDeepseekKey" class="space-y-3">
          <div>
            <label class="block text-xs text-slate-300 mb-1.5">DeepSeek API Key</label>
            <input
              v-model="deepseekKeyInput"
              type="password"
              autocomplete="off"
              autofocus
              placeholder="请输入 sk- 开头的 DeepSeek API Key"
              class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 focus:border-cyan-500 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500/40 font-mono"
            />
          </div>

          <p class="text-[11px] text-slate-400 leading-relaxed">
            API Key 仅保存在当前浏览器本地存储（LocalStorage）中，由浏览器直接请求 DeepSeek API，不会发送或保存至后端。
          </p>

          <div v-if="keyModalError" class="text-xs text-rose-300 bg-rose-500/15 border border-rose-500/30 rounded-lg px-3 py-2">
            {{ keyModalError }}
          </div>

          <div class="flex items-center justify-between pt-1">
            <button
              v-if="isDeepseekKeyConfigured"
              type="button"
              :disabled="isSavingKey"
              @click="clearDeepseekKey"
              class="px-3 py-1.5 rounded-lg bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 text-xs cursor-pointer disabled:opacity-50"
            >
              清除 Key
            </button>
            <span v-else />

            <div class="flex items-center gap-2">
              <button
                type="button"
                @click="closeKeyModal"
                class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs cursor-pointer"
              >
                取消
              </button>
              <button
                type="submit"
                :disabled="isSavingKey || !deepseekKeyInput.trim()"
                class="px-3.5 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium flex items-center gap-1.5 cursor-pointer"
              >
                <Loader2 v-if="isSavingKey" class="w-3.5 h-3.5 animate-spin" />
                <span>{{ isSavingKey ? '保存中...' : '保存并使用' }}</span>
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
