<script setup lang="ts">
import { computed } from 'vue'
import type { DockerContainerItem } from '@/types'

const props = defineProps<{ container: DockerContainerItem }>()

function dateTime(value?: string | null) {
  if (!value || value.startsWith('0001-')) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function yesNo(value?: boolean | null) {
  return value == null ? '未读取' : value ? '是' : '否'
}

const groups = computed(() => {
  const c = props.container
  const restartDescriptions: Record<string, string> = {
    no: '不自动重启', always: '始终重启',
    'unless-stopped': '自动重启，手动停止除外', 'on-failure': '仅异常退出时重启'
  }
  const retries = c.restartMaxRetries ? `，最多 ${c.restartMaxRetries} 次` : '，不限制次数'
  return [
    { title: '运行记录', entries: [
      ['容器 ID', c.id], ['创建时间', dateTime(c.createdAt)],
      ['最近启动', dateTime(c.startedAt)], ['最近退出', dateTime(c.finishedAt)],
      ['退出码', ['exited', 'dead'].includes(c.status) ? c.exitCode ?? '未读取' : '—'],
      ['OOM 终止', yesNo(c.oomKilled)],
      ['Compose 归属', c.composeProject ? `${c.composeProject} / ${c.composeService || '—'}` : '未关联']
    ] },
    { title: '重启与资源限制', entries: [
      ['重启策略', c.restartPolicy ? `${c.restartPolicy} · ${restartDescriptions[c.restartPolicy] || ''}${c.restartPolicy === 'on-failure' ? retries : ''}` : '未读取'],
      ['已自动重启', c.restartCount == null ? '未读取' : `${c.restartCount} 次`],
      ['健康检查', c.healthStatus || '未配置'],
      ['CPU 上限', c.cpuLimit == null ? '未读取' : c.cpuLimit > 0 ? `${Number(c.cpuLimit.toFixed(3))} 核` : '未限制'],
      ['内存上限', c.memoryLimitBytes == null ? '未读取' : c.memoryLimitBytes > 0 ? `${Number((c.memoryLimitBytes / 1024 / 1024).toFixed(1))} MiB` : '未限制'],
      ['CPU 绑核', c.cpusetCpus || '未限制']
    ] },
    { title: '网络与隔离', entries: [
      ['网络模式', c.networkMode || '未读取'],
      ['运行用户', c.runUser || 'root（默认）'],
      ['特权模式', yesNo(c.privileged)], ['只读根文件系统', yesNo(c.readOnlyRootfs)]
    ] }
  ]
})
</script>

<template>
  <div class="rounded-lg border border-slate-800 bg-slate-950 p-4 text-xs">
    <p v-if="!container.detailsAvailable" role="status" class="text-amber-300">
      容器详情未读取，配置状态未知。请刷新重试。
    </p>
    <div v-else class="parameter-groups grid grid-cols-1 gap-5">
      <section v-for="group in groups" :key="group.title" class="min-w-0">
        <h3 class="font-semibold text-slate-100 mb-3">{{ group.title }}</h3>
        <dl class="space-y-2">
          <div v-for="[label, value] in group.entries" :key="String(label)" class="grid grid-cols-[7rem_minmax(0,1fr)] gap-2">
            <dt class="text-slate-400">{{ label }}</dt>
            <dd class="text-slate-200 break-all">{{ value }}</dd>
          </div>
        </dl>
        <div v-if="group.title === '网络与隔离'" class="mt-3 space-y-2">
          <p v-if="container.networkMode === 'host'" class="text-sky-300">共享宿主机网络，无独立容器 IP；端口直接在宿主机监听。</p>
          <p v-else-if="container.networkMode === 'none'" class="text-slate-400">未连接外部网络，仅保留容器回环接口。</p>
          <div v-for="network in container.networks" v-else :key="network.name" class="rounded border border-slate-800 p-2 break-all">
            <div class="font-mono text-sky-300">{{ network.name }}</div>
            <div class="mt-1 text-slate-300">IPv4：{{ network.ipAddress || '未分配' }}</div>
            <div v-if="network.ipv6Address" class="text-slate-300">IPv6：{{ network.ipv6Address }}</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
@container (width >= 700px) {
  .parameter-groups { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (width >= 1050px) {
  .parameter-groups { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
