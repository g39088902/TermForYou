// Run with: node scripts/verify-cron-host-switch.mjs
// Exercise the real store with delayed HTTP responses; no remote host is contacted.
import assert from 'node:assert/strict'
import { setImmediate } from 'node:timers/promises'
import { createServer } from 'vite'

const originalFetch = globalThis.fetch
const requests = []
globalThis.fetch = (url) => {
  if (/\/(inspect|probe)\//.test(String(url))) {
    return new Promise((resolve, reject) => requests.push({ url: String(url), resolve, reject }))
  }
  return Promise.resolve(Response.json({ status: 'error' }))
}

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { store, inspectHost, probeHost } = await vite.ssrLoadModule('/src/stores/workbenchStore.ts')
  const task = (title) => ({ id: title, title, command: `echo ${title}`, engine: 'crontab' })
  const take = (host, kind = 'inspect') => {
    const index = requests.findIndex((r) => r.url.endsWith(`/${kind}/${host}`))
    assert.notEqual(index, -1, `Switching to ${host} must immediately request ${kind}`)
    return requests.splice(index, 1)[0]
  }
  const respond = async (request, data, status = 200) => {
    request.resolve(Response.json(data, { status }))
    await setImmediate()
  }
  store.hosts = ['A', 'B'].map((id) => ({ id, name: id, currentCwd: '/tmp' }))
  assert.deepEqual(store.cronTasks, [], 'No demo tasks on startup')

  store.activeHostId = 'A'
  await respond(take('A'), { status: 'ok', cronTasks: [task('A-task')] })
  assert.equal(store.cronTasks[0].title, 'A-task')

  store.activeHostId = 'B'
  assert.deepEqual(store.cronTasks, [], 'Clear A synchronously when switching to B')
  assert.equal(store.cronTasksLoading, true)
  await respond(take('B'), { status: 'ok', cronTasks: [] })
  assert.deepEqual(store.cronTasks, [], 'An empty crontab is a valid result')
  assert.equal(store.cronTasksLoading, false)
  assert.equal(store.cronTasksError, '')

  store.activeHostId = 'A'
  const oldA = take('A')
  store.activeHostId = 'B'
  const oldB = take('B')
  store.activeHostId = 'A'
  await respond(take('A'), { status: 'ok', cronTasks: [task('latest-A')] })
  await respond(oldB, { status: 'ok', cronTasks: [task('stale-B')] })
  await respond(oldA, { status: 'ok', cronTasks: [task('stale-A')] })
  assert.equal(store.cronTasks[0].title, 'latest-A', 'Ignore old replies even after A → B → A')

  const olderLoad = inspectHost('A')
  const olderRequest = take('A')
  const newerLoad = inspectHost('A')
  await respond(take('A'), { status: 'ok', cronTasks: [task('newest-A')] })
  await newerLoad
  olderRequest.reject(new Error('late network failure'))
  await olderLoad
  assert.equal(store.cronTasks[0].title, 'newest-A', 'A late failure must not clear newer data')
  assert.equal(store.cronTasksError, '')

  for (const [data, status] of [
    [{ status: 'partial', cronTasks: [] }, 200],
    [{ status: 'auth_failed', message: 'Authentication failed' }, 200],
    [{ detail: 'Unavailable' }, 503]
  ]) {
    const load = inspectHost('A')
    await respond(take('A'), data, status)
    await load
    assert.deepEqual(store.cronTasks, [])
    assert.ok(store.cronTasksError, 'A failed/partial inspection must not look like an empty crontab')
    assert.equal(store.cronTasksLoading, false)
  }

  const retry = inspectHost('A')
  await respond(take('A'), { status: 'ok', cronTasks: [task('recovered-A')] })
  await retry
  assert.equal(store.cronTasksError, '')
  assert.equal(store.cronTasks[0].title, 'recovered-A')

  const background = probeHost('B')
  await respond(take('B', 'probe'), {
    online: true, inspection: { status: 'ok', cronTasks: [task('background-B')] }
  })
  await background
  assert.equal(store.cronTasks[0].title, 'recovered-A', 'A background probe cannot replace active tasks')

  const probe = probeHost('A')
  await respond(take('A', 'probe'), { online: true, inspection: { status: 'ok', cronTasks: [] } })
  await probe
  assert.deepEqual(store.cronTasks, [], 'The probe path must also accept empty lists')
  assert.equal(store.cronTasksError, '')

  const closingLoad = inspectHost('A')
  const closingRequest = take('A')
  store.activeHostId = ''
  await respond(closingRequest, { status: 'ok', cronTasks: [task('closed-A')] })
  await closingLoad
  assert.deepEqual(store.cronTasks, [])
  assert.equal(store.cronTasksLoading, false)
  console.log('PASS: immediate refresh, empty results, A/B/A switching, response ordering, errors, retry, probes and closing')
} finally {
  await vite.close()
  globalThis.fetch = originalFetch
}
