<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  currentHost,
  extractedClusters,
  executeTerminalCommand,
  triggerSnippetExecution,
  promoteClusterToSnippet,
  openFileInEditor,
  navigateWithContext
} from '@/stores/workbenchStore'
import RealXtermTerminal from '@/components/terminal/RealXtermTerminal.vue'
import {
  Terminal,
  Sparkles,
  Play,
  FolderOpen,
  FileCode2,
  Columns2,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Send,
  Radio
} from 'lucide-vue-next'

const useRealXterm = ref(true)
const cmdInput = ref('')
const splitPaneMode = ref(false)
const highRiskBlockedCmd = ref('')

const HIGH_RISK_PATTERNS = [/rm\s+-rf\s+\//, /mkfs/, /iptables\s+-F/, /dd\s+if=/]

// 幽灵文本内联自动补全提示
const ghostSuggestion = computed(() => {
  const val = cmdInput.value.trim()
  if (!val || val.length < 2) return ''
  const matchFromHistory = store.rawHistoryLines.find(
    (line) => line.startsWith(val) && line !== val
  )
  return matchFromHistory ?? ''
})

function acceptGhostSuggestion() {
  if (ghostSuggestion.value) {
    cmdInput.value = ghostSuggestion.value
  }
}

function submitCommand() {
  const raw = cmdInput.value.trim()
  if (!raw) return

  if (HIGH_RISK_PATTERNS.some((reg) => reg.test(raw))) {
    highRiskBlockedCmd.value = raw
    return
  }

  executeTerminalCommand(raw)
  cmdInput.value = ''
}

function forceExecuteHighRisk() {
  if (!highRiskBlockedCmd.value) return
  executeTerminalCommand(highRiskBlockedCmd.value)
  highRiskBlockedCmd.value = ''
  cmdInput.value = ''
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- 上半区：左终端 + 右智能命令侧边栏 -->
    <div class="flex-1 flex min-h-0 overflow-hidden">
      <!-- 左上：多标签/分屏 SSH 终端主舞台 -->
      <div class="flex-1 flex flex-col bg-slate-950 border-r border-slate-800 min-w-0">
        <!-- 终端工具栏 -->
        <div class="h-9 px-3 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between text-xs shrink-0">
          <div class="flex items-center gap-2">
            <Terminal class="w-3.5 h-3.5 text-cyan-400" />
            <span class="font-semibold text-slate-100">SSH 交互终端 ({{ currentHost.name }})</span>
            <span class="px-1.5 py-0.5 rounded bg-slate-800 text-amber-300 font-mono text-[11px]">
              {{ currentHost.ip }}:{{ currentHost.port }}
            </span>
            <span
              v-if="useRealXterm"
              class="flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 font-mono text-[10px] border border-emerald-500/30"
            >
              <Radio class="w-3 h-3 text-emerald-400 animate-pulse" />
              <span>xterm.js + Python 直连</span>
            </span>
          </div>

          <div class="flex items-center gap-2">
            <button
              type="button"
              @click="useRealXterm = !useRealXterm"
              :class="[
                'px-2 py-0.5 rounded text-[11px] border cursor-pointer transition',
                useRealXterm
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                  : 'bg-slate-800 text-slate-400 border-slate-700'
              ]"
            >
              {{ useRealXterm ? '切换回 Mock 演示模式' : '启用真实 xterm 直连' }}
            </button>
            <button
              type="button"
              @click="cmdInput = 'rm -rf /var/log/nginx/*'"
              class="px-2 py-0.5 rounded bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 text-[11px] cursor-pointer"
              title="点击演示高危命令二次确认拦截器"
            >
              测试高危命令拦截
            </button>
            <button
              type="button"
              @click="splitPaneMode = !splitPaneMode"
              :class="[
                'flex items-center gap-1 px-2 py-0.5 rounded text-[11px] border cursor-pointer',
                splitPaneMode
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                  : 'bg-slate-800 text-slate-300 border-slate-700'
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

        <!-- 终端输出内容区：真实 xterm 直连 或 Mock 演示 -->
        <div class="flex-1 flex min-h-0 overflow-hidden relative">
          <!-- 真实 xterm 直连组件 -->
          <RealXtermTerminal
            v-if="useRealXterm"
            :host-alias="currentHost.id"
            class="w-full h-full"
          />

          <!-- 原有 Mock 演示列表 -->
          <div v-else class="flex-1 flex flex-col min-h-0 overflow-hidden">
            <div class="flex-1 flex min-h-0 overflow-hidden">
              <div class="flex-1 overflow-y-auto p-3.5 font-mono text-xs space-y-3">
                <div class="text-slate-500 text-[11px]">
                  Welcome to {{ currentHost.os }} ({{ currentHost.kernel }}) — Mock 演示终端.
                </div>

                <div
                  v-for="entry in store.terminalHistory"
                  :key="entry.id"
                  class="rounded-lg bg-slate-900/60 border border-slate-800/80 p-2.5 space-y-1.5"
                >
                  <div class="flex items-center justify-between text-[11px]">
                    <div class="flex items-center gap-1.5">
                      <span class="text-emerald-400 font-semibold">{{ currentHost.user }}@{{ currentHost.name }}</span>
                      <span class="text-slate-500">:</span>
                      <span class="text-amber-300">{{ entry.cwd }}</span>
                      <span class="text-slate-400">#</span>
                      <span class="text-slate-100 font-bold ml-1">{{ entry.command }}</span>
                    </div>
                    <div class="flex items-center gap-2 text-slate-500">
                      <span class="text-emerald-400">Exit {{ entry.exitCode }}</span>
                      <span>{{ entry.durationMs }}ms</span>
                      <span>{{ entry.timestamp }}</span>
                    </div>
                  </div>
                  <pre class="text-slate-300 whitespace-pre-wrap text-[11px] leading-relaxed pl-2 border-l-2 border-slate-700">{{ entry.output }}</pre>
                </div>
              </div>

              <!-- 分屏终端 #2 -->
              <div
                v-if="splitPaneMode"
                class="w-1/2 border-l border-slate-800 bg-slate-950 p-3.5 font-mono text-xs flex flex-col justify-between"
              >
                <div class="space-y-2">
                  <div class="text-[11px] text-cyan-400 font-semibold flex items-center justify-between border-b border-slate-800 pb-1.5">
                    <span>SSH 分屏终端 #2 (实时监控视图)</span>
                    <span class="text-slate-500">广播同步已就绪</span>
                  </div>
                  <pre class="text-[11px] text-slate-300 leading-relaxed">
$ watch -n 2 "ss -s && free -h"
Total: 418 (kernel 912)
TCP:   94 (estab 62, closed 18, orphaned 0, timewait 18)

               total        used        free      shared  buff/cache   available
Mem:           15Gi       9.4Gi       1.2Gi       142Mi       5.1Gi       5.9Gi
Swap:         4.0Gi       410Mi       3.6Gi</pre>
                </div>
                <div class="text-[11px] text-slate-500">
                  提示：开启广播模式后，主输入框指令将同时发送至两个分屏终端。
                </div>
              </div>
            </div>

            <!-- 终端底部输入框（仅 Mock 演示模式使用） -->
            <form
              @submit.prevent="submitCommand"
              class="h-11 bg-slate-900 border-t border-slate-800 px-3 flex items-center gap-2 relative shrink-0"
            >
              <span class="font-mono text-xs text-emerald-400 shrink-0">
                {{ currentHost.user }}@{{ currentHost.name }}:{{ currentHost.currentCwd }}#
              </span>

              <div class="relative flex-1 flex items-center">
                <input
                  v-model="cmdInput"
                  @keydown.tab.prevent="acceptGhostSuggestion"
                  type="text"
                  placeholder="输入命令 (如 cd /var/log 或 docker logs...)，按 Tab 采纳历史补全"
                  class="w-full bg-transparent font-mono text-xs text-slate-100 focus:outline-none z-10"
                />
                <span
                  v-if="ghostSuggestion"
                  class="absolute left-0 font-mono text-xs text-slate-600 pointer-events-none select-none"
                >
                  {{ ghostSuggestion }}
                  <span class="ml-2 px-1 py-0.5 text-[10px] rounded bg-slate-800 text-cyan-400">Tab 补全</span>
                </span>
              </div>

              <button
                type="submit"
                class="flex items-center gap-1 px-3 py-1.5 rounded-md bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium cursor-pointer"
              >
                <Send class="w-3.5 h-3.5" />
                <span>发送</span>
              </button>
            </form>
          </div>
        </div>
      </div>

      <!-- 右上：常用命令与 AST 历史自动提炼侧边栏 -->
      <div class="w-80 bg-slate-900/70 flex flex-col shrink-0">
        <!-- 自动提炼实时提醒卡 -->
        <div class="p-3 border-b border-slate-800 bg-gradient-to-br from-cyan-950/50 to-slate-900">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-1.5 text-xs font-bold text-cyan-300">
              <Sparkles class="w-4 h-4 text-cyan-400" />
              <span>AST 历史命令自动提炼 ({{ extractedClusters.length }})</span>
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
              class="w-full py-1 rounded bg-cyan-600/30 hover:bg-cyan-600/50 text-cyan-200 border border-cyan-500/40 text-[11px] font-medium flex items-center justify-center gap-1 cursor-pointer"
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
                class="flex items-center gap-1 px-2 py-0.5 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-[11px] font-medium cursor-pointer"
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

    <!-- 下半区：Follow-CWD 联动紧凑型文件管理面板 -->
    <div class="h-48 bg-slate-900/95 border-t border-slate-800 flex flex-col shrink-0">
      <div class="h-8 px-3 bg-slate-950 border-b border-slate-800 flex items-center justify-between text-xs">
        <div class="flex items-center gap-2">
          <FolderOpen class="w-3.5 h-3.5 text-amber-400" />
          <span class="font-semibold text-slate-200">CWD 同步文件工作区：</span>
          <span class="font-mono text-amber-300">{{ currentHost.currentCwd }}</span>
          <span class="text-[11px] text-slate-500">
            (在上方终端执行 <code>cd /path</code> 自动刷新此目录，点击文件直接呼出内置编辑器)
          </span>
        </div>

        <button
          type="button"
          @click="
            navigateWithContext({
              sourcePage: 'P1_WORKBENCH',
              targetPage: 'P3_FILES',
              reason: '从终端工作台展开全屏文件管理器',
              openPath: currentHost.currentCwd
            })
          "
          class="text-[11px] text-cyan-400 hover:underline flex items-center gap-1 cursor-pointer"
        >
          <span>切换全屏文件管理 (P3)</span>
          <ArrowUpRight class="w-3 h-3" />
        </button>
      </div>

      <div tabindex="0" role="region" aria-label="当前终端工作目录文件列表" class="table-wrapper flex-1">
        <table class="text-left text-xs" style="--label-2: '权限'; --label-3: '大小'; --label-4: '操作'">
          <thead class="bg-slate-900 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-1.5 px-3">文件名 / 路径</th>
              <th class="py-1.5 px-3">权限 (Octal)</th>
              <th class="py-1.5 px-3">大小</th>
              <th class="py-1.5 px-3">最后修改</th>
              <th class="py-1.5 px-3 text-right">快捷操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60">
            <tr
              v-for="file in store.files"
              :key="file.path"
              class="hover:bg-slate-800/50 transition"
            >
              <th class="py-1.5 px-3 font-mono font-medium text-slate-200 flex items-center gap-2">
                <FolderOpen v-if="file.isDir" class="w-3.5 h-3.5 text-amber-400 shrink-0" />
                <FileCode2 v-else class="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <span>{{ file.path }}</span>
              </th>
              <td class="py-1.5 px-3 font-mono text-slate-400">
                {{ file.permissions }} <span class="text-slate-500">({{ file.octal }})</span>
              </td>
              <td class="py-1.5 px-3 font-mono text-slate-400">
                {{ (file.sizeBytes / 1024).toFixed(1) }} KB
              </td>
              <td class="py-1.5 px-3 text-slate-400">{{ file.modifiedAt }}</td>
              <td class="py-1.5 px-3 text-right">
                <button
                  v-if="!file.isDir"
                  type="button"
                  @click="openFileInEditor(file.path)"
                  class="px-2 py-0.5 rounded bg-cyan-500/15 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/30 text-[11px] cursor-pointer"
                >
                  内置编辑器打开
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
