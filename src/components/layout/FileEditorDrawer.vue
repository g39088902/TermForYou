<script setup lang="ts">
import { store, executeTerminalCommand, showToast } from '@/stores/workbenchStore'
import { FileCode2, Save, ShieldAlert, RefreshCw, X } from 'lucide-vue-next'

function saveFile() {
  const existing = store.files.find((f) => f.path === store.editorDrawer.filePath)
  if (existing) {
    existing.content = store.editorDrawer.content
    existing.modifiedAt = '刚刚'
  } else {
    store.files.unshift({
      name: store.editorDrawer.filePath.split('/').pop() || 'config',
      path: store.editorDrawer.filePath,
      isDir: false,
      sizeBytes: store.editorDrawer.content.length,
      permissions: '-rw-r--r--',
      octal: '0644',
      owner: 'root',
      group: 'root',
      modifiedAt: '刚刚',
      content: store.editorDrawer.content
    })
  }
  const cmd = store.editorDrawer.sudoWrite
    ? `sudo tee ${store.editorDrawer.filePath} < /tmp/tfy_upload.tmp > /dev/null`
    : `sftp put ${store.editorDrawer.filePath}`
  showToast(`文件已保存 (${cmd})`)
}

function saveAndReloadService() {
  saveFile()
  if (store.editorDrawer.reloadServiceHint) {
    executeTerminalCommand(`sudo systemctl daemon-reload && sudo systemctl restart ${store.editorDrawer.reloadServiceHint}`)
  }
}
</script>

<template>
  <aside
    v-if="store.editorDrawer.open"
    aria-label="内置代码与配置文件编辑器抽屉"
    class="fixed inset-y-0 right-0 w-[560px] max-w-full bg-slate-900 border-l border-slate-700 shadow-2xl z-40 flex flex-col"
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

      <button
        type="button"
        @click="store.editorDrawer.open = false"
        aria-label="关闭编辑器抽屉"
        class="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-100 cursor-pointer"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- 工具条：sudo 提权写入开关 + 编码 -->
    <div class="px-4 py-2 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between text-xs">
      <label class="flex items-center gap-2 text-amber-300 cursor-pointer">
        <input
          v-model="store.editorDrawer.sudoWrite"
          type="checkbox"
          class="rounded border-slate-700"
        />
        <ShieldAlert class="w-3.5 h-3.5" />
        <span>使用 <code>sudo tee</code> 提权写入系统受保护文件</span>
      </label>

      <span class="text-[11px] font-mono text-slate-400">UTF-8 · LF · Monaco Engine</span>
    </div>

    <!-- 代码编辑区 -->
    <div class="flex-1 p-3 bg-slate-950 flex flex-col">
      <textarea
        v-model="store.editorDrawer.content"
        spellcheck="false"
        aria-label="远程文件内容编辑器"
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
              ? `cat << 'EOF' | sudo tee ${store.editorDrawer.filePath}`
              : `sftp> put -P ${store.editorDrawer.filePath}`
          }}
        </span>
      </div>

      <div class="flex items-center justify-end gap-2">
        <button
          type="button"
          @click="store.editorDrawer.open = false"
          class="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 cursor-pointer"
        >
          取消
        </button>

        <button
          v-if="store.editorDrawer.reloadServiceHint"
          type="button"
          @click="saveAndReloadService"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-xs font-medium text-white cursor-pointer"
        >
          <RefreshCw class="w-3.5 h-3.5" />
          <span>保存并重启 {{ store.editorDrawer.reloadServiceHint }}</span>
        </button>

        <button
          type="button"
          @click="saveFile"
          class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-cyan-600 hover:bg-cyan-500 text-xs font-medium text-white cursor-pointer"
        >
          <Save class="w-3.5 h-3.5" />
          <span>保存到远端服务器</span>
        </button>
      </div>
    </div>
  </aside>
</template>
