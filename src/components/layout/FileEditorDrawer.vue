<script setup lang="ts">
import { computed } from 'vue'
import {
  store,
  executeTerminalCommand,
  saveRemoteFileContent,
  openFileInEditor
} from '@/stores/workbenchStore'
import { FileCode2, Save, ShieldAlert, RefreshCw, X, Loader2, RotateCcw } from 'lucide-vue-next'

const lineCount = computed(() => {
  if (!store.editorDrawer.content) return 0
  return store.editorDrawer.content.split('\n').length
})

const byteSizeFormatted = computed(() => {
  const bytes = new Blob([store.editorDrawer.content || '']).size
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(2)} KB`
})

async function saveFile() {
  await saveRemoteFileContent()
}

async function saveAndReloadService() {
  const ok = await saveRemoteFileContent()
  if (ok && store.editorDrawer.reloadServiceHint) {
    executeTerminalCommand(`sudo systemctl daemon-reload && sudo systemctl restart ${store.editorDrawer.reloadServiceHint}`)
  }
}

function reloadFromRemote() {
  if (store.editorDrawer.filePath) {
    openFileInEditor(store.editorDrawer.filePath, store.editorDrawer.reloadServiceHint)
  }
}
</script>

<template>
  <aside
    v-if="store.editorDrawer.open"
    aria-label="内置代码与配置文件编辑器抽屉"
    class="fixed inset-y-0 right-0 w-[620px] max-w-full bg-slate-900 border-l border-slate-700 shadow-2xl z-40 flex flex-col"
  >
    <!-- 顶部标题栏 -->
    <div class="h-12 px-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
      <div class="flex items-center gap-2 min-w-0">
        <FileCode2 class="w-4 h-4 text-cyan-400 shrink-0" />
        <div class="truncate">
          <div class="text-xs font-semibold text-slate-100 truncate">
            内置远程配置编辑器
          </div>
          <div class="text-[11px] font-mono text-cyan-300 truncate">
            {{ store.editorDrawer.filePath }}
          </div>
        </div>
      </div>

      <div class="flex items-center gap-1.5">
        <button
          type="button"
          @click="reloadFromRemote"
          title="从远端服务器重新拉取文件内容"
          class="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-cyan-300 cursor-pointer flex items-center gap-1 text-[11px]"
        >
          <RotateCcw class="w-3.5 h-3.5" :class="store.editorDrawer.loading ? 'animate-spin' : ''" />
          <span>重新拉取</span>
        </button>
        <button
          type="button"
          @click="store.editorDrawer.open = false"
          aria-label="关闭编辑器抽屉"
          class="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-100 cursor-pointer"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 工具条：sudo 提权写入开关 + 编码与行数统计 -->
    <div class="px-4 py-2 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between text-xs">
      <label class="flex items-center gap-2 text-amber-300 cursor-pointer">
        <input
          v-model="store.editorDrawer.sudoWrite"
          type="checkbox"
          class="rounded border-slate-700"
        />
        <ShieldAlert class="w-3.5 h-3.5" />
        <span>使用 <code>sudo tee</code> 提权写入受保护文件</span>
      </label>

      <span class="text-[11px] font-mono text-slate-400">
        {{ lineCount }} 行 · {{ byteSizeFormatted }} · UTF-8
      </span>
    </div>

    <!-- 代码编辑区 -->
    <div class="flex-1 p-3 bg-slate-950 flex flex-col relative">
      <div
        v-if="store.editorDrawer.loading"
        class="absolute inset-0 bg-slate-950/80 backdrop-blur-xs flex items-center justify-center gap-2 text-xs text-cyan-300 z-10"
      >
        <Loader2 class="w-4 h-4 animate-spin" />
        <span>正在从远端服务器拉取真实文件内容...</span>
      </div>
      <textarea
        v-model="store.editorDrawer.content"
        spellcheck="false"
        aria-label="远程文件内容编辑器"
        @keydown.ctrl.s.prevent="saveFile"
        @keydown.meta.s.prevent="saveFile"
        class="flex-1 w-full bg-slate-950 text-slate-100 font-mono text-xs leading-relaxed p-3 rounded-lg border border-slate-800 focus:border-cyan-500/60 focus:outline-none resize-none"
      />
    </div>

    <!-- 底部操作栏与底层命令透明预览 -->
    <div class="p-3 bg-slate-950 border-t border-slate-800 space-y-2">
      <div class="text-[11px] font-mono text-slate-400 bg-slate-900 px-2.5 py-1.5 rounded border border-slate-800 truncate">
        底层指令:
        <span class="text-cyan-300">
          {{
            store.editorDrawer.sudoWrite
              ? `sudo -n tee ${store.editorDrawer.filePath} > /dev/null`
              : `sftp> put ${store.editorDrawer.filePath}`
          }}
        </span>
      </div>

      <div class="flex items-center justify-end gap-2">
        <button
          type="button"
          @click="store.editorDrawer.open = false"
          class="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 cursor-pointer"
        >
          关闭
        </button>

        <button
          v-if="store.editorDrawer.reloadServiceHint"
          type="button"
          :disabled="store.editorDrawer.saving"
          @click="saveAndReloadService"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-xs font-medium text-white cursor-pointer"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="store.editorDrawer.saving ? 'animate-spin' : ''" />
          <span>保存并重启 {{ store.editorDrawer.reloadServiceHint }}</span>
        </button>

        <button
          type="button"
          :disabled="store.editorDrawer.saving"
          @click="saveFile"
          class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-xs font-medium text-white cursor-pointer"
        >
          <Loader2 v-if="store.editorDrawer.saving" class="w-3.5 h-3.5 animate-spin" />
          <Save v-else class="w-3.5 h-3.5" />
          <span>{{ store.editorDrawer.saving ? '正在写入远端...' : '保存到远端服务器 (⌘S)' }}</span>
        </button>
      </div>
    </div>
  </aside>
</template>
