<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  store,
  currentHost,
  navigateWithContext,
  createFirewallRule,
  deleteFirewallRule,
  inspectHost,
  showToast
} from '@/stores/workbenchStore'
import type { FirewallRuleItem } from '@/types'
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  Lock,
  Plus,
  Star,
  Activity,
  Container,
  RefreshCw,
  Trash2,
  Loader2,
  AlertTriangle
} from 'lucide-vue-next'

const useSudo = ref(false)
const deleteDialogRef = ref<HTMLDialogElement | null>(null)
const pendingDeleteRule = ref<FirewallRuleItem | null>(null)

const newRule = ref({
  port: store.lastJumpContext?.prefillFirewallPort
    ? String(store.lastJumpContext.prefillFirewallPort)
    : '8080',
  protocol: (store.lastJumpContext?.prefillFirewallProtocol ?? 'tcp') as 'tcp' | 'udp' | 'any',
  sourceCidr: '0.0.0.0/0',
  action: 'ALLOW' as 'ALLOW' | 'DENY' | 'REJECT',
  comment: store.lastJumpContext?.prefillFirewallComment ?? 'API Core Public Port'
})

// 从进程监控或 Docker 页面点击端口跳转时，自动预填端口号
watch(
  () => store.lastJumpContext,
  (ctx) => {
    if (ctx?.prefillFirewallPort) {
      newRule.value.port = String(ctx.prefillFirewallPort)
      if (ctx.prefillFirewallProtocol) {
        newRule.value.protocol = ctx.prefillFirewallProtocol
      }
      if (ctx.prefillFirewallComment) {
        newRule.value.comment = ctx.prefillFirewallComment
      }
    }
  },
  { immediate: true }
)

// 生成底层透明防火墙 CLI 命令预览
const underlyingCliPreview = computed(() => {
  const r = newRule.value
  const prefix = useSudo.value ? 'sudo -n ' : ''
  const backend = currentHost.value.firewallBackend || 'ufw'

  if (backend === 'ufw') {
    const actionVerb = r.action === 'ALLOW' ? 'allow' : r.action === 'REJECT' ? 'reject' : 'deny'
    const fromPart = !r.sourceCidr || r.sourceCidr === '0.0.0.0/0' ? 'any' : r.sourceCidr
    const protoPart = r.protocol === 'any' ? '' : ` proto ${r.protocol}`
    const commentPart = r.comment.trim() ? ` comment '${r.comment.trim()}'` : ''
    return `${prefix}ufw ${actionVerb} from ${fromPart} to any port ${r.port}${protoPart}${commentPart}`
  }

  if (backend === 'firewalld') {
    const fwdPort = r.port.replace(':', '-')
    const protos = r.protocol === 'any' ? ['tcp', 'udp'] : [r.protocol]
    const cmds = protos.map((p) => `${prefix}firewall-cmd --permanent --add-port=${fwdPort}/${p}`).join(' && ')
    return `${cmds} && ${prefix}firewall-cmd --reload`
  }

  const target = r.action === 'ALLOW' ? 'ACCEPT' : r.action === 'REJECT' ? 'REJECT' : 'DROP'
  const protos = r.protocol === 'any' ? ['tcp', 'udp'] : [r.protocol]
  const srcPart = r.sourceCidr && r.sourceCidr !== '0.0.0.0/0' ? `-s ${r.sourceCidr} ` : ''
  return protos.map((p) => `${prefix}iptables -A INPUT -p ${p} --dport ${r.port} ${srcPart}-j ${target}`).join(' && ')
})

function matchRuleForPort(port: number, protocol: string): boolean | null {
  const matched = store.firewallRules.filter((r) => {
    const protoOk = r.protocol === 'any' || r.protocol === protocol
    if (!protoOk) return false
    if (r.port.includes(':')) {
      const [s, e] = r.port.split(':').map(Number)
      return Number.isInteger(s) && Number.isInteger(e) && port >= s && port <= e
    }
    return Number(r.port) === port
  })
  if (matched.length === 0) return null
  if (matched.some((r) => r.action === 'ALLOW')) return true
  if (matched.some((r) => r.action === 'DENY' || r.action === 'REJECT')) return false
  return null
}

// 计算「服务器实际监听端口 vs 防火墙放行规则」全景对照矩阵
const portComparisonMatrix = computed(() => {
  return store.processes
    .filter((p) => p.listenPort)
    .map((p) => {
      const proto = p.protocol ?? 'tcp'
      const allowed = p.firewallAllowed ?? matchRuleForPort(p.listenPort!, proto)
      return {
        port: p.listenPort!,
        protocol: proto,
        processName: p.name,
        pid: p.pid,
        isDocker: Boolean(p.dockerContainerId),
        dockerId: p.dockerContainerId,
        allowed
      }
    })
})

async function applyNewFirewallRule() {
  if (!newRule.value.port.trim()) {
    showToast('请输入端口号或端口段')
    return
  }
  await createFirewallRule({
    port: newRule.value.port.trim(),
    protocol: newRule.value.protocol,
    sourceCidr: newRule.value.sourceCidr.trim() || '0.0.0.0/0',
    action: newRule.value.action,
    comment: newRule.value.comment.trim(),
    sudo: useSudo.value,
    backend: currentHost.value.firewallBackend
  })
}

async function handleAllowListeningPort(item: { port: number; protocol: string; processName: string }) {
  newRule.value.port = String(item.port)
  newRule.value.protocol = (item.protocol === 'udp' ? 'udp' : 'tcp') as 'tcp' | 'udp'
  newRule.value.action = 'ALLOW'
  newRule.value.comment = `${item.processName} Port`
  await applyNewFirewallRule()
}

function isSshPortRule(rule: FirewallRuleItem): boolean {
  const sshPort = Number(currentHost.value.port || 22)
  if (rule.port.includes(':')) {
    const [s, e] = rule.port.split(':').map(Number)
    return Number.isInteger(s) && Number.isInteger(e) && sshPort >= s && sshPort <= e
  }
  return Number(rule.port) === sshPort
}

function openDeleteDialog(rule: FirewallRuleItem) {
  pendingDeleteRule.value = rule
  deleteDialogRef.value?.showModal()
}

function closeDeleteDialog() {
  deleteDialogRef.value?.close()
  pendingDeleteRule.value = null
}

async function confirmDeleteRule() {
  const target = pendingDeleteRule.value
  if (!target) return
  const ok = await deleteFirewallRule(target, useSudo.value)
  if (ok) {
    closeDeleteDialog()
  }
}

function saveFirewallRuleToSnippets() {
  store.savedSnippets.unshift({
    id: `snip-fw-${Date.now()}`,
    title: `防火墙放行端口 ${newRule.value.port} (${newRule.value.comment})`,
    category: '网络与端口排查',
    commandTemplate: underlyingCliPreview.value,
    description: '防火墙放行规则',
    variables: [],
    scope: currentHost.value.id,
    usageCount: 1,
    source: 'gui-saved'
  })
  showToast('已将该命令保存至常用命令库！')
}
</script>

<template>
  <div class="p-5 space-y-5 overflow-y-auto h-full">
    <!-- 1. 「实际监听端口 vs 防火墙放行状态」对照矩阵 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 class="text-sm font-bold text-slate-100 flex items-center gap-2">
            <Shield class="w-4 h-4 text-cyan-400" />
            <span>端口监听与防火墙对照 ({{ (currentHost.firewallBackend || '待探测').toUpperCase() }})</span>
            <span
              v-if="currentHost.firewallBackend"
              :class="[
                'text-[10px] font-mono px-2 py-0.5 rounded-full border flex items-center gap-1',
                currentHost.firewallEnabled
                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                  : 'bg-rose-500/15 border-rose-500/30 text-rose-700 dark:text-rose-300'
              ]"
            >
              <ShieldCheck v-if="currentHost.firewallEnabled" class="w-3 h-3" />
              <ShieldAlert v-else class="w-3 h-3" />
              {{ currentHost.firewallEnabled ? '服务运行中' : '未开启 / 已停止' }}
            </span>
            <span
              v-else
              class="text-[10px] font-mono px-2 py-0.5 rounded-full border flex items-center gap-1 bg-slate-800 text-slate-400 border-slate-700"
            >
              <ShieldAlert class="w-3 h-3 opacity-50" />
              未检测
            </span>
          </h1>
          <p class="text-xs text-slate-400 mt-0.5">
            实时比对本地服务监听端口与防火墙规则放行状态。
          </p>
        </div>

        <div class="flex items-center gap-2">
          <div class="flex items-center gap-2 px-3 py-1 rounded-lg bg-emerald-950/60 border border-emerald-700/50 text-xs text-emerald-300">
            <Lock class="w-3.5 h-3.5" />
            <span>保护规则：当前 SSH 端口 (:{{ currentHost.port }}) 保持锁定放行</span>
          </div>

          <button
            type="button"
            :disabled="!currentHost.id || store.firewallRulesLoading"
            @click="currentHost.id && inspectHost(currentHost.id)"
            class="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-xs cursor-pointer"
          >
            <RefreshCw :class="['w-3.5 h-3.5', store.firewallRulesLoading && 'animate-spin']" />
            <span>刷新</span>
          </button>
        </div>
      </div>

      <div v-if="portComparisonMatrix.length === 0" class="text-xs text-slate-500 py-3 text-center">
        暂无监听端口数据，请先探测或刷新当前主机。
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <div
          v-for="item in portComparisonMatrix"
          :key="`${item.pid}-${item.port}-${item.protocol}`"
          :class="[
            'p-3 rounded-xl border flex flex-col justify-between gap-2 transition',
            item.allowed
              ? 'bg-slate-950/80 border-emerald-500/30'
              : item.allowed === false ? 'bg-amber-950/25 border-amber-500/50' : 'bg-slate-950/80 border-slate-700'
          ]"
        >
          <div class="flex items-start justify-between">
            <div>
              <span class="font-mono text-sm font-bold text-slate-100">
                :{{ item.port }} / {{ item.protocol.toUpperCase() }}
              </span>
              <div class="text-xs text-slate-300 mt-0.5">
                进程: <strong>{{ item.processName }}</strong> (PID {{ item.pid }})
              </div>
            </div>

            <span
              :class="[
                'px-2 py-0.5 rounded-full text-[10px] font-semibold flex items-center gap-1',
                item.allowed
                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                  : item.allowed === false
                    ? 'bg-amber-500/15 text-amber-800 dark:text-amber-200'
                    : 'bg-slate-500/15 text-slate-600 dark:text-slate-300'
              ]"
            >
              <ShieldCheck v-if="item.allowed" class="w-3 h-3" />
              <ShieldAlert v-else class="w-3 h-3" />
              {{ item.allowed ? '已监听 & 已放行' : item.allowed === false ? '已监听但被拦截' : '已监听 · 规则未匹配' }}
            </span>
          </div>

          <div class="flex items-center justify-between pt-2 border-t border-slate-800/80 text-[11px]">
            <button
              type="button"
              @click="
                navigateWithContext({
                  sourcePage: 'P8_FIREWALL',
                  targetPage: item.isDocker ? 'P5_DOCKER' : 'P2_METRICS_PROCESS',
                  reason: `从防火墙端口 :${item.port} 反查进程 ${item.processName} (PID ${item.pid})`,
                  highlightPid: item.pid,
                  filterContainer: item.dockerId
                })
              "
              class="text-cyan-400 hover:underline flex items-center gap-1 cursor-pointer"
            >
              <Container v-if="item.isDocker" class="w-3 h-3" />
              <Activity v-else class="w-3 h-3" />
              <span>跳转定位该进程/容器</span>
            </button>

            <button
              v-if="item.allowed !== true"
              type="button"
              :disabled="store.firewallMutating"
              @click="handleAllowListeningPort(item)"
              class="px-2 py-0.5 rounded bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-slate-950 font-bold cursor-pointer"
            >
              放行端口
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 可视化添加防火墙规则 + 底层 CLI 透明预览 -->
    <div class="rounded-xl bg-slate-900/90 border border-cyan-500/30 p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="text-xs font-bold text-slate-100 flex items-center gap-2">
          <Plus class="w-4 h-4 text-cyan-400" />
          <span>新增入站防火墙规则 (实时生成底层 {{ (currentHost.firewallBackend || 'ufw').toUpperCase() }} 命令)</span>
        </div>

        <label class="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer select-none">
          <input
            v-model="useSudo"
            type="checkbox"
            class="rounded border-slate-600 bg-slate-950 text-cyan-500 focus:ring-cyan-500"
          />
          <span>使用 <code class="font-mono text-amber-300">sudo -n</code> 提权执行</span>
        </label>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-5 gap-3 text-xs">
        <div>
          <label class="text-slate-400 block mb-1">端口 / 端口段</label>
          <input
            v-model="newRule.port"
            type="text"
            placeholder="如 8080 或 8000:8010"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 font-mono text-slate-100"
          />
        </div>
        <div>
          <label class="text-slate-400 block mb-1">协议类型</label>
          <select
            v-model="newRule.protocol"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-100"
          >
            <option value="tcp">TCP</option>
            <option value="udp">UDP</option>
            <option value="any">TCP + UDP</option>
          </select>
        </div>
        <div>
          <label class="text-slate-400 block mb-1">授权来源 IP / CIDR</label>
          <input
            v-model="newRule.sourceCidr"
            type="text"
            placeholder="0.0.0.0/0 或指定网段"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 font-mono text-cyan-300"
          />
        </div>
        <div>
          <label class="text-slate-400 block mb-1">策略动作</label>
          <select
            v-model="newRule.action"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-100"
          >
            <option value="ALLOW">ALLOW (允许入站)</option>
            <option value="DENY">DENY (丢弃拦截)</option>
            <option value="REJECT">REJECT (拒绝响应)</option>
          </select>
        </div>
        <div>
          <label class="text-slate-400 block mb-1">规则业务备注</label>
          <input
            v-model="newRule.comment"
            type="text"
            class="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-100"
          />
        </div>
      </div>

      <!-- GUI 到底层 CLI 透明映射栏 -->
      <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex flex-wrap items-center justify-between gap-2">
        <div class="font-mono text-xs text-slate-400 truncate max-w-full">
          <span>[&gt;_ 预览底层命令] </span>
          <span class="text-cyan-300">{{ underlyingCliPreview }}</span>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <button
            type="button"
            @click="saveFirewallRuleToSnippets"
            class="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-amber-300 text-xs cursor-pointer"
          >
            <Star class="w-3.5 h-3.5" />
            <span>存为常用命令</span>
          </button>

          <button
            type="button"
            :disabled="store.firewallMutating || !currentHost.id"
            @click="applyNewFirewallRule"
            class="flex items-center gap-1.5 px-3.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-xs font-semibold cursor-pointer"
          >
            <Loader2 v-if="store.firewallMutating" class="w-3.5 h-3.5 animate-spin" />
            <span>{{ store.firewallMutating ? '应用中...' : '立即应用规则' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 3. 现有防火墙规则表 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 overflow-hidden">
      <div v-if="store.firewallRulesLoading && store.firewallRules.length === 0" class="p-8 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
        <Loader2 class="w-4 h-4 animate-spin text-cyan-400" />
        <span>正在读取远端防火墙规则...</span>
      </div>

      <div v-else-if="store.firewallRulesError && store.firewallRules.length === 0" class="p-8 text-center space-y-2">
        <p class="text-xs text-rose-400">{{ store.firewallRulesError }}</p>
        <button
          type="button"
          :disabled="!currentHost.id"
          @click="currentHost.id && inspectHost(currentHost.id)"
          class="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
        >
          重试读取
        </button>
      </div>

      <div v-else-if="store.firewallRules.length === 0" class="p-8 text-center text-xs text-slate-500">
        当前主机暂未检测到激活的入站防火墙规则（非 root 用户运行 ufw 时可能需要更高权限查看，或当前防火墙未配置规则）。
      </div>

      <div v-else tabindex="0" role="region" aria-label="防火墙入站规则列表" class="table-wrapper">
        <table class="text-left text-xs w-full" style="--label-2: '来源网段'; --label-3: '关联监听进程'; --label-4: '备注'">
          <thead class="bg-slate-950 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">端口 / 协议</th>
              <th class="py-2.5 px-3">动作</th>
              <th class="py-2.5 px-3">来源 IP / CIDR</th>
              <th class="py-2.5 px-3">关联监听进程 (点击直达)</th>
              <th class="py-2.5 px-3">规则备注说明</th>
              <th class="py-2.5 px-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/70">
            <tr
              v-for="rule in store.firewallRules"
              :key="rule.id"
              class="hover:bg-slate-800/50 transition"
            >
              <th class="py-2.5 px-3 font-mono font-bold text-slate-100">
                <span v-if="rule.ruleNumber" class="text-slate-500 mr-1.5">#{{ rule.ruleNumber }}</span>
                {{ rule.port }} / {{ rule.protocol.toUpperCase() }}
              </th>
              <td class="py-2.5 px-3">
                <span
                  :class="[
                    'px-2 py-0.5 rounded font-mono text-[10px] font-bold',
                    rule.action === 'ALLOW'
                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                      : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
                  ]"
                >
                  {{ rule.action }}
                </span>
              </td>
              <td class="py-2.5 px-3 font-mono text-cyan-300">{{ rule.sourceCidr }}</td>
              <td class="py-2.5 px-3">
                <button
                  v-if="rule.listeningProcess"
                  type="button"
                  @click="
                    navigateWithContext({
                      sourcePage: 'P8_FIREWALL',
                      targetPage:
                        rule.listeningProcess.type === 'docker'
                          ? 'P5_DOCKER'
                          : 'P2_METRICS_PROCESS',
                      reason: `从防火墙规则反查监听进程 ${rule.listeningProcess.name}`,
                      highlightPid: rule.listeningProcess.pid,
                      filterContainer: rule.listeningProcess.targetId
                    })
                  "
                  class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-emerald-300 font-mono text-[11px] cursor-pointer"
                >
                  {{ rule.listeningProcess.name }} (PID {{ rule.listeningProcess.pid }}) →
                </button>
                <span
                  v-else
                  class="px-2 py-0.5 rounded bg-slate-950 text-slate-500 text-[11px]"
                >
                  当前无服务监听此端口
                </span>
              </td>
              <td class="py-2.5 px-3 text-slate-300">{{ rule.comment }}</td>
              <td class="py-2.5 px-3 text-right">
                <button
                  type="button"
                  :disabled="store.firewallDeletingId === rule.id"
                  @click="openDeleteDialog(rule)"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded bg-rose-500/15 hover:bg-rose-500/25 disabled:opacity-50 text-rose-700 dark:text-rose-300 text-[11px] font-medium cursor-pointer"
                >
                  <Loader2 v-if="store.firewallDeletingId === rule.id" class="w-3 h-3 animate-spin" />
                  <Trash2 v-else class="w-3 h-3" />
                  <span>删除</span>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 删除确认弹窗 -->
    <dialog
      ref="deleteDialogRef"
      class="rounded-xl bg-slate-900 border border-slate-700 text-slate-100 p-0 backdrop:bg-slate-950/75 max-w-md w-full m-auto shadow-2xl"
      @cancel.prevent="closeDeleteDialog"
    >
      <div v-if="pendingDeleteRule" class="p-5 space-y-4">
        <div class="flex items-start gap-3">
          <div class="p-2 rounded-lg bg-rose-500/15 text-rose-400 shrink-0">
            <AlertTriangle class="w-5 h-5" />
          </div>
          <div class="space-y-1">
            <h3 class="text-sm font-bold text-slate-100">确认删除防火墙规则？</h3>
            <p class="text-xs text-slate-400">
              将从目标主机 ({{ (pendingDeleteRule.backend || currentHost.firewallBackend || 'firewall').toUpperCase() }}) 永久移除以下规则：
            </p>
            <div class="mt-2 p-2.5 rounded-lg bg-slate-950 border border-slate-800 font-mono text-xs text-slate-200">
              {{ pendingDeleteRule.action }} {{ pendingDeleteRule.port }}/{{ pendingDeleteRule.protocol.toUpperCase() }}
              <span class="text-slate-400">from</span> {{ pendingDeleteRule.sourceCidr }}
            </div>
          </div>
        </div>

        <div
          v-if="isSshPortRule(pendingDeleteRule)"
          class="p-2.5 rounded-lg bg-amber-500/15 border border-amber-500/40 text-xs text-amber-800 dark:text-amber-200"
        >
          警告：该规则涉及当前主机 SSH 管理端口 (:{{ currentHost.port }})，删除后若无其他放行规则可能导致当前 SSH 连接中断或无法重连！
        </div>

        <div class="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            @click="closeDeleteDialog"
            class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 cursor-pointer"
          >
            取消
          </button>
          <button
            type="button"
            :disabled="store.firewallDeletingId === pendingDeleteRule.id"
            @click="confirmDeleteRule"
            class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-xs font-semibold text-white cursor-pointer"
          >
            <Loader2 v-if="store.firewallDeletingId === pendingDeleteRule.id" class="w-3.5 h-3.5 animate-spin" />
            <span>确认删除</span>
          </button>
        </div>
      </div>
    </dialog>
  </div>
</template>
