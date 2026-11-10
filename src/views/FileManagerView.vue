<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  store,
  currentHost,
  openFileInEditor,
  executeTerminalCommand,
  showToast
} from '@/stores/workbenchStore'
import type { FileEntry } from '@/types'
import {
  FolderOpen,
  FileCode2,
  Bookmark,
  Shield,
  Terminal,
  Upload,
  Archive,
  PieChart
} from 'lucide-vue-next'

const bookmarks = [
  { label: 'Nginx 配置目录', path: '/etc/nginx' },
  { label: 'Systemd 单元目录', path: '/etc/systemd/system' },
  { label: 'Docker 编排目录', path: '/opt/stacks/gateway' },
  { label: '系统日志目录', path: '/var/log' },
  { label: '运维脚本目录', path: '/opt/scripts' }
]

const selectedFileForChmod = ref<FileEntry | null>(store.files[0])
const chmodMatrix = ref({
  ownerR: true,
  ownerW: true,
  ownerX: false,
  groupR: true,
  groupW: false,
  groupX: false,
  otherR: true,
  otherW: false,
  otherX: false,
  recursive: false
})

const computedOctal = computed(() => {
  const m = chmodMatrix.value
  const o = (m.ownerR ? 4 : 0) + (m.ownerW ? 2 : 0) + (m.ownerX ? 1 : 0)
  const g = (m.groupR ? 4 : 0) + (m.groupW ? 2 : 0) + (m.groupX ? 1 : 0)
  const t = (m.otherR ? 4 : 0) + (m.otherW ? 2 : 0) + (m.otherX ? 1 : 0)
  return `0${o}${g}${t}`
})

const computedSymbolic = computed(() => {
  const m = chmodMatrix.value
  const bit = (r: boolean, w: boolean, x: boolean) => `${r ? 'r' : '-'}${w ? 'w' : '-'}${x ? 'x' : '-'}`
  return `-${bit(m.ownerR, m.ownerW, m.ownerX)}${bit(m.groupR, m.groupW, m.groupX)}${bit(m.otherR, m.otherW, m.otherX)}`
})

function applyChmod() {
  if (!selectedFileForChmod.value) return
  const flag = chmodMatrix.value.recursive ? '-R ' : ''
  const cmd = `sudo chmod ${flag}${computedOctal.value.slice(1)} ${selectedFileForChmod.value.path}`
  selectedFileForChmod.value.octal = computedOctal.value
  selectedFileForChmod.value.permissions = computedSymbolic.value
  executeTerminalCommand(cmd)
}

function jumpToDir(path: string) {
  currentHost.value.currentCwd = path
  showToast(`已切换工作目录至 ${path}`)
}
</script>

<template>
  <div class="p-5 h-full flex gap-4 overflow-hidden">
    <!-- 左侧：收藏书签 + 磁盘空间 ncdu 概览 -->
    <div class="w-64 bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between shrink-0">
      <div class="space-y-3">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
          <Bookmark class="w-4 h-4 text-amber-400" />
          <span>高频服务器目录书签</span>
        </div>

        <div class="space-y-1">
          <button
            v-for="bm in bookmarks"
            :key="bm.path"
            type="button"
            @click="jumpToDir(bm.path)"
            :class="[
              'w-full text-left px-2.5 py-2 rounded-lg text-xs transition cursor-pointer flex flex-col',
              currentHost.currentCwd === bm.path
                ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/40'
                : 'hover:bg-slate-800 text-slate-300'
            ]"
          >
            <span class="font-medium">{{ bm.label }}</span>
            <span class="font-mono text-[10px] text-slate-400 mt-0.5">{{ bm.path }}</span>
          </button>
        </div>
      </div>

      <!-- 目录体积分析 (类 ncdu 可视化) -->
      <div class="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-2">
        <div class="flex items-center justify-between text-xs font-semibold text-slate-100">
          <div class="flex items-center gap-1.5">
            <PieChart class="w-3.5 h-3.5 text-indigo-400" />
            <span>目录体积分布 (ncdu)</span>
          </div>
          <span class="font-mono text-[11px] text-indigo-300">24.8 GB</span>
        </div>
        <div class="space-y-1.5 text-[11px]">
          <div>
            <div class="flex justify-between font-mono text-slate-300">
              <span>/var/lib/docker</span>
              <span>16.4 GB (66%)</span>
            </div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden mt-0.5">
              <div class="bg-indigo-500 h-full w-2/3" />
            </div>
          </div>
          <div>
            <div class="flex justify-between font-mono text-slate-300">
              <span>/var/log/nginx</span>
              <span>5.2 GB (21%)</span>
            </div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden mt-0.5">
              <div class="bg-cyan-500 h-full w-1/5" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 中间：SFTP 文件列表与工具栏 -->
    <div class="flex-1 bg-slate-900/90 border border-slate-800 rounded-xl flex flex-col overflow-hidden min-w-0">
      <div class="p-3.5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2 text-xs">
          <FolderOpen class="w-4 h-4 text-amber-400" />
          <span class="text-slate-400">当前路径:</span>
          <span class="px-2.5 py-1 rounded bg-slate-950 border border-slate-800 font-mono text-amber-300">
            {{ currentHost.currentCwd }}
          </span>
          <button
            type="button"
            @click="
              () => {
                executeTerminalCommand(`cd ${currentHost.currentCwd}`, true)
              }
            "
            class="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 text-xs cursor-pointer"
          >
            <Terminal class="w-3.5 h-3.5" />
            <span>在终端打开此目录</span>
          </button>
        </div>

        <div class="flex items-center gap-2">
          <button
            type="button"
            @click="showToast('已打开 SFTP 断点续传上传队列')"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
          >
            <Upload class="w-3.5 h-3.5 text-cyan-400" />
            <span>SFTP 上传</span>
          </button>
          <button
            type="button"
            @click="executeTerminalCommand(`tar -czvf backup_${Date.now()}.tar.gz ${currentHost.currentCwd}`)"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
          >
            <Archive class="w-3.5 h-3.5 text-amber-400" />
            <span>一键打包 .tar.gz</span>
          </button>
        </div>
      </div>

      <div tabindex="0" role="region" aria-label="远程服务器文件列表" class="table-wrapper flex-1">
        <table class="text-left text-xs" style="--label-2: '权限'; --label-3: '所有者'; --label-4: '操作'">
          <thead class="bg-slate-950 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">文件名 / 完整路径</th>
              <th class="py-2.5 px-3">权限 (Octal)</th>
              <th class="py-2.5 px-3">所有者</th>
              <th class="py-2.5 px-3">大小</th>
              <th class="py-2.5 px-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/70">
            <tr
              v-for="file in store.files"
              :key="file.path"
              @click="selectedFileForChmod = file"
              :class="[
                'hover:bg-slate-800/60 transition cursor-pointer',
                selectedFileForChmod?.path === file.path ? 'bg-cyan-500/10' : ''
              ]"
            >
              <th class="py-2.5 px-3 font-mono font-medium text-slate-100 flex items-center gap-2">
                <FolderOpen v-if="file.isDir" class="w-4 h-4 text-amber-400 shrink-0" />
                <FileCode2 v-else class="w-4 h-4 text-cyan-400 shrink-0" />
                <div>
                  <div>{{ file.name }}</div>
                  <div class="text-[10px] text-slate-400">{{ file.path }}</div>
                </div>
              </th>
              <td class="py-2.5 px-3 font-mono">
                <span class="text-emerald-300">{{ file.permissions }}</span>
                <span class="text-slate-500 ml-1">({{ file.octal }})</span>
              </td>
              <td class="py-2.5 px-3 font-mono text-slate-300">{{ file.owner }}:{{ file.group }}</td>
              <td class="py-2.5 px-3 font-mono text-slate-400">{{ (file.sizeBytes / 1024).toFixed(2) }} KB</td>
              <td class="py-2.5 px-3 text-right">
                <button
                  v-if="!file.isDir"
                  type="button"
                  @click.stop="openFileInEditor(file.path)"
                  class="px-2.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-[11px] font-medium cursor-pointer"
                >
                  编辑内容
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 右侧：九宫格可视化 Chmod / Chown 权限计算器 -->
    <div class="w-72 bg-slate-900/90 border border-slate-800 rounded-xl p-4 flex flex-col justify-between shrink-0">
      <div class="space-y-4">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100 border-b border-slate-800 pb-2.5">
          <Shield class="w-4 h-4 text-cyan-400" />
          <span>可视化权限计算器 (chmod)</span>
        </div>

        <div v-if="selectedFileForChmod" class="space-y-3 text-xs">
          <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 font-mono">
            <div class="text-[10px] text-slate-400">当前选中目标：</div>
            <div class="text-cyan-300 truncate mt-0.5">{{ selectedFileForChmod.path }}</div>
          </div>

          <!-- 九宫格勾选矩阵 -->
          <div class="grid grid-cols-4 gap-2 text-center items-center bg-slate-950 p-3 rounded-lg border border-slate-800">
            <div class="text-left text-[11px] text-slate-400">角色</div>
            <div class="font-mono text-[11px] text-slate-300">读(4)</div>
            <div class="font-mono text-[11px] text-slate-300">写(2)</div>
            <div class="font-mono text-[11px] text-slate-300">执行(1)</div>

            <div class="text-left text-slate-200 font-medium">所有者</div>
            <input v-model="chmodMatrix.ownerR" type="checkbox" aria-label="所有者读权限" />
            <input v-model="chmodMatrix.ownerW" type="checkbox" aria-label="所有者写权限" />
            <input v-model="chmodMatrix.ownerX" type="checkbox" aria-label="所有者执行权限" />

            <div class="text-left text-slate-200 font-medium">用户组</div>
            <input v-model="chmodMatrix.groupR" type="checkbox" aria-label="用户组读权限" />
            <input v-model="chmodMatrix.groupW" type="checkbox" aria-label="用户组写权限" />
            <input v-model="chmodMatrix.groupX" type="checkbox" aria-label="用户组执行权限" />

            <div class="text-left text-slate-200 font-medium">其他</div>
            <input v-model="chmodMatrix.otherR" type="checkbox" aria-label="其他用户读权限" />
            <input v-model="chmodMatrix.otherW" type="checkbox" aria-label="其他用户写权限" />
            <input v-model="chmodMatrix.otherX" type="checkbox" aria-label="其他用户执行权限" />
          </div>

          <div class="flex items-center justify-between p-2.5 rounded-lg bg-slate-950 border border-slate-800 font-mono">
            <div>
              <div class="text-[10px] text-slate-400">八进制值</div>
              <div class="text-sm font-bold text-amber-300">{{ computedOctal }}</div>
            </div>
            <div class="text-right">
              <div class="text-[10px] text-slate-400">符号表示</div>
              <div class="text-sm font-bold text-emerald-300">{{ computedSymbolic }}</div>
            </div>
          </div>

          <label class="flex items-center gap-2 text-slate-300 cursor-pointer">
            <input v-model="chmodMatrix.recursive" type="checkbox" class="rounded" />
            <span>递归应用到子目录 (<code>chmod -R</code>)</span>
          </label>
        </div>
      </div>

      <div class="space-y-2 pt-3 border-t border-slate-800">
        <div class="text-[11px] font-mono text-slate-400 bg-slate-950 p-2 rounded border border-slate-800 truncate">
          sudo chmod {{ chmodMatrix.recursive ? '-R ' : '' }}{{ computedOctal.slice(1) }} {{ selectedFileForChmod?.path }}
        </div>
        <button
          type="button"
          @click="applyChmod"
          class="w-full py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-semibold text-white cursor-pointer"
        >
          应用权限变更并同步终端
        </button>
      </div>
    </div>
  </div>
</template>
