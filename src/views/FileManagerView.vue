<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import {
  store,
  currentHost,
  openFileInEditor,
  executeTerminalCommand,
  showToast,
  fetchRemoteDirectory,
  fetchDirectoryDiskUsage,
  fetchSingleDirSize
} from '@/stores/workbenchStore'
import type { FileEntry } from '@/types'
import {
  FolderOpen,
  FileCode2,
  FileArchive,
  Bookmark,
  Shield,
  Terminal,
  Upload,
  Archive,
  PieChart,
  RefreshCw,
  ArrowUp,
  Home,
  FilePlus,
  FolderPlus,
  Download,
  Trash2,
  Edit3,
  Copy,
  Search,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  X,
  PackageOpen,
  ChevronRight,
  Zap
} from 'lucide-vue-next'

interface BookmarkItem {
  label: string
  path: string
  custom?: boolean
}

const DEFAULT_BOOKMARKS: BookmarkItem[] = [
  { label: '用户家目录 (~)', path: '~' },
  { label: '系统根目录 (/)', path: '/' },
  { label: 'Nginx 配置目录', path: '/etc/nginx' },
  { label: 'Systemd 单元目录', path: '/etc/systemd/system' },
  { label: '系统配置目录 (/etc)', path: '/etc' },
  { label: '系统日志目录 (/var/log)', path: '/var/log' },
  { label: '应用部署目录 (/opt)', path: '/opt' },
  { label: '临时缓存目录 (/tmp)', path: '/tmp' }
]

function loadBookmarks(): BookmarkItem[] {
  try {
    const raw = localStorage.getItem('termforyou_file_bookmarks')
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch {
    // ignore
  }
  return [...DEFAULT_BOOKMARKS]
}

const bookmarks = ref<BookmarkItem[]>(loadBookmarks())

function saveBookmarks() {
  try {
    localStorage.setItem('termforyou_file_bookmarks', JSON.stringify(bookmarks.value))
  } catch {
    // ignore
  }
}

function addCurrentDirBookmark() {
  const cwd = currentHost.value.currentCwd || '/root'
  if (bookmarks.value.some((b) => b.path === cwd)) {
    showToast(`目录 ${cwd} 已在收藏书签中`)
    return
  }
  const name = cwd === '/' ? '系统根目录 (/)' : `${cwd.split('/').filter(Boolean).pop() || cwd} 目录`
  bookmarks.value.unshift({
    label: name,
    path: cwd,
    custom: true
  })
  saveBookmarks()
  showToast(`已收藏目录书签: ${cwd}`)
}

function removeBookmark(path: string) {
  bookmarks.value = bookmarks.value.filter((b) => b.path !== path)
  saveBookmarks()
  showToast(`已移除书签: ${path}`)
}

// 路径导航与搜索过滤状态
const searchQuery = ref('')
const isEditingPath = ref(false)
const pathInputVal = ref('')
const pathInputRef = ref<HTMLInputElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const isDraggingOver = ref(false)
const isUploading = ref(false)
const isOperating = ref(false)

const currentCwd = computed(() => currentHost.value.currentCwd || '/root')

const breadcrumbSegments = computed(() => {
  const cwd = currentCwd.value
  if (!cwd || cwd === '/') return []
  const parts = cwd.split('/').filter(Boolean)
  return parts.map((part, idx) => ({
    name: part,
    path: '/' + parts.slice(0, idx + 1).join('/')
  }))
})

const filteredFiles = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return store.files
  return store.files.filter(
    (f) =>
      f.name.toLowerCase().includes(q) ||
      f.path.toLowerCase().includes(q) ||
      f.owner.toLowerCase().includes(q) ||
      f.permissions.toLowerCase().includes(q)
  )
})

function formatSize(bytes: number): string {
  if (!bytes || bytes < 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function isArchiveFile(name: string): boolean {
  const low = name.toLowerCase()
  return (
    low.endsWith('.tar.gz') ||
    low.endsWith('.tgz') ||
    low.endsWith('.zip') ||
    low.endsWith('.tar') ||
    low.endsWith('.tar.bz2') ||
    low.endsWith('.tar.xz')
  )
}

// 右侧 Chmod / Chown 状态与自动同步
const selectedFileForChmod = ref<FileEntry | null>(store.files[0] ?? null)

// 多选状态 (Shift 连续多选、Ctrl / Cmd 点选多选、全选)
const selectedPaths = ref<Set<string>>(new Set())
const lastSelectedPath = ref<string | null>(null)

const selectedFiles = computed(() => {
  return filteredFiles.value.filter((f) => selectedPaths.value.has(f.path))
})

const isAllSelected = computed(() => {
  if (filteredFiles.value.length === 0) return false
  return filteredFiles.value.every((f) => selectedPaths.value.has(f.path))
})

const isIndeterminate = computed(() => {
  if (filteredFiles.value.length === 0) return false
  const count = filteredFiles.value.filter((f) => selectedPaths.value.has(f.path)).length
  return count > 0 && count < filteredFiles.value.length
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedPaths.value.clear()
    lastSelectedPath.value = null
  } else {
    selectedPaths.value = new Set(filteredFiles.value.map((f) => f.path))
    if (filteredFiles.value.length > 0) {
      lastSelectedPath.value = filteredFiles.value[0].path
    }
  }
}

function toggleRowSelection(file: FileEntry, event: Event) {
  event.stopPropagation()
  const nextSet = new Set(selectedPaths.value)
  if (nextSet.has(file.path)) {
    nextSet.delete(file.path)
  } else {
    nextSet.add(file.path)
  }
  selectedPaths.value = nextSet
  lastSelectedPath.value = file.path
  selectedFileForChmod.value = file
}

function handleRowClick(file: FileEntry, event: MouseEvent) {
  selectedFileForChmod.value = file

  const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform)
  const isCtrlOrCmd = isMac ? event.metaKey : event.ctrlKey

  if (event.shiftKey && lastSelectedPath.value) {
    // 按住 Shift 连续区间多选
    const allPaths = filteredFiles.value.map((f) => f.path)
    const prevIdx = allPaths.indexOf(lastSelectedPath.value)
    const currIdx = allPaths.indexOf(file.path)

    if (prevIdx !== -1 && currIdx !== -1) {
      const start = Math.min(prevIdx, currIdx)
      const end = Math.max(prevIdx, currIdx)
      const range = allPaths.slice(start, end + 1)

      if (!isCtrlOrCmd) {
        selectedPaths.value = new Set(range)
      } else {
        const nextSet = new Set(selectedPaths.value)
        range.forEach((p) => nextSet.add(p))
        selectedPaths.value = nextSet
      }
    } else {
      selectedPaths.value = new Set([file.path])
      lastSelectedPath.value = file.path
    }
  } else if (isCtrlOrCmd) {
    // 按住 Ctrl / ⌘ 点选多选（追加或反选）
    const nextSet = new Set(selectedPaths.value)
    if (nextSet.has(file.path)) {
      nextSet.delete(file.path)
    } else {
      nextSet.add(file.path)
    }
    selectedPaths.value = nextSet
    lastSelectedPath.value = file.path
  } else {
    // 普通单击单选
    selectedPaths.value = new Set([file.path])
    lastSelectedPath.value = file.path
  }
}
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
  recursive: false,
  sudo: false
})
const chownOwner = ref('root')
const chownGroup = ref('root')
const isApplyingChmod = ref(false)

function syncChmodFromEntry(file: FileEntry | null) {
  if (!file) return
  const oct = (file.octal || '0644').padStart(4, '0').slice(-3)
  const o = parseInt(oct[0] || '6', 10)
  const g = parseInt(oct[1] || '4', 10)
  const t = parseInt(oct[2] || '4', 10)

  chmodMatrix.value.ownerR = (o & 4) !== 0
  chmodMatrix.value.ownerW = (o & 2) !== 0
  chmodMatrix.value.ownerX = (o & 1) !== 0

  chmodMatrix.value.groupR = (g & 4) !== 0
  chmodMatrix.value.groupW = (g & 2) !== 0
  chmodMatrix.value.groupX = (g & 1) !== 0

  chmodMatrix.value.otherR = (t & 4) !== 0
  chmodMatrix.value.otherW = (t & 2) !== 0
  chmodMatrix.value.otherX = (t & 1) !== 0

  chownOwner.value = file.owner || 'root'
  chownGroup.value = file.group || 'root'
  chmodMatrix.value.sudo = file.path.startsWith('/etc') || file.path.startsWith('/usr') || file.path.startsWith('/lib')
}

watch(
  selectedFileForChmod,
  (newFile) => {
    syncChmodFromEntry(newFile)
  },
  { immediate: true }
)

watch(
  () => store.files,
  (newFiles) => {
    if (!newFiles || newFiles.length === 0) {
      selectedFileForChmod.value = null
      selectedPaths.value.clear()
      lastSelectedPath.value = null
      return
    }

    const currentPathSet = new Set(newFiles.map((f) => f.path))
    for (const p of selectedPaths.value) {
      if (!currentPathSet.has(p)) {
        selectedPaths.value.delete(p)
      }
    }

    if (selectedFileForChmod.value) {
      const match = newFiles.find((f) => f.path === selectedFileForChmod.value?.path)
      if (match) {
        selectedFileForChmod.value = match
        syncChmodFromEntry(match)
        return
      }
    }
    selectedFileForChmod.value = newFiles[0]
  }
)

const computedOctal = computed(() => {
  const m = chmodMatrix.value
  const o = (m.ownerR ? 4 : 0) + (m.ownerW ? 2 : 0) + (m.ownerX ? 1 : 0)
  const g = (m.groupR ? 4 : 0) + (m.groupW ? 2 : 0) + (m.groupX ? 1 : 0)
  const t = (m.otherR ? 4 : 0) + (m.otherW ? 2 : 0) + (m.otherX ? 1 : 0)
  return `0${o}${g}${t}`
})

const computedSymbolic = computed(() => {
  const m = chmodMatrix.value
  const prefix = selectedFileForChmod.value?.isDir ? 'd' : '-'
  const bit = (r: boolean, w: boolean, x: boolean) => `${r ? 'r' : '-'}${w ? 'w' : '-'}${x ? 'x' : '-'}`
  return `${prefix}${bit(m.ownerR, m.ownerW, m.ownerX)}${bit(m.groupR, m.groupW, m.groupX)}${bit(m.otherR, m.otherW, m.otherX)}`
})

function setQuickOctalPreset(oct: string) {
  const clean = oct.slice(-3)
  const o = parseInt(clean[0] || '6', 10)
  const g = parseInt(clean[1] || '4', 10)
  const t = parseInt(clean[2] || '4', 10)
  chmodMatrix.value.ownerR = (o & 4) !== 0
  chmodMatrix.value.ownerW = (o & 2) !== 0
  chmodMatrix.value.ownerX = (o & 1) !== 0
  chmodMatrix.value.groupR = (g & 4) !== 0
  chmodMatrix.value.groupW = (g & 2) !== 0
  chmodMatrix.value.groupX = (g & 1) !== 0
  chmodMatrix.value.otherR = (t & 4) !== 0
  chmodMatrix.value.otherW = (t & 2) !== 0
  chmodMatrix.value.otherX = (t & 1) !== 0
}

async function applyChmod() {
  const target = selectedFileForChmod.value
  const hostId = store.activeHostId
  if (!target || !hostId) return

  isApplyingChmod.value = true
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/chmod`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: target.path,
        octal: computedOctal.value,
        recursive: chmodMatrix.value.recursive,
        owner: chownOwner.value.trim() || target.owner,
        group: chownGroup.value.trim() || target.group,
        sudo: chmodMatrix.value.sudo
      })
    })
    const data = await res.json()
    if (res.ok && data.status === 'ok') {
      target.octal = data.octal || computedOctal.value
      target.permissions = data.permissions || computedSymbolic.value
      if (data.owner) target.owner = data.owner
      if (data.group) target.group = data.group
      showToast(data.message || `已更新权限: ${target.path} -> ${computedOctal.value}`)
      await fetchRemoteDirectory(currentCwd.value, false)
    } else {
      showToast(data.message || '修改文件权限失败')
    }
  } catch {
    showToast('修改权限失败：无法连接后端服务')
  } finally {
    isApplyingChmod.value = false
  }
}

// 目录跳转与导航动作
async function jumpToDir(path: string) {
  searchQuery.value = ''
  isEditingPath.value = false
  selectedPaths.value.clear()
  lastSelectedPath.value = null
  const ok = await fetchRemoteDirectory(path, true)
  if (ok) {
    showToast(`已切换远程工作目录至 ${currentHost.value.currentCwd}`)
  }
}

// 单独异步测算指定目录的磁盘占用
async function recalculateSingleDir(dirPath: string) {
  const name = dirPath.split('/').filter(Boolean).pop() || dirPath
  const size = await fetchSingleDirSize(dirPath)
  if (size !== null) {
    showToast(`已测算「${name}」真实占用: ${formatSize(size)}`)
  } else {
    showToast(`测算「${name}」失败或超时`)
  }
}

function goUpDirectory() {
  const cwd = currentCwd.value
  if (!cwd || cwd === '/') return
  const parts = cwd.split('/').filter(Boolean)
  parts.pop()
  const parent = parts.length === 0 ? '/' : '/' + parts.join('/')
  jumpToDir(parent)
}

function startEditPath() {
  pathInputVal.value = currentCwd.value
  isEditingPath.value = true
  nextTick(() => {
    pathInputRef.value?.focus()
    pathInputRef.value?.select()
  })
}

function submitPathInput() {
  const val = pathInputVal.value.trim()
  isEditingPath.value = false
  if (val && val !== currentCwd.value) {
    jumpToDir(val)
  }
}

function toggleHiddenFiles() {
  store.showHiddenFiles = !store.showHiddenFiles
  fetchRemoteDirectory(currentCwd.value, false)
}

function handleRowDoubleClick(file: FileEntry) {
  if (file.isDir) {
    jumpToDir(file.path)
  } else {
    openFileInEditor(file.path)
  }
}

// ============================================================================
// 原生 <dialog> 模态框控制：新建文件、新建文件夹、重命名/移动、删除确认
// ============================================================================
type DialogMode = 'touch' | 'mkdir' | 'rename' | 'delete'
const actionDialogRef = ref<HTMLDialogElement | null>(null)
const dialogMode = ref<DialogMode>('touch')
const dialogInputName = ref('')
const dialogDirMode = ref('0755')
const dialogOpenEditorAfterTouch = ref(true)
const dialogUseSudo = ref(false)
const dialogTargetFile = ref<FileEntry | null>(null)
const dialogTargetFiles = ref<FileEntry[]>([])

function openActionDialog(mode: DialogMode, target?: FileEntry | FileEntry[]) {
  dialogMode.value = mode
  if (Array.isArray(target)) {
    dialogTargetFiles.value = target
    dialogTargetFile.value = target[0] ?? null
  } else if (target) {
    dialogTargetFiles.value = [target]
    dialogTargetFile.value = target
  } else {
    dialogTargetFiles.value = []
    dialogTargetFile.value = null
  }

  const cwd = currentCwd.value
  dialogUseSudo.value = cwd.startsWith('/etc') || cwd.startsWith('/usr') || cwd.startsWith('/lib')

  if (mode === 'touch') {
    dialogInputName.value = ''
    dialogOpenEditorAfterTouch.value = true
  } else if (mode === 'mkdir') {
    dialogInputName.value = ''
    dialogDirMode.value = '0755'
  } else if (mode === 'rename' && dialogTargetFile.value) {
    dialogInputName.value = dialogTargetFile.value.path
  }

  actionDialogRef.value?.showModal()
}

function closeActionDialog() {
  actionDialogRef.value?.close()
}

function joinRemotePath(baseDir: string, name: string): string {
  if (name.startsWith('/') || name.startsWith('~')) return name
  const cleanBase = baseDir.endsWith('/') ? baseDir.slice(0, -1) : baseDir
  return `${cleanBase}/${name}`
}

async function submitActionDialog() {
  const hostId = store.activeHostId
  if (!hostId) return

  const mode = dialogMode.value
  isOperating.value = true

  try {
    if (mode === 'touch') {
      const name = dialogInputName.value.trim()
      if (!name) return
      const fullPath = joinRemotePath(currentCwd.value, name)
      const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/touch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: fullPath,
          content: '',
          sudo: dialogUseSudo.value
        })
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        showToast(`已创建文件: ${fullPath}`)
        closeActionDialog()
        await fetchRemoteDirectory(currentCwd.value, false)
        if (dialogOpenEditorAfterTouch.value) {
          openFileInEditor(fullPath)
        }
      } else {
        showToast(data.message || '新建文件失败')
      }
    } else if (mode === 'mkdir') {
      const name = dialogInputName.value.trim()
      if (!name) return
      const fullPath = joinRemotePath(currentCwd.value, name)
      const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/mkdir`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: fullPath,
          mode: dialogDirMode.value || '0755',
          sudo: dialogUseSudo.value
        })
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        showToast(`已创建目录: ${fullPath}`)
        closeActionDialog()
        await fetchRemoteDirectory(currentCwd.value, true)
      } else {
        showToast(data.message || '新建目录失败')
      }
    } else if (mode === 'rename' && dialogTargetFile.value) {
      const newInput = dialogInputName.value.trim()
      if (!newInput) return
      const newPath = joinRemotePath(currentCwd.value, newInput)
      const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_path: dialogTargetFile.value.path,
          new_path: newPath,
          sudo: dialogUseSudo.value
        })
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        showToast(data.message || `已重命名至 ${newPath}`)
        closeActionDialog()
        await fetchRemoteDirectory(currentCwd.value, false)
      } else {
        showToast(data.message || '重命名失败')
      }
    } else if (mode === 'delete' && dialogTargetFiles.value.length > 0) {
      const targetPaths = dialogTargetFiles.value.map((f) => f.path)
      const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paths: targetPaths,
          sudo: dialogUseSudo.value
        })
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        showToast(data.message || `已成功删除 ${targetPaths.length} 个项目`)
        targetPaths.forEach((p) => selectedPaths.value.delete(p))
        closeActionDialog()
        await fetchRemoteDirectory(currentCwd.value, true)
      } else {
        showToast(data.message || '删除失败')
      }
    }
  } catch {
    showToast('操作失败：无法连接后端服务')
  } finally {
    isOperating.value = false
  }
}

// 批量删除模态框呼出
function openBatchDeleteDialog() {
  if (selectedFiles.value.length === 0) return
  openActionDialog('delete', selectedFiles.value)
}

// 批量打包选中项
async function compressSelectedEntries() {
  const hostId = store.activeHostId
  if (!hostId || selectedFiles.value.length === 0) return

  const list = selectedFiles.value
  const paths = list.map((f) => f.path)
  const baseName = list.length === 1 ? list[0].name : `batch_${list.length}items`
  const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
  const outputPath = joinRemotePath(currentCwd.value, `${baseName}_${ts}.tar.gz`)

  showToast(`正在将选中的 ${paths.length} 个项目打包至 ${outputPath} ...`)
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        paths,
        output_path: outputPath,
        action: 'compress',
        sudo: false
      })
    })
    const data = await res.json()
    if (res.ok && data.status === 'ok') {
      showToast(data.message || `已成功打包生成: ${outputPath}`)
      await fetchRemoteDirectory(currentCwd.value, true)
    } else {
      showToast(data.message || '打包压缩失败')
    }
  } catch {
    showToast('打包失败：无法连接后端服务')
  }
}

// 批量下载选中项 (单项直接下载，多项自动打包为 .tar.gz 流式下载)
async function downloadSelectedEntries() {
  const hostId = store.activeHostId
  if (!hostId || selectedFiles.value.length === 0) return

  const list = selectedFiles.value
  if (list.length === 1) {
    downloadRemoteEntry(list[0])
    return
  }

  showToast(`正在批量打包并下载选中的 ${list.length} 个项目...`)
  const paths = list.map((f) => f.path)

  try {
    const res = await fetch(
      `http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/download-batch`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths })
      }
    )
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      showToast(err.detail || '批量下载失败')
      return
    }

    const disposition = res.headers.get('Content-Disposition')
    let filename = `batch_download_${list.length}items.tar.gz`
    if (disposition && disposition.includes("filename*=UTF-8''")) {
      const parts = disposition.split("filename*=UTF-8''")
      if (parts[1]) filename = decodeURIComponent(parts[1])
    } else if (disposition && disposition.includes('filename=')) {
      const match = disposition.match(/filename="?([^"]+)"?/)
      if (match && match[1]) filename = match[1]
    }

    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    showToast(`批量下载已开始: ${filename}`)
  } catch {
    showToast('批量下载失败：网络或连接异常')
  }
}

// ============================================================================
// 文件复制、打包压缩 (.tar.gz)、解压、上传与下载
// ============================================================================
async function duplicateFile(file: FileEntry) {
  const hostId = store.activeHostId
  if (!hostId) return

  const extIdx = file.name.lastIndexOf('.')
  const copyName =
    extIdx > 0
      ? `${file.name.slice(0, extIdx)}_copy${file.name.slice(extIdx)}`
      : `${file.name}_copy`
  const destPath = joinRemotePath(currentCwd.value, copyName)

  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/copy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        src_path: file.path,
        dest_path: destPath,
        sudo: false
      })
    })
    const data = await res.json()
    if (res.ok && data.status === 'ok') {
      showToast(`已创建副本: ${destPath}`)
      await fetchRemoteDirectory(currentCwd.value, false)
    } else {
      showToast(data.message || '复制文件失败')
    }
  } catch {
    showToast('复制失败：无法连接后端服务')
  }
}

async function compressTarget(targetPath?: string) {
  const hostId = store.activeHostId
  if (!hostId) return

  const pathToPack = targetPath || selectedFileForChmod.value?.path || currentCwd.value
  const baseName = pathToPack.split('/').filter(Boolean).pop() || 'backup'
  const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
  const outputPath = joinRemotePath(currentCwd.value, `${baseName}_${ts}.tar.gz`)

  showToast(`正在打包压缩 ${pathToPack} ...`)
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        paths: [pathToPack],
        output_path: outputPath,
        action: 'compress',
        sudo: false
      })
    })
    const data = await res.json()
    if (res.ok && data.status === 'ok') {
      showToast(data.message || `已打包生成: ${outputPath}`)
      await fetchRemoteDirectory(currentCwd.value, true)
    } else {
      showToast(data.message || '打包压缩失败')
    }
  } catch {
    showToast('打包失败：无法连接后端服务')
  }
}

async function extractArchive(file: FileEntry) {
  const hostId = store.activeHostId
  if (!hostId) return

  showToast(`正在解压 ${file.name} 至 ${currentCwd.value} ...`)
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        paths: [file.path],
        target_dir: currentCwd.value,
        action: 'extract',
        sudo: false
      })
    })
    const data = await res.json()
    if (res.ok && data.status === 'ok') {
      showToast(data.message || `已解压 ${file.name}`)
      await fetchRemoteDirectory(currentCwd.value, true)
    } else {
      showToast(data.message || '解压失败')
    }
  } catch {
    showToast('解压失败：无法连接后端服务')
  }
}

function downloadRemoteEntry(file: FileEntry) {
  const hostId = store.activeHostId
  if (!hostId) return

  const url = `http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/download?path=${encodeURIComponent(file.path)}`
  const a = document.createElement('a')
  a.href = url
  a.download = file.isDir ? `${file.name}.tar.gz` : file.name
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  showToast(
    file.isDir
      ? `正在将目录「${file.name}」打包为 .tar.gz 下载...`
      : `开始下载文件: ${file.name}`
  )
}

function triggerUploadPicker() {
  fileInputRef.value?.click()
}

async function uploadFilesList(files: FileList | File[]) {
  const hostId = store.activeHostId
  if (!hostId || !files || files.length === 0) return

  isUploading.value = true
  const cwd = currentCwd.value
  const needSudo = cwd.startsWith('/etc') || cwd.startsWith('/usr') || cwd.startsWith('/lib')
  let successCount = 0

  try {
    for (const file of Array.from(files)) {
      const remotePath = joinRemotePath(cwd, file.name)
      showToast(`正在上传 ${file.name} (${formatSize(file.size)}) -> ${remotePath} ...`)
      const buf = await file.arrayBuffer()
      const res = await fetch(
        `http://127.0.0.1:8000/api/v1/ssh/files/${encodeURIComponent(hostId)}/upload?path=${encodeURIComponent(remotePath)}&sudo=${needSudo}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/octet-stream' },
          body: buf
        }
      )
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        successCount++
      } else {
        showToast(data.message || `上传 ${file.name} 失败`)
      }
    }
    if (successCount > 0) {
      showToast(`已成功上传 ${successCount} 个文件至 ${cwd}`)
      await fetchRemoteDirectory(cwd, true)
    }
  } catch {
    showToast('上传失败：无法连接后端服务')
  } finally {
    isUploading.value = false
    if (fileInputRef.value) {
      fileInputRef.value.value = ''
    }
  }
}

function handleFileUploadChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    uploadFilesList(input.files)
  }
}

function handleDropUpload(e: DragEvent) {
  isDraggingOver.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    uploadFilesList(e.dataTransfer.files)
  }
}

function handleKeyDown(e: KeyboardEvent) {
  // 当焦点在输入框或文本域内时不触发文件列表快捷键
  const activeEl = document.activeElement
  if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) {
    return
  }

  // Ctrl+A / Cmd+A: 全选当前筛选视图中的所有文件
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
    e.preventDefault()
    selectedPaths.value = new Set(filteredFiles.value.map((f) => f.path))
    if (filteredFiles.value.length > 0) {
      lastSelectedPath.value = filteredFiles.value[0].path
    }
  }

  // Escape: 清空多选状态
  if (e.key === 'Escape' && selectedPaths.value.size > 0) {
    e.preventDefault()
    selectedPaths.value.clear()
    lastSelectedPath.value = null
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)

  if (store.activeHostId) {
    fetchRemoteDirectory(currentHost.value.currentCwd || '~', true)
  }

  // Fallback for <dialog closedby="any"> light dismiss (modern-web-guidance: dialog)
  const dlg = actionDialogRef.value
  if (dlg && typeof HTMLDialogElement !== 'undefined' && !('closedBy' in HTMLDialogElement.prototype)) {
    const outside = (e: PointerEvent, dialog: HTMLDialogElement) => {
      const r = dialog.getBoundingClientRect()
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom
    }
    let pressedOutside = false
    dlg.addEventListener('pointerdown', (e) => {
      pressedOutside = outside(e, dlg)
    })
    dlg.addEventListener('pointerup', (e) => {
      if (pressedOutside && outside(e, dlg)) dlg.close()
    })
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="p-5 h-full flex gap-4 overflow-hidden">
    <!-- 隐藏的文件上传选择器 -->
    <input
      ref="fileInputRef"
      type="file"
      multiple
      class="hidden"
      @change="handleFileUploadChange"
    />

    <!-- 左侧：收藏书签 + 磁盘空间 ncdu 实时概览 -->
    <div class="w-64 bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 flex flex-col justify-between shrink-0 overflow-hidden">
      <div class="space-y-2.5 flex-1 min-h-0 flex flex-col">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2 text-xs font-bold text-slate-100">
            <Bookmark class="w-4 h-4 text-amber-400" />
            <span>高频目录书签</span>
          </div>
          <button
            type="button"
            @click="addCurrentDirBookmark"
            title="将当前目录加入书签"
            class="flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 text-[11px] cursor-pointer"
          >
            <Plus class="w-3 h-3" />
            <span>收藏当前</span>
          </button>
        </div>

        <div class="space-y-1 overflow-y-auto pr-1 flex-1">
          <div
            v-for="bm in bookmarks"
            :key="bm.path"
            @click="jumpToDir(bm.path)"
            :class="[
              'group w-full text-left px-2.5 py-2 rounded-lg text-xs transition cursor-pointer flex items-center justify-between gap-1',
              currentCwd === bm.path
                ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/40'
                : 'hover:bg-slate-800 text-slate-300 border border-transparent'
            ]"
          >
            <div class="min-w-0 flex-1">
              <div class="font-medium truncate">{{ bm.label }}</div>
              <div class="font-mono text-[10px] text-slate-400 mt-0.5 truncate">{{ bm.path }}</div>
            </div>
            <button
              v-if="bm.custom"
              type="button"
              @click.stop="removeBookmark(bm.path)"
              title="移除此书签"
              class="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-rose-500/20 text-slate-400 hover:text-rose-300 cursor-pointer"
            >
              <X class="w-3 h-3" />
            </button>
          </div>
        </div>
      </div>

      <!-- 目录体积分析 (类 ncdu 实时可视化) -->
      <div class="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-2 mt-3 shrink-0">
        <div class="flex items-center justify-between text-xs font-semibold text-slate-100">
          <div class="flex items-center gap-1.5">
            <PieChart class="w-3.5 h-3.5 text-indigo-400" />
            <span>目录体积分布 (ncdu)</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="font-mono text-[11px] text-indigo-300">
              {{ formatSize(store.dirDiskUsage.totalBytes) }}
            </span>
            <button
              type="button"
              @click="fetchDirectoryDiskUsage(currentCwd)"
              title="重新扫描当前目录体积分布"
              class="text-slate-400 hover:text-indigo-300 cursor-pointer"
            >
              <RefreshCw class="w-3 h-3" :class="store.dirDiskUsage.loading ? 'animate-spin text-indigo-400' : ''" />
            </button>
          </div>
        </div>

        <div v-if="store.dirDiskUsage.items.length > 0" class="space-y-1.5 text-[11px] max-h-40 overflow-y-auto pr-0.5">
          <div
            v-for="item in store.dirDiskUsage.items.slice(0, 5)"
            :key="item.path"
            @click="item.isDir ? jumpToDir(item.path) : openFileInEditor(item.path)"
            class="cursor-pointer group"
          >
            <div class="flex justify-between font-mono text-slate-300 group-hover:text-cyan-300">
              <span class="truncate max-w-[120px]" :title="item.path">
                {{ item.isDir ? '📁' : '📄' }} {{ item.name }}
              </span>
              <span class="shrink-0">{{ formatSize(item.sizeBytes) }} ({{ item.percent }}%)</span>
            </div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden mt-0.5">
              <div
                class="bg-indigo-500 h-full transition-all duration-300"
                :style="{ width: `${Math.max(4, Math.min(100, item.percent))}%` }"
              />
            </div>
          </div>
        </div>
        <div v-else class="text-[11px] text-slate-400 py-2 text-center">
          {{ store.dirDiskUsage.loading ? '正在统计目录占用...' : '当前目录为空或暂无体积数据' }}
        </div>
      </div>
    </div>

    <!-- 中间：SFTP 文件列表与工具栏 -->
    <div
      class="flex-1 bg-slate-900/90 border border-slate-800 rounded-xl flex flex-col overflow-hidden min-w-0 relative"
      @dragover.prevent="isDraggingOver = true"
      @dragleave.prevent="isDraggingOver = false"
      @drop.prevent="handleDropUpload"
    >
      <!-- 拖拽上传遮罩提示 -->
      <div
        v-if="isDraggingOver"
        class="absolute inset-0 bg-cyan-950/85 border-2 border-dashed border-cyan-400 rounded-xl z-30 flex flex-col items-center justify-center gap-2 pointer-events-none"
      >
        <Upload class="w-10 h-10 text-cyan-300 animate-bounce" />
        <div class="text-sm font-bold text-cyan-200">松开鼠标立即通过 SFTP 上传至当前目录</div>
        <div class="text-xs font-mono text-cyan-300">{{ currentCwd }}</div>
      </div>

      <!-- 第一行：路径面包屑导航 + 搜索过滤 -->
      <div class="p-3 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2 bg-slate-950/50">
        <div class="flex items-center gap-1.5 flex-1 min-w-[280px]">
          <button
            type="button"
            @click="goUpDirectory"
            :disabled="currentCwd === '/'"
            title="返回上级目录 (..)"
            class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-200 cursor-pointer"
          >
            <ArrowUp class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            @click="jumpToDir('~')"
            title="进入用户家目录 (~)"
            class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 cursor-pointer"
          >
            <Home class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            @click="fetchRemoteDirectory(currentCwd, true)"
            title="刷新当前目录"
            class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 cursor-pointer"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="store.filesLoading ? 'animate-spin text-cyan-400' : ''" />
          </button>

          <!-- 可点击面包屑 / 可编辑路径输入框 -->
          <div
            v-if="!isEditingPath"
            @click="startEditPath"
            title="点击直接输入路径跳转"
            class="flex-1 flex items-center gap-0.5 px-2.5 py-1 rounded-lg bg-slate-950 border border-slate-800 hover:border-cyan-500/50 font-mono text-xs overflow-x-auto cursor-text"
          >
            <button
              type="button"
              @click.stop="jumpToDir('/')"
              class="px-1 py-0.5 rounded hover:bg-slate-800 text-amber-400 font-bold cursor-pointer shrink-0"
            >
              /
            </button>
            <template v-for="(seg, idx) in breadcrumbSegments" :key="seg.path">
              <ChevronRight v-if="idx > 0" class="w-3 h-3 text-slate-600 shrink-0" />
              <button
                type="button"
                @click.stop="jumpToDir(seg.path)"
                class="px-1.5 py-0.5 rounded hover:bg-slate-800 text-amber-300 hover:text-cyan-300 cursor-pointer shrink-0"
              >
                {{ seg.name }}
              </button>
            </template>
          </div>

          <form
            v-else
            @submit.prevent="submitPathInput"
            class="flex-1 flex items-center gap-1"
          >
            <input
              ref="pathInputRef"
              v-model="pathInputVal"
              type="text"
              placeholder="输入远程绝对路径，按回车跳转..."
              aria-label="远程目录路径输入"
              @blur="submitPathInput"
              @keydown.esc="isEditingPath = false"
              class="w-full px-2.5 py-1 rounded-lg bg-slate-950 border border-cyan-500 font-mono text-xs text-amber-300 focus:outline-none"
            />
          </form>
        </div>

        <!-- 搜索与隐藏文件开关 -->
        <div class="flex items-center gap-2">
          <div class="relative">
            <Search class="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              v-model="searchQuery"
              type="search"
              placeholder="过滤当前目录文件名..."
              aria-label="过滤当前目录文件名"
              class="pl-8 pr-2.5 py-1 rounded-lg bg-slate-950 border border-slate-800 focus:border-cyan-500/60 text-xs text-slate-200 focus:outline-none w-44"
            />
          </div>

          <button
            type="button"
            @click="toggleHiddenFiles"
            :title="store.showHiddenFiles ? '当前已显示隐藏文件 (.dot)，点击隐藏' : '当前已隐藏 .dot 文件，点击显示'"
            :class="[
              'flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs border cursor-pointer transition',
              store.showHiddenFiles
                ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            ]"
          >
            <Eye v-if="store.showHiddenFiles" class="w-3.5 h-3.5" />
            <EyeOff v-else class="w-3.5 h-3.5" />
            <span>隐藏文件</span>
          </button>
        </div>
      </div>

      <!-- 第二行：文件操作工具栏 -->
      <div class="px-3.5 py-2 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-1.5 flex-wrap">
          <button
            type="button"
            @click="openActionDialog('touch')"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
          >
            <FilePlus class="w-3.5 h-3.5 text-emerald-400" />
            <span>新建文件</span>
          </button>

          <button
            type="button"
            @click="openActionDialog('mkdir')"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
          >
            <FolderPlus class="w-3.5 h-3.5 text-amber-400" />
            <span>新建文件夹</span>
          </button>

          <button
            type="button"
            :disabled="isUploading"
            @click="triggerUploadPicker"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-cyan-600/20 hover:bg-cyan-600/30 border border-cyan-500/40 text-xs text-cyan-300 font-medium cursor-pointer disabled:opacity-50"
          >
            <Loader2 v-if="isUploading" class="w-3.5 h-3.5 animate-spin" />
            <Upload v-else class="w-3.5 h-3.5 text-cyan-400" />
            <span>{{ isUploading ? '上传中...' : 'SFTP 上传文件' }}</span>
          </button>

          <button
            type="button"
            @click="compressTarget()"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
          >
            <Archive class="w-3.5 h-3.5 text-amber-400" />
            <span>
              {{ selectedFileForChmod ? `打包「${selectedFileForChmod.name}」` : '一键打包 .tar.gz' }}
            </span>
          </button>
        </div>

        <div class="flex items-center gap-2">
          <!-- 异步测算当前目录所有子目录真实体积 -->
          <button
            type="button"
            @click="fetchDirectoryDiskUsage(currentCwd)"
            :disabled="store.dirDiskUsage.loading"
            title="异步测算当前目录下所有子目录的真实磁盘占用"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 border border-slate-700 hover:border-cyan-500/50 cursor-pointer disabled:opacity-50 transition"
          >
            <RefreshCw
              class="w-3.5 h-3.5 text-cyan-400"
              :class="store.dirDiskUsage.loading ? 'animate-spin' : ''"
            />
            <span>{{ store.dirDiskUsage.loading ? '测算中...' : '测算目录大小' }}</span>
          </button>

          <!-- 自动测算开关 -->
          <button
            type="button"
            @click="store.autoCalculateDirSizes = !store.autoCalculateDirSizes"
            :title="store.autoCalculateDirSizes ? '已开启：进入目录时自动在后台异步测算子目录真实大小（点击可关闭）' : '已关闭自动测算：点击开启进入目录时自动异步测算'"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs border cursor-pointer transition"
            :class="store.autoCalculateDirSizes ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40' : 'bg-slate-800 text-slate-400 border-slate-700'"
          >
            <Zap class="w-3.5 h-3.5" :class="store.autoCalculateDirSizes ? 'text-cyan-400 fill-cyan-400' : 'text-slate-500'" />
            <span>自动测算</span>
          </button>

          <span class="text-[11px] font-mono text-slate-400">
            共 {{ filteredFiles.length }} 项
          </span>
          <button
            type="button"
            @click="executeTerminalCommand(`cd ${currentCwd}`, true)"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-300 text-xs cursor-pointer"
          >
            <Terminal class="w-3.5 h-3.5" />
            <span>在终端打开此目录</span>
          </button>
        </div>
      </div>

      <!-- 批量操作控制栏 (当选中文件时显示) -->
      <div
        v-if="selectedPaths.size > 0"
        class="px-3.5 py-2 bg-cyan-950/40 border-b border-cyan-500/40 flex flex-wrap items-center justify-between gap-2 select-none"
      >
        <div class="flex items-center gap-2">
          <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 font-mono font-bold text-xs border border-cyan-500/40">
            已选择 {{ selectedPaths.size }} 项
          </span>
          <span class="text-slate-400 text-xs hidden sm:inline">
            (Shift 范围多选 · Ctrl/⌘ 点选加减 · Ctrl/⌘+A 全选)
          </span>
        </div>

        <div class="flex items-center gap-2 flex-wrap">
          <!-- 批量下载 -->
          <button
            type="button"
            @click="downloadSelectedEntries"
            class="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-medium text-xs cursor-pointer shadow-xs transition"
            :title="selectedPaths.size === 1 ? '下载所选文件' : '将选中的多个项目自动打包为 .tar.gz 下载'"
          >
            <Download class="w-3.5 h-3.5" />
            <span>批量下载 ({{ selectedPaths.size }})</span>
          </button>

          <!-- 批量打包 -->
          <button
            type="button"
            @click="compressSelectedEntries"
            class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs cursor-pointer transition"
            title="将选中的多个项目打包为 .tar.gz"
          >
            <Archive class="w-3.5 h-3.5 text-amber-400" />
            <span>批量打包</span>
          </button>

          <!-- 批量删除 -->
          <button
            type="button"
            @click="openBatchDeleteDialog"
            class="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/40 font-medium text-xs cursor-pointer transition"
            title="批量删除选中的项目（支持 sudo 提权）"
          >
            <Trash2 class="w-3.5 h-3.5 text-rose-400" />
            <span>批量删除 ({{ selectedPaths.size }})</span>
          </button>

          <!-- 清除多选 -->
          <button
            type="button"
            @click="selectedPaths.clear(); lastSelectedPath = null"
            class="flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 text-xs cursor-pointer transition"
            title="取消选择 (Esc)"
          >
            <X class="w-3.5 h-3.5" />
            <span>取消</span>
          </button>
        </div>
      </div>

      <!-- 文件列表表格 -->
      <div tabindex="0" role="region" aria-label="远程服务器文件列表" class="table-wrapper flex-1 relative">
        <div
          v-if="store.filesLoading"
          class="absolute inset-0 bg-slate-950/60 backdrop-blur-[1px] z-10 flex items-center justify-center gap-2 text-xs text-cyan-300"
        >
          <Loader2 class="w-4 h-4 animate-spin" />
          <span>正在同步远程目录 {{ currentCwd }} ...</span>
        </div>

        <table class="text-left text-xs" style="--label-2: '权限'; --label-3: '所有者'; --label-4: '大小/时间'">
          <thead class="bg-slate-950 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3 w-8 text-center">
                <input
                  type="checkbox"
                  :checked="isAllSelected"
                  :indeterminate="isIndeterminate"
                  @change="toggleSelectAll"
                  class="rounded border-slate-700 text-cyan-500 focus:ring-cyan-500/20 cursor-pointer"
                  title="全选 / 取消全选 (快捷键: Ctrl/Cmd + A)"
                />
              </th>
              <th class="py-2.5 px-3">文件名 / 路径</th>
              <th class="py-2.5 px-3">权限 (Octal)</th>
              <th class="py-2.5 px-3">所有者</th>
              <th class="py-2.5 px-3">大小 / 修改时间</th>
              <th class="py-2.5 px-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/70">
            <!-- 返回上一级 (..) 行 -->
            <tr
              v-if="currentCwd !== '/'"
              @click="goUpDirectory"
              class="group hover:bg-slate-800/60 transition cursor-pointer bg-slate-950/30"
            >
              <td class="py-2 px-3 text-center text-slate-600"></td>
              <th class="py-2 px-3 font-mono font-medium text-amber-300">
                <div class="flex items-center gap-2">
                  <FolderOpen class="w-4 h-4 text-amber-400 shrink-0" />
                  <span class="group-hover:underline">.. (返回上级目录)</span>
                </div>
              </th>
              <td class="py-2 px-3 font-mono text-slate-500">drwxr-xr-x</td>
              <td class="py-2 px-3 font-mono text-slate-500">--</td>
              <td class="py-2 px-3 font-mono text-slate-500">--</td>
              <td class="py-2 px-3 text-right">
                <button
                  type="button"
                  @click.stop="goUpDirectory"
                  class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] cursor-pointer"
                >
                  上级目录
                </button>
              </td>
            </tr>

            <tr
              v-for="file in filteredFiles"
              :key="file.path"
              @click="handleRowClick(file, $event)"
              @dblclick="handleRowDoubleClick(file)"
              :class="[
                'group hover:bg-slate-800/60 transition cursor-pointer select-none',
                selectedPaths.has(file.path)
                  ? 'is-selected bg-cyan-500/15 border-l-2 border-cyan-400 text-slate-100'
                  : selectedFileForChmod?.path === file.path
                  ? 'bg-slate-800/40'
                  : ''
              ]"
            >
              <td class="py-2.5 px-3 w-8 text-center" @click.stop>
                <input
                  type="checkbox"
                  :checked="selectedPaths.has(file.path)"
                  @click.stop
                  @change="toggleRowSelection(file, $event)"
                  class="rounded border-slate-700 text-cyan-500 focus:ring-cyan-500/20 cursor-pointer"
                  :title="`选择 ${file.name}`"
                />
              </td>
              <th class="py-2.5 px-3 font-mono font-medium text-slate-100">
                <div class="flex items-center gap-2">
                  <FolderOpen
                    v-if="file.isDir"
                    class="w-4 h-4 text-amber-400 shrink-0"
                    @click.stop="jumpToDir(file.path)"
                  />
                  <FileArchive
                    v-else-if="isArchiveFile(file.name)"
                    class="w-4 h-4 text-purple-400 shrink-0"
                  />
                  <FileCode2
                    v-else
                    class="w-4 h-4 text-cyan-400 shrink-0"
                  />
                  <div class="min-w-0">
                    <div class="flex items-center gap-1.5">
                      <button
                        v-if="file.isDir"
                        type="button"
                        @click.stop="jumpToDir(file.path)"
                        class="hover:text-amber-300 group-hover:text-amber-300 hover:underline text-left font-semibold cursor-pointer truncate"
                      >
                        {{ file.name }}
                      </button>
                      <button
                        v-else
                        type="button"
                        @click.stop="openFileInEditor(file.path)"
                        title="点击在编辑器中打开此文件"
                        class="hover:text-cyan-300 group-hover:text-cyan-300 hover:underline text-left font-medium cursor-pointer truncate text-slate-100"
                      >
                        {{ file.name }}
                      </button>
                      <span
                        v-if="file.isSymlink"
                        class="text-[10px] px-1.5 py-0.2 rounded bg-purple-500/15 text-purple-300 border border-purple-500/30"
                        :title="file.linkTarget ? `符号链接指向: ${file.linkTarget}` : '符号链接'"
                      >
                        symlink {{ file.linkTarget ? `→ ${file.linkTarget}` : '' }}
                      </span>
                    </div>
                    <div class="text-[10px] text-slate-400 group-hover:text-slate-300 truncate transition-colors">{{ file.path }}</div>
                  </div>
                </div>
              </th>
              <td class="py-2.5 px-3 font-mono whitespace-nowrap">
                <span class="text-emerald-300">{{ file.permissions }}</span>
                <span class="text-slate-500 ml-1">({{ file.octal }})</span>
              </td>
              <td class="py-2.5 px-3 font-mono text-slate-300 whitespace-nowrap">
                {{ file.owner }}:{{ file.group }}
              </td>
              <td class="py-2.5 px-3 font-mono text-slate-400 whitespace-nowrap">
                <div v-if="!file.isDir">{{ formatSize(file.sizeBytes) }}</div>
                <div v-else class="flex items-center gap-1.5">
                  <!-- 正在异步测算中 -->
                  <template v-if="store.calculatingDirs.includes(file.path) || (store.dirDiskUsage.loading && store.dirSizes[file.path] === undefined)">
                    <span class="inline-flex items-center gap-1 text-[11px] text-cyan-400/90 animate-pulse" title="正在后台非阻塞测算中...">
                      <Loader2 class="w-3 h-3 animate-spin text-cyan-400 shrink-0" />
                      <span>测算中...</span>
                    </span>
                  </template>
                  <!-- 已获取目录大小 -->
                  <template v-else-if="store.dirSizes[file.path] !== undefined">
                    <button
                      type="button"
                      @click.stop="recalculateSingleDir(file.path)"
                      class="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-300 hover:text-cyan-200 cursor-pointer hover:underline"
                      :title="`文件夹磁盘占用: ${formatSize(store.dirSizes[file.path])} (点击重新测算)`"
                    >
                      <span>📁 {{ formatSize(store.dirSizes[file.path]) }}</span>
                    </button>
                    <button
                      type="button"
                      @click.stop="recalculateSingleDir(file.path)"
                      title="重新测算此目录占用"
                      class="opacity-0 group-hover:opacity-100 hover:text-cyan-300 text-slate-500 transition-opacity p-0.5 cursor-pointer"
                    >
                      <RefreshCw class="w-2.5 h-2.5" />
                    </button>
                  </template>
                  <!-- 未测算状态 -->
                  <template v-else>
                    <span class="text-slate-400">目录</span>
                    <button
                      type="button"
                      @click.stop="recalculateSingleDir(file.path)"
                      title="异步测算此文件夹真实体积"
                      class="opacity-0 group-hover:opacity-100 text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 transition-opacity cursor-pointer inline-flex items-center gap-0.5"
                    >
                      <Zap class="w-2.5 h-2.5" />
                      <span>测算</span>
                    </button>
                  </template>
                </div>
                <div class="text-[10px] text-slate-500">{{ file.modifiedAt }}</div>
              </td>
              <td class="py-2.5 px-3 text-right whitespace-nowrap">
                <div class="inline-flex items-center gap-1 justify-end">
                  <!-- 目录进入 / 文件编辑 -->
                  <button
                    v-if="file.isDir"
                    type="button"
                    @click.stop="jumpToDir(file.path)"
                    class="px-2 py-1 rounded bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 text-[11px] font-medium cursor-pointer"
                  >
                    进入
                  </button>
                  <button
                    v-else
                    type="button"
                    @click.stop="openFileInEditor(file.path)"
                    class="px-2 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-[11px] font-medium cursor-pointer"
                  >
                    编辑
                  </button>

                  <!-- 归档文件一键解压 -->
                  <button
                    v-if="!file.isDir && isArchiveFile(file.name)"
                    type="button"
                    @click.stop="extractArchive(file)"
                    title="解压到当前目录"
                    class="px-2 py-1 rounded bg-purple-500/15 hover:bg-purple-500/25 text-purple-300 border border-purple-500/30 text-[11px] cursor-pointer flex items-center gap-0.5"
                  >
                    <PackageOpen class="w-3 h-3" />
                    <span>解压</span>
                  </button>

                  <!-- 下载文件或打包下载目录 -->
                  <button
                    type="button"
                    @click.stop="downloadRemoteEntry(file)"
                    :title="file.isDir ? '将目录打包为 .tar.gz 下载' : '下载文件到本地'"
                    class="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-cyan-300 cursor-pointer"
                  >
                    <Download class="w-3.5 h-3.5" />
                  </button>

                  <!-- 复制副本 (仅文件) -->
                  <button
                    v-if="!file.isDir"
                    type="button"
                    @click.stop="duplicateFile(file)"
                    title="在当前目录复制一份副本"
                    class="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-emerald-300 cursor-pointer"
                  >
                    <Copy class="w-3.5 h-3.5" />
                  </button>

                  <!-- 重命名 / 移动 -->
                  <button
                    type="button"
                    @click.stop="openActionDialog('rename', file)"
                    title="重命名或移动路径"
                    class="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-amber-300 cursor-pointer"
                  >
                    <Edit3 class="w-3.5 h-3.5" />
                  </button>

                  <!-- 删除 -->
                  <button
                    type="button"
                    @click.stop="openActionDialog('delete', file)"
                    title="删除此项目"
                    class="p-1.5 rounded bg-slate-800 hover:bg-rose-500/20 text-slate-400 hover:text-rose-300 cursor-pointer"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </td>
            </tr>

            <tr v-if="!store.filesLoading && filteredFiles.length === 0">
              <td colspan="6" class="py-10 text-center text-slate-400 text-xs">
                {{
                  store.filesError
                    ? store.filesError
                    : searchQuery
                      ? `未找到匹配「${searchQuery}」的文件`
                      : '当前目录为空'
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 右侧：九宫格可视化 Chmod / Chown 权限计算器 -->
    <div class="w-72 bg-slate-900/90 border border-slate-800 rounded-xl p-4 flex flex-col justify-between shrink-0 overflow-y-auto">
      <div class="space-y-3.5">
        <div class="flex items-center gap-2 text-xs font-bold text-slate-100 border-b border-slate-800 pb-2.5">
          <Shield class="w-4 h-4 text-cyan-400" />
          <span>权限与归属管理 (chmod/chown)</span>
        </div>

        <div v-if="selectedFileForChmod" class="space-y-3 text-xs">
          <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 font-mono">
            <div class="flex items-center justify-between text-[10px] text-slate-400">
              <span>当前选中目标：</span>
              <span>{{ selectedFileForChmod.isDir ? '目录' : formatSize(selectedFileForChmod.sizeBytes) }}</span>
            </div>
            <div class="text-cyan-300 truncate mt-0.5 font-semibold" :title="selectedFileForChmod.path">
              {{ selectedFileForChmod.name }}
            </div>
            <div class="text-[10px] text-slate-500 truncate">{{ selectedFileForChmod.path }}</div>
          </div>

          <!-- 快捷预设按钮 -->
          <div class="grid grid-cols-4 gap-1.5 text-[11px] font-mono">
            <button
              type="button"
              @click="setQuickOctalPreset('0644')"
              class="py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer border border-slate-700"
            >
              0644
            </button>
            <button
              type="button"
              @click="setQuickOctalPreset('0755')"
              class="py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer border border-slate-700"
            >
              0755
            </button>
            <button
              type="button"
              @click="setQuickOctalPreset('0600')"
              class="py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer border border-slate-700"
            >
              0600
            </button>
            <button
              type="button"
              @click="setQuickOctalPreset('0777')"
              class="py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer border border-slate-700"
            >
              0777
            </button>
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

          <!-- 所有者与用户组 (chown) -->
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] text-slate-400 mb-1">所有者 (Owner)</label>
              <input
                v-model="chownOwner"
                type="text"
                aria-label="文件所有者"
                class="w-full px-2 py-1 rounded bg-slate-950 border border-slate-800 font-mono text-xs text-slate-200 focus:border-cyan-500/60 focus:outline-none"
              />
            </div>
            <div>
              <label class="block text-[10px] text-slate-400 mb-1">用户组 (Group)</label>
              <input
                v-model="chownGroup"
                type="text"
                aria-label="文件用户组"
                class="w-full px-2 py-1 rounded bg-slate-950 border border-slate-800 font-mono text-xs text-slate-200 focus:border-cyan-500/60 focus:outline-none"
              />
            </div>
          </div>

          <div class="space-y-1.5 pt-1">
            <label class="flex items-center gap-2 text-slate-300 cursor-pointer">
              <input v-model="chmodMatrix.recursive" type="checkbox" class="rounded" />
              <span>递归应用到子目录 (<code>-R</code>)</span>
            </label>
            <label class="flex items-center gap-2 text-amber-300 cursor-pointer">
              <input v-model="chmodMatrix.sudo" type="checkbox" class="rounded" />
              <span>使用 <code>sudo</code> 提权变更权限</span>
            </label>
          </div>
        </div>

        <div v-else class="text-xs text-slate-400 py-8 text-center">
          请在左侧列表中点击选择一个文件或目录以查看并配置权限
        </div>
      </div>

      <div v-if="selectedFileForChmod" class="space-y-2 pt-3 border-t border-slate-800 mt-3">
        <div class="text-[11px] font-mono text-slate-400 bg-slate-950 p-2 rounded border border-slate-800 truncate">
          {{ chmodMatrix.sudo ? 'sudo ' : '' }}chmod {{ chmodMatrix.recursive ? '-R ' : '' }}{{ computedOctal.slice(1) }} {{ selectedFileForChmod.path }}
        </div>
        <button
          type="button"
          :disabled="isApplyingChmod"
          @click="applyChmod"
          class="w-full py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-xs font-semibold text-white cursor-pointer flex items-center justify-center gap-1.5"
        >
          <Loader2 v-if="isApplyingChmod" class="w-3.5 h-3.5 animate-spin" />
          <span>{{ isApplyingChmod ? '正在应用权限...' : '应用权限变更到远端服务器' }}</span>
        </button>
      </div>
    </div>

    <!-- 原生 <dialog> 模态框：新建文件 / 新建文件夹 / 重命名 / 删除确认 -->
    <dialog
      ref="actionDialogRef"
      closedby="any"
      aria-labelledby="file-action-dialog-title"
      class="m-auto w-[440px] max-w-[92vw] rounded-xl bg-slate-900 border border-slate-700 text-slate-100 shadow-2xl p-0 overflow-hidden"
    >
      <div class="px-4 py-3 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
        <h2 id="file-action-dialog-title" class="text-xs font-bold text-slate-100">
          <template v-if="dialogMode === 'touch'">新建远程文件</template>
          <template v-else-if="dialogMode === 'mkdir'">新建远程文件夹</template>
          <template v-else-if="dialogMode === 'rename'">重命名或移动路径</template>
          <template v-else>确认删除远程项目</template>
        </h2>
        <button
          type="button"
          @click="closeActionDialog"
          aria-label="关闭弹窗"
          class="text-slate-400 hover:text-slate-100 cursor-pointer"
        >
          <X class="w-4 h-4" />
        </button>
      </div>

      <form @submit.prevent="submitActionDialog" class="p-4 space-y-3 text-xs">
        <div class="text-[11px] font-mono text-slate-400">
          当前目录: <span class="text-amber-300">{{ currentCwd }}</span>
        </div>

        <template v-if="dialogMode === 'touch' || dialogMode === 'mkdir' || dialogMode === 'rename'">
          <div>
            <label class="block text-slate-300 mb-1 font-medium">
              {{
                dialogMode === 'touch'
                  ? '新文件名称（或相对/绝对路径）'
                  : dialogMode === 'mkdir'
                    ? '新文件夹名称（支持多级 a/b/c）'
                    : '目标新名称或完整路径'
              }}
            </label>
            <input
              v-model="dialogInputName"
              type="text"
              required
              autofocus
              :placeholder="dialogMode === 'touch' ? '例如: app.conf 或 scripts/deploy.sh' : '例如: backups'"
              class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 focus:border-cyan-500 font-mono text-xs text-slate-100 focus:outline-none"
            />
          </div>

          <div v-if="dialogMode === 'mkdir'">
            <label class="block text-slate-300 mb-1 font-medium">初始权限 (Octal)</label>
            <input
              v-model="dialogDirMode"
              type="text"
              class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 font-mono text-xs text-amber-300 focus:outline-none"
            />
          </div>

          <label v-if="dialogMode === 'touch'" class="flex items-center gap-2 text-slate-300 cursor-pointer">
            <input v-model="dialogOpenEditorAfterTouch" type="checkbox" class="rounded" />
            <span>创建后立即在右侧代码编辑器中打开</span>
          </label>
        </template>

        <template v-else-if="dialogMode === 'delete' && dialogTargetFiles.length > 0">
          <div class="p-3 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-200 space-y-2">
            <div class="font-semibold text-xs text-rose-100">
              <template v-if="dialogTargetFiles.length === 1">
                确定要从远端服务器永久删除此{{ dialogTargetFiles[0].isDir ? '目录及其所有子内容' : '文件' }}吗？
              </template>
              <template v-else>
                确定要永久删除以下选中的 {{ dialogTargetFiles.length }} 个文件 / 目录吗？此操作不可逆！
              </template>
            </div>
            <div class="max-h-40 overflow-y-auto space-y-1 font-mono text-[11px] text-rose-300 pr-1 divide-y divide-rose-500/20">
              <div v-for="target in dialogTargetFiles" :key="target.path" class="flex items-center gap-1.5 py-0.5 truncate">
                <span class="text-rose-400 text-xs shrink-0">✕</span>
                <span class="font-medium shrink-0">[{{ target.isDir ? '目录' : '文件' }}]</span>
                <span :title="target.path" class="truncate">{{ target.path }}</span>
              </div>
            </div>
          </div>
        </template>

        <label class="flex items-center gap-2 text-amber-300 cursor-pointer pt-1">
          <input v-model="dialogUseSudo" type="checkbox" class="rounded" />
          <span>使用 <code>sudo</code> 提权执行此操作</span>
        </label>

        <div class="flex items-center justify-end gap-2 pt-3 border-t border-slate-800">
          <button
            type="button"
            @click="closeActionDialog"
            :autofocus="dialogMode === 'delete'"
            class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer"
          >
            取消
          </button>
          <button
            type="submit"
            :disabled="isOperating"
            :class="[
              'px-3.5 py-1.5 rounded-lg font-semibold text-white cursor-pointer flex items-center gap-1.5 disabled:opacity-50',
              dialogMode === 'delete' ? 'bg-rose-600 hover:bg-rose-500' : 'bg-cyan-600 hover:bg-cyan-500'
            ]"
          >
            <Loader2 v-if="isOperating" class="w-3.5 h-3.5 animate-spin" />
            <span>{{ dialogMode === 'delete' ? '确认永久删除' : '确认执行' }}</span>
          </button>
        </div>
      </form>
    </dialog>
  </div>
</template>
