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
  CheckCircle2
} from 'lucide-vue-next'

const splitPaneMode = ref(false)
const highRiskBlockedCmd = ref('')

function forceExecuteHighRisk() {
  if (!highRiskBlockedCmd.value) return
  executeTerminalCommand(highRiskBlockedCmd.value)
  highRiskBlockedCmd.value = ''
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

        <!-- 终端输出内容区 -->
        <div class="flex-1 flex min-h-0 overflow-hidden relative">
          <!-- 主终端 -->
          <RealXtermTerminal
            :host-alias="currentHost.id"
            class="flex-1 h-full min-w-0"
          />

          <!-- 分屏终端 #2 -->
          <div
            v-if="splitPaneMode"
            class="w-1/2 border-l border-slate-800 h-full flex flex-col min-w-0"
          >
            <RealXtermTerminal
              :host-alias="currentHost.id"
              class="w-full h-full"
            />
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
            (跟随终端当前目录，点击文件可直接编辑)
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
          <span>切换全屏文件管理</span>
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
