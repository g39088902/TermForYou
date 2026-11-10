<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  store,
  currentHost,
  navigateWithContext,
  executeTerminalCommand,
  showToast
} from '@/stores/workbenchStore'
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  Lock,
  Plus,
  Star,
  Activity,
  Container
} from 'lucide-vue-next'

const newRule = ref({
  port: store.lastJumpContext?.prefillFirewallPort
    ? String(store.lastJumpContext.prefillFirewallPort)
    : '8080',
  protocol: (store.lastJumpContext?.prefillFirewallProtocol ?? 'tcp') as 'tcp' | 'udp' | 'any',
  sourceCidr: '0.0.0.0/0',
  action: 'ALLOW' as 'ALLOW' | 'DENY',
  comment: store.lastJumpContext?.prefillFirewallComment ?? 'API Core Public Port'
})

// 当从其他页面（如 P2 进程监控 或 P5 Docker）点击未放行端口跳转过来时，自动预填端口号
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

// 生成底层透明防火墙 CLI 命令
const underlyingCliPreview = computed(() => {
  const r = newRule.value
  const actionVerb = r.action === 'ALLOW' ? 'allow' : 'deny'
  if (currentHost.value.firewallBackend === 'ufw') {
    const fromPart = r.sourceCidr === '0.0.0.0/0' ? 'any' : r.sourceCidr
    return `sudo ufw ${actionVerb} from ${fromPart} to any port ${r.port} proto ${r.protocol} comment '${r.comment}'`
  }
  if (currentHost.value.firewallBackend === 'firewalld') {
    if (r.action === 'ALLOW') {
      return `sudo firewall-cmd --permanent --add-port=${r.port}/${r.protocol} && sudo firewall-cmd --reload`
    }
    return `sudo firewall-cmd --permanent --remove-port=${r.port}/${r.protocol} && sudo firewall-cmd --reload`
  }
  return `sudo iptables -A INPUT -p ${r.protocol} --dport ${r.port} -s ${r.sourceCidr} -j ${r.action === 'ALLOW' ? 'ACCEPT' : 'DROP'}`
})

// 计算「服务器实际监听端口 vs 防火墙放行规则」全景对照矩阵
const portComparisonMatrix = computed(() => {
  return store.processes
    .filter((p) => p.listenPort)
    .map((p) => ({
      port: p.listenPort!,
      protocol: p.protocol ?? 'tcp',
      processName: p.name,
      pid: p.pid,
      isDocker: Boolean(p.dockerContainerId),
      dockerId: p.dockerContainerId,
      allowed: Boolean(p.firewallAllowed)
    }))
})

function applyNewFirewallRule() {
  const portNum = Number(newRule.value.port)
  const matchingProc = store.processes.find((p) => p.listenPort === portNum)
  if (matchingProc && newRule.value.action === 'ALLOW') {
    matchingProc.firewallAllowed = true
  }

  for (const c of store.dockerContainers) {
    for (const pt of c.ports) {
      if (pt.hostPort === portNum && newRule.value.action === 'ALLOW') {
        pt.firewallAllowed = true
      }
    }
  }

  store.firewallRules.unshift({
    id: `fw-${Date.now()}`,
    port: newRule.value.port,
    protocol: newRule.value.protocol,
    sourceCidr: newRule.value.sourceCidr,
    action: newRule.value.action,
    comment: newRule.value.comment,
    enabled: true,
    listeningProcess: matchingProc
      ? { pid: matchingProc.pid, name: matchingProc.name, type: 'process' }
      : undefined
  })

  executeTerminalCommand(underlyingCliPreview.value)
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
                  ? 'bg-emerald-950/60 border-emerald-700/60 text-emerald-300'
                  : 'bg-rose-950/60 border-rose-700/60 text-rose-300'
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

        <div class="flex items-center gap-2 px-3 py-1 rounded-lg bg-emerald-950/60 border border-emerald-700/50 text-xs text-emerald-300">
          <Lock class="w-3.5 h-3.5" />
          <span>保护规则：当前 SSH 端口 (:{{ currentHost.port }}) 保持锁定放行</span>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <div
          v-for="item in portComparisonMatrix"
          :key="item.port"
          :class="[
            'p-3 rounded-xl border flex flex-col justify-between gap-2 transition',
            item.allowed
              ? 'bg-slate-950/80 border-emerald-500/30'
              : 'bg-amber-950/25 border-amber-500/50'
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
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-amber-500/20 text-amber-300'
              ]"
            >
              <ShieldCheck v-if="item.allowed" class="w-3 h-3" />
              <ShieldAlert v-else class="w-3 h-3" />
              {{ item.allowed ? '已监听 & 已放行' : '已监听但被拦截' }}
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
              v-if="!item.allowed"
              type="button"
              @click="
                () => {
                  newRule.port = String(item.port)
                  newRule.comment = `${item.processName} Port`
                  applyNewFirewallRule()
                }
              "
              class="px-2 py-0.5 rounded bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold cursor-pointer"
            >
              一键立即放行
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 可视化添加防火墙规则 + 底层 CLI 透明预览 -->
    <div class="rounded-xl bg-slate-900/90 border border-cyan-500/30 p-4 space-y-3">
      <div class="text-xs font-bold text-slate-100 flex items-center gap-2">
        <Plus class="w-4 h-4 text-cyan-400" />
        <span>新增入站防火墙规则 (实时生成底层 {{ (currentHost.firewallBackend || 'ufw').toUpperCase() }} 命令)</span>
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
        <div class="font-mono text-xs text-slate-400 truncate">
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
            @click="applyNewFirewallRule"
            class="px-3.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold cursor-pointer"
          >
            立即应用规则
          </button>
        </div>
      </div>
    </div>

    <!-- 3. 现有防火墙规则表 -->
    <div class="rounded-xl bg-slate-900/90 border border-slate-800 overflow-hidden">
      <div tabindex="0" role="region" aria-label="防火墙入站规则列表" class="table-wrapper">
        <table class="text-left text-xs" style="--label-2: '来源网段'; --label-3: '关联监听进程'; --label-4: '备注'">
          <thead class="bg-slate-950 text-slate-400 text-[11px] border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">端口 / 协议</th>
              <th class="py-2.5 px-3">动作</th>
              <th class="py-2.5 px-3">来源 IP / CIDR</th>
              <th class="py-2.5 px-3">关联监听进程 (点击直达)</th>
              <th class="py-2.5 px-3">规则备注说明</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/70">
            <tr
              v-for="rule in store.firewallRules"
              :key="rule.id"
              class="hover:bg-slate-800/50 transition"
            >
              <th class="py-2.5 px-3 font-mono font-bold text-slate-100">
                {{ rule.port }} / {{ rule.protocol.toUpperCase() }}
              </th>
              <td class="py-2.5 px-3">
                <span
                  :class="[
                    'px-2 py-0.5 rounded font-mono text-[10px] font-bold',
                    rule.action === 'ALLOW'
                      ? 'bg-emerald-500/15 text-emerald-300'
                      : 'bg-rose-500/20 text-rose-300'
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
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
