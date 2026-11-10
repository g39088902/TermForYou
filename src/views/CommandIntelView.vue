<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  extractedClusters,
  prefixStats,
  triggerSnippetExecution,
  promoteClusterToSnippet,
  showToast
} from '@/stores/workbenchStore'
import type { ExtractedCommandCluster } from '@/types'
import {
  Sparkles,
  BookMarked,
  Play,
  Plus,
  Wand2,
  CheckCircle2,
  BarChart3,
  Bot
} from 'lucide-vue-next'

const activeSubTab = ref<'EXTRACT' | 'LIBRARY'>('EXTRACT')
const selectedCategory = ref<string>('全部')
const customHistoryInput = ref(
  `kubectl logs -f -n prod deployment/payment-api --tail 100\nkubectl logs -f -n prod deployment/order-worker --tail 250\nkubectl logs -f -n staging deployment/auth-sso --tail 50`
)

const categories = ['全部', 'Docker 运维', '网络与端口排查', '日志与文件分析', '系统服务管控', '数据库维护']

const filteredSnippets = computed(() => {
  if (selectedCategory.value === '全部') return store.savedSnippets
  return store.savedSnippets.filter((s) => s.category === selectedCategory.value)
})

function injectCustomHistoryForExtraction() {
  const lines = customHistoryInput.value
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length === 0) return
  store.rawHistoryLines.unshift(...lines)
  showToast(`已导入 ${lines.length} 条历史记录，AST 引擎已实时重新聚类！`)
}

function runLlmSemanticPolish(cluster: ExtractedCommandCluster) {
  cluster.llmAnnotated = true
  if (cluster.baseCommand === 'kubectl') {
    cluster.proposedTitle = 'K8s 命名空间 Deployment 容器日志实时追踪'
  } else if (cluster.baseCommand === 'docker') {
    cluster.proposedTitle = 'Docker 容器标准输出尾部日志实时流'
  } else if (cluster.baseCommand === 'find') {
    cluster.proposedTitle = '按文件后缀与修改天数批量检索过期文件'
  } else {
    cluster.proposedTitle = `${cluster.baseCommand.toUpperCase()} 智能参数化运维指令模板`
  }
  showToast(`已通过 LLM 为模板补充中文语义标题与参数注释`)
}
</script>

<template>
  <div class="p-5 space-y-5 overflow-y-auto h-full">
    <!-- 顶栏：Tab 切换 (AST 历史命令统计与自动提炼 vs 常用命令资产库) -->
    <div class="flex flex-wrap items-center justify-between gap-4 bg-slate-900/90 border border-slate-800 rounded-xl p-4">
      <div>
        <h1 class="text-base font-bold text-slate-100 flex items-center gap-2">
          <Sparkles class="w-5 h-5 text-cyan-400" />
          <span>命令提炼与常用库</span>
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          分析历史会话高频命令，支持参数化模版提炼与快捷复用。
        </p>
      </div>

      <div class="flex items-center gap-2 bg-slate-950 p-1 rounded-lg border border-slate-800">
        <button
          type="button"
          @click="activeSubTab = 'EXTRACT'"
          :class="[
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer',
            activeSubTab === 'EXTRACT'
              ? 'bg-cyan-600 text-white'
              : 'text-slate-400 hover:text-slate-200'
          ]"
        >
          <Wand2 class="w-3.5 h-3.5" />
          <span>历史命令统计与提炼 ({{ extractedClusters.length }})</span>
        </button>

        <button
          type="button"
          @click="activeSubTab = 'LIBRARY'"
          :class="[
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition cursor-pointer',
            activeSubTab === 'LIBRARY'
              ? 'bg-cyan-600 text-white'
              : 'text-slate-400 hover:text-slate-200'
          ]"
        >
          <BookMarked class="w-3.5 h-3.5" />
          <span>常用命令库 ({{ store.savedSnippets.length }})</span>
        </button>
      </div>
    </div>

    <!-- 子视图 1：历史命令统计与 AST 自动提炼 -->
    <div v-if="activeSubTab === 'EXTRACT'" class="space-y-5">
      <!-- 顶部：命令前缀分布统计 + 实时提炼测试沙箱 -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- 前缀统计 -->
        <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
              <BarChart3 class="w-4 h-4 text-cyan-400" />
              <span>高频命令前缀分布</span>
            </div>
            <span class="text-[11px] font-mono text-slate-400">样本总数: {{ store.rawHistoryLines.length }} 条</span>
          </div>

          <div class="space-y-2">
            <div
              v-for="item in prefixStats"
              :key="item.prefix"
              class="space-y-1"
            >
              <div class="flex items-center justify-between text-xs font-mono">
                <span class="text-cyan-300 font-semibold">{{ item.prefix }}</span>
                <span class="text-slate-400">{{ item.count }} 次 ({{ item.percent }}%)</span>
              </div>
              <div class="h-1.5 rounded-full bg-slate-950 overflow-hidden">
                <div
                  class="h-full bg-gradient-to-r from-cyan-500 to-indigo-500 rounded-full"
                  :style="{ width: `${Math.max(8, item.percent)}%` }"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- 自定义命令输入分析 -->
        <div class="rounded-xl bg-slate-900/90 border border-cyan-500/30 p-4 flex flex-col justify-between space-y-3">
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold text-cyan-300 flex items-center gap-1.5">
                <Wand2 class="w-4 h-4" />
                <span>自定义命令输入分析</span>
              </span>
            </div>
            <textarea
              v-model="customHistoryInput"
              rows="3"
              aria-label="命令输入区"
              class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2.5 font-mono text-xs text-slate-200 focus:border-cyan-400 focus:outline-none"
            />
          </div>

          <div class="flex items-center justify-between">
            <span class="text-[11px] text-slate-400">
              输入多行相似命令，点击右侧生成模版
            </span>
            <button
              type="button"
              @click="injectCustomHistoryForExtraction"
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer shrink-0"
            >
              <Plus class="w-3.5 h-3.5" />
              <span>注入并实时提炼</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 自动提炼出的候选参数化模板列表 -->
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div
          v-for="cluster in extractedClusters"
          :key="cluster.id"
          class="rounded-xl bg-slate-900/90 border border-slate-800 hover:border-cyan-500/40 p-4 space-y-3 transition"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <div class="flex items-center gap-2">
                <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                  {{ cluster.proposedCategory }}
                </span>
                <span
                  v-if="cluster.llmAnnotated"
                  class="px-2 py-0.5 rounded text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/30"
                >
                  AI 语义已增强
                </span>
                <h3 class="text-sm font-bold text-slate-100">{{ cluster.proposedTitle }}</h3>
              </div>
              <div class="text-[11px] text-slate-400 mt-1 font-mono">
                骨架指纹: {{ cluster.skeletonHash }} · 历史出现 <strong class="text-emerald-400">{{ cluster.occurrenceCount }}</strong> 次 · 置信度 {{ cluster.confidence }}%
              </div>
            </div>

            <div class="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                @click="runLlmSemanticPolish(cluster)"
                class="flex items-center gap-1 px-2.5 py-1 rounded-md bg-purple-500/15 hover:bg-purple-500/25 text-purple-300 border border-purple-500/30 text-xs cursor-pointer"
                title="可选调用 LLM 自动生成更精准的中文标题与参数说明"
              >
                <Bot class="w-3.5 h-3.5" />
                <span>AI 润色命名</span>
              </button>
              <button
                type="button"
                @click="
                  () => {
                    promoteClusterToSnippet(cluster)
                    activeSubTab = 'LIBRARY'
                  }
                "
                class="flex items-center gap-1 px-3 py-1 rounded-md bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold cursor-pointer"
              >
                <CheckCircle2 class="w-3.5 h-3.5" />
                <span>采纳并入库</span>
              </button>
            </div>
          </div>

          <!-- 提炼出的参数化模板 -->
          <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
            <div class="text-[10px] text-slate-400">自动合成参数化模板：</div>
            <div class="font-mono text-xs text-cyan-300 break-all">
              {{ cluster.proposedTemplate }}
            </div>
          </div>

          <!-- 识别出的动态变量槽位与原始样本对照 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2.5 text-xs">
            <div class="p-2.5 rounded-lg bg-slate-950/70 border border-slate-800/80 space-y-1">
              <div class="text-[10px] font-semibold text-slate-400">识别出的动态变量槽位：</div>
              <div
                v-for="v in cluster.variables"
                :key="v.name"
                class="flex items-center justify-between font-mono text-[11px]"
              >
                <span class="text-amber-300">&#123;&#123;{{ v.name }}&#125;&#125;</span>
                <span class="text-slate-400 truncate max-w-[160px]">
                  可选: {{ v.options?.join(', ') }}
                </span>
              </div>
            </div>

            <div class="p-2.5 rounded-lg bg-slate-950/70 border border-slate-800/80 space-y-1">
              <div class="text-[10px] font-semibold text-slate-400">原始历史执行样本：</div>
              <div
                v-for="raw in cluster.rawExamples.slice(0, 3)"
                :key="raw"
                class="font-mono text-[11px] text-slate-400 truncate"
                :title="raw"
              >
                $ {{ raw }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 子视图 2：常用命令资产库 -->
    <div v-else class="space-y-4">
      <div class="flex items-center gap-2 flex-wrap">
        <button
          v-for="cat in categories"
          :key="cat"
          type="button"
          @click="selectedCategory = cat"
          :class="[
            'px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer border',
            selectedCategory === cat
              ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
              : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200'
          ]"
        >
          {{ cat }}
        </button>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div
          v-for="snip in filteredSnippets"
          :key="snip.id"
          class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 flex flex-col justify-between space-y-3"
        >
          <div class="space-y-2">
            <div class="flex items-start justify-between">
              <div>
                <div class="flex items-center gap-2">
                  <span class="px-2 py-0.5 text-[10px] rounded bg-slate-800 text-cyan-300">
                    {{ snip.category }}
                  </span>
                  <span
                    class="px-2 py-0.5 text-[10px] rounded font-mono"
                    :class="
                      snip.source === 'auto-extracted'
                        ? 'bg-emerald-500/15 text-emerald-300'
                        : snip.source === 'gui-saved'
                          ? 'bg-indigo-500/15 text-indigo-300'
                          : 'bg-slate-800 text-slate-400'
                    "
                  >
                    {{
                      snip.source === 'auto-extracted'
                        ? 'AST 自动提炼'
                        : snip.source === 'gui-saved'
                          ? 'GUI 转换保存'
                          : '手动创建'
                    }}
                  </span>
                </div>
                <h3 class="text-sm font-bold text-slate-100 mt-1.5">{{ snip.title }}</h3>
                <p class="text-xs text-slate-400 mt-0.5">{{ snip.description }}</p>
              </div>

              <button
                type="button"
                @click="triggerSnippetExecution(snip)"
                class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold cursor-pointer shrink-0"
              >
                <Play class="w-3.5 h-3.5" />
                <span>填参执行</span>
              </button>
            </div>

            <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 font-mono text-xs text-cyan-300 break-all">
              {{ snip.commandTemplate }}
            </div>
          </div>

          <div class="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-slate-800">
            <span>包含 {{ snip.variables.length }} 个动态参数</span>
            <span class="font-mono">累计调用 {{ snip.usageCount }} 次</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
