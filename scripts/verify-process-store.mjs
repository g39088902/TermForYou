// Run: node scripts/verify-process-store.mjs. No remote hosts are contacted.
import assert from 'node:assert/strict'
import { setImmediate } from 'node:timers/promises'
import { createServer } from 'vite'
const originalFetch = globalThis.fetch
const pending = []
globalThis.fetch = (url, options) => /\/(inspect|processes)\//.test(String(url))
  ? new Promise((resolve, reject) => pending.push({ url: String(url), options, resolve, reject }))
  : Promise.resolve(Response.json({ status: 'error' }))
const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { store, refreshProcesses, signalProcess } = await vite.ssrLoadModule('/src/stores/workbenchStore.ts')
  const take = suffix => {
    const index = pending.findIndex(r => r.url.endsWith(suffix))
    assert.notEqual(index, -1, suffix)
    return pending.splice(index, 1)[0]
  }
  const respond = async (r, data) => { r.resolve(Response.json(data)); await setImmediate() }
  const proc = { pid: 42, identity: '11111111-1111-1111-1111-111111111111:999', state: 'S', name: 'test' }
  const snapshot = processes => ({ status: 'ok', processes })
  const inspection = processes => ({ ...snapshot(processes), cronTasks: [], dockerContainers: [] })
  store.hosts = ['A', 'B'].map(id => ({ id, name: id, currentCwd: '/tmp' }))
  assert.deepEqual(store.processes, [])
  store.activeHostId = 'A'
  await respond(take('/inspect/A'), inspection([proc]))
  assert.equal(await signalProcess({ ...proc, pid: 1 }, 'SIGKILL'), false)
  assert.equal(await signalProcess({ ...proc, identity: undefined }, 'SIGTERM'), false)

  const operation = signalProcess(proc, 'SIGTERM')
  const request = take('/processes/A/kill')
  assert.deepEqual(JSON.parse(request.options.body), { pid: 42, identity: proc.identity, signal: 'SIGTERM', sudo: false })
  assert.equal(await signalProcess(proc, 'SIGKILL'), false)
  await respond(request, { status: 'ok', message: 'sent' })
  assert.equal(store.processes.length, 1, 'Do not remove a process based on signal delivery alone')
  await respond(take('/processes/A'), snapshot([]))
  assert.equal(await operation, true)
  assert.deepEqual(store.processes, [])
  assert.deepEqual(store.processActions, {})

  const load = refreshProcesses()
  await respond(take('/processes/A'), snapshot([proc]))
  await load
  const failed = signalProcess(proc, 'SIGKILL', true)
  const failedRequest = take('/processes/A/kill')
  assert.equal(JSON.parse(failedRequest.options.body).sudo, true)
  await respond(failedRequest, { status: 'error', message: 'permission denied' })
  await respond(take('/processes/A'), snapshot([proc]))
  assert.equal(await failed, false)
  assert.equal(store.processes[0].pid, 42)
  assert.deepEqual(store.processActions, {})

  const old = refreshProcesses()
  const stale = take('/processes/A')
  const current = refreshProcesses()
  await respond(take('/processes/A'), snapshot([]))
  await respond(stale, snapshot([proc]))
  await Promise.all([old, current])
  assert.deepEqual(store.processes, [])

  const reload = refreshProcesses()
  await respond(take('/processes/A'), snapshot([proc]))
  await reload
  const switched = signalProcess(proc, 'SIGTERM')
  const switchedRequest = take('/processes/A/kill')
  store.activeHostId = 'B'
  assert.deepEqual(store.processes, [])
  await respond(take('/inspect/B'), inspection([]))
  await respond(switchedRequest, { status: 'ok', message: 'old A sent' })
  await switched
  assert.deepEqual(store.processes, [])
  assert.equal(pending.length, 0)

  store.activeHostId = 'A'
  const full = take('/inspect/A')
  const newer = refreshProcesses()
  await respond(take('/processes/A'), snapshot([]))
  await newer
  await respond(full, inspection([proc]))
  assert.deepEqual(store.processes, [], 'Old full inspection cannot overwrite newer process query')
  const errorLoad = refreshProcesses()
  take('/processes/A').reject(new Error('network failure'))
  assert.equal(await errorLoad, false)
  assert.equal(store.processesLoading, false)
  assert.equal(store.processesError, 'network failure')
  const retry = refreshProcesses()
  await respond(take('/processes/A'), snapshot([proc]))
  assert.equal(await retry, true)
  assert.equal(store.processesError, '')

  const uncertain = signalProcess(proc, 'SIGKILL')
  take('/processes/A/kill').reject(new Error('network failure'))
  await setImmediate()
  await respond(take('/processes/A'), snapshot([proc]))
  assert.equal(await uncertain, false)
  assert.deepEqual(store.processActions, {})
  store.activeHostId = ''
  console.log('PASS: Process signals, explicit sudo, conflicts, real-state refresh, failures, empty lists, host and request isolation')
} finally {
  await vite.close()
  globalThis.fetch = originalFetch
}
