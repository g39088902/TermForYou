// Run: node scripts/verify-docker-store.mjs. No remote hosts are contacted.
import assert from 'node:assert/strict'
import { setImmediate } from 'node:timers/promises'
import { createServer } from 'vite'

const originalFetch = globalThis.fetch
const pending = []
globalThis.fetch = (url, options) => {
  if (/\/(inspect|docker)\//.test(String(url))) {
    return new Promise((resolve, reject) => pending.push({ url: String(url), options, resolve, reject }))
  }
  return Promise.resolve(Response.json({ status: 'error' }))
}
const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { store, restartDockerContainer, controlDockerContainer } = await vite.ssrLoadModule('/src/stores/workbenchStore.ts')
  const take = (suffix) => {
    const index = pending.findIndex((r) => r.url.endsWith(suffix))
    assert.notEqual(index, -1, suffix)
    return pending.splice(index, 1)[0]
  }
  const respond = async (request, body) => {
    request.resolve(Response.json(body))
    await setImmediate()
  }
  const inspection = (ids) => ({ status: 'ok', cronTasks: [], dockerContainers: ids.map((id) => ({ id, name: id, status: 'running' })) })
  store.hosts = ['A', 'B'].map((id) => ({ id, name: id, currentCwd: '/tmp' }))
  assert.deepEqual(store.dockerContainers, [])
  store.activeHostId = 'A'
  await respond(take('/inspect/A'), inspection(['a']))

  const restart = restartDockerContainer('a')
  const request = take('/docker/A/containers/a/restart')
  assert.equal(JSON.parse(request.options.body).sudo, false)
  assert.deepEqual(store.dockerContainerActions, { 'A/a': 'restart' })
  assert.equal(await restartDockerContainer('a'), false, 'Block duplicate restart')
  assert.equal(await controlDockerContainer('a', 'stop'), false, 'Block a conflicting stop during restart')
  await respond(request, { status: 'ok' })
  await respond(take('/inspect/A'), inspection(['a']))
  assert.equal(await restart, true)
  assert.deepEqual(store.dockerContainerActions, {})

  const failed = restartDockerContainer('a', true)
  const failureRequest = take('/docker/A/containers/a/restart')
  assert.equal(JSON.parse(failureRequest.options.body).sudo, true)
  await respond(failureRequest, { status: 'error', message: 'permission denied' })
  assert.equal(await failed, false)
  assert.equal(store.dockerContainers[0].status, 'running', 'Do not fabricate state after failure')
  assert.deepEqual(store.dockerContainerActions, {})

  for (const action of ['stop', 'start']) {
    const operation = controlDockerContainer('a', action, action === 'start')
    const actionRequest = take('/docker/A/containers/a/action')
    assert.deepEqual(JSON.parse(actionRequest.options.body), { action, sudo: action === 'start' })
    assert.equal(store.dockerContainerActions['A/a'], action)
    assert.equal(await controlDockerContainer('a', 'restart'), false, 'Block conflicting actions')
    await respond(actionRequest, { status: 'ok', action })
    const refreshed = inspection(['a'])
    refreshed.dockerContainers[0].status = action === 'stop' ? 'exited' : 'running'
    await respond(take('/inspect/A'), refreshed)
    assert.equal(await operation, true)
    assert.equal(store.dockerContainers[0].status, refreshed.dockerContainers[0].status)
    assert.deepEqual(store.dockerContainerActions, {})
  }

  const failedStop = controlDockerContainer('a', 'stop')
  await respond(take('/docker/A/containers/a/action'), { status: 'error', message: 'permission denied' })
  assert.equal(await failedStop, false)
  assert.equal(store.dockerContainers[0].status, 'running', 'Failed stop must not fabricate an exited state')
  assert.deepEqual(store.dockerContainerActions, {})

  const interruptedStart = controlDockerContainer('a', 'start')
  take('/docker/A/containers/a/action').reject(new Error('network failure'))
  assert.equal(await interruptedStart, false)
  assert.deepEqual(store.dockerContainerActions, {})

  const switchingRestart = restartDockerContainer('a')
  const switchingRequest = take('/docker/A/containers/a/restart')
  store.activeHostId = 'B'
  assert.deepEqual(store.dockerContainers, [], 'Clear old host immediately')
  await respond(take('/inspect/B'), inspection(['b']))
  await respond(switchingRequest, { status: 'ok' })
  await switchingRestart
  assert.equal(store.dockerContainers[0].id, 'b', 'Late restart result must not mutate new host')
  assert.equal(pending.length, 0, 'Late restart does not start inspection for another host')

  store.activeHostId = 'A'
  const oldA = take('/inspect/A')
  store.activeHostId = 'B'
  await respond(take('/inspect/B'), inspection([]))
  await respond(oldA, inspection(['old-a']))
  assert.deepEqual(store.dockerContainers, [], 'Accept empty lists and reject old host response')
  assert.equal(store.dockerContainersLoading, false)
  assert.equal(store.dockerContainersError, '')
  store.activeHostId = ''
  console.log('PASS: Docker start/stop/restart requests, conflict prevention, failure, host switching and empty list isolation')
} finally {
  await vite.close()
  globalThis.fetch = originalFetch
}
